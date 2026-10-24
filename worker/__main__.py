"""Jar memo worker: picks up memos the server stored, transcribes them, lets the local
model file them, and records everything in the memo's .json and the daily memo log.

    python -m worker            run forever (poll every few seconds)
    python -m worker --once     process what's waiting, then exit
    python -m worker --check    check Whisper/Ollama setup and exit
    python -m worker --warmup   download/load Whisper, transcribe 1 s of silence, report GPU or CPU
    python -m worker --retry-failed   put failed memos back in the queue
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config as config_mod
from .agent import Agent, OllamaUnavailable
from .memos import MemoFile, pending
from .tools import MemoContext, Notes
from .transcribe import Transcriber

log = logging.getLogger("jar")


def setup_logging(data_dir: Path) -> None:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(data_dir / "logs" / "worker.log", maxBytes=2_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [fh]
    if sys.stdout and sys.stdout.isatty():
        # Also print to the console when run by hand (not when start-jar.ps1 runs it hidden).
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    # Only Jar's own messages at INFO; libraries (Hugging Face downloads, httpx…) only when something is wrong.
    root.setLevel(logging.WARNING)
    logging.getLogger("jar").setLevel(logging.INFO)


class SingleInstance:
    """Holds an OS file lock so two workers never process the same memo. Released on exit/crash."""

    def __init__(self, path: Path):
        self.f = open(path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(f"another worker is already running (lock: {path})")


def recorded_local(meta: dict, tz: ZoneInfo) -> datetime:
    raw = meta.get("recorded_at") or meta.get("received_at")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        dt = datetime.now(timezone.utc)
    return dt.astimezone(tz)


class Worker:
    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.transcriber = Transcriber(cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute,
                                       cfg.whisper_language, cfg.vocabulary, cfg.whisper_vad, cfg.whisper_normalize)
        self.agent = Agent(cfg.ollama_url, cfg.llm_model, cfg.temperature, cfg.keep_alive, cfg.max_rounds,
                           about=cfg.about, think=cfg.think, num_ctx=cfg.num_ctx)
        from .accounts import build as build_accounts
        self.accounts = build_accounts(cfg)   # personal -> Outlook, school -> Google (None if not set up)
        from .family import Family
        from .taskstore import TaskStore
        self.family = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
        from .accounts import build_family
        self.family_account = build_family(cfg, self.family)   # the family's own Jar Gmail, or None
        from .points import PointsConfig, PointsStore
        self.points = PointsStore(cfg.data_dir / "points.json", self.family, cfg.timezone,
                                  PointsConfig.from_raw(cfg.points))
        self.tasks = TaskStore(cfg.data_dir / "tasks.json", self.family, cfg.notes_dir / "Tasks.md", self.points)
        self._rate_retry_at = 0.0
        try:
            n = self.tasks.import_markdown(self.family.admin)
            if n:
                log.info("moved %d open task(s) from Tasks.md into the family task list", n)
            self.tasks.purge_old()
        except Exception:  # noqa: BLE001
            log.exception("task list housekeeping failed")
        self._ollama_warned = False
        self._ollama_problem = ""
        self.account_status: dict = {}

    def process(self, m: MemoFile) -> None:
        log.info("memo %s (%s, %.1f s, %s)", m.id, m.status, m.meta.get("duration_ms", 0) / 1000,
                 m.meta.get("device_id", "?"))
        try:
            if m.status == "received":
                t = self.transcriber.transcribe(m.wav)
                m.wav.with_suffix(".txt").write_text(t.text + "\n", encoding="utf-8")
                m.update(status="transcribed", transcript=t.text, language=t.language,
                         language_probability=t.language_probability, transcribe_seconds=t.seconds,
                         whisper=f"{self.cfg.whisper_model}/{self.transcriber.device}", error=None)
                log.info("  transcript (%s, %.1f s): %s", t.language, t.seconds, t.text[:200] or "(no speech)")
            if m.status == "transcribed":
                self.route(m)
        except OllamaUnavailable as e:
            # Not the memo's fault: keep it as "transcribed" and try again next poll.
            if not self._ollama_warned or str(e) != self._ollama_problem:
                log.warning("  waiting for Ollama: %s", e)
            self._ollama_warned, self._ollama_problem = True, str(e)
            raise
        except Exception as e:  # noqa: BLE001
            attempts = m.meta.get("attempts", 0) + 1
            failed = attempts >= self.cfg.max_attempts
            m.update(attempts=attempts, error=f"{type(e).__name__}: {e}", status="failed" if failed else m.status)
            log.exception("  %s (attempt %d/%d)", "gave up" if failed else "error", attempts,
                          self.cfg.max_attempts)

    def route(self, m: MemoFile) -> None:
        when = recorded_local(m.meta, self.tz)
        speaker = self.family.get(m.meta.get("person")) or self.family.admin
        if speaker.admin:
            notes = Notes(self.cfg.notes_dir, self.tz, MemoContext(m.id, when), accounts=self.accounts,
                          store=self.tasks, family=self.family, speaker=speaker, join_info=self.join_info,
                          family_account=self.family_account)
        else:
            # Everyone else's notes and memo log live in their own folder; no access to the admin's
            # calendars or email.
            from .tools import slug
            notes = Notes(self.cfg.notes_dir / "Family" / slug(speaker.name), self.tz, MemoContext(m.id, when),
                          store=self.tasks, family=self.family, speaker=speaker, join_info=self.join_info,
                          family_account=self.family_account)
        if m.meta.get("actions"):
            # Filed before (Re-file / edited transcript): drop the family events and open tasks that filing made.
            self.forget_events(m.meta.get("actions") or [])
            n = self.tasks.forget_memo(speaker, m.id)
            if n:
                log.info("  re-filing: removed %d task(s) from the earlier filing", n)
        text = (m.meta.get("transcript") or "").strip()
        if not text:
            notes.log_memo(m.meta.get("duration_ms", 0), m.meta.get("device_id", "?"), "", m.meta.get("language", ""),
                           "No speech found.")
            m.update(status="done", actions=[], summary="No speech found.", processed_at=_now())
            log.info("  no speech: nothing to file")
            return
        r = self.agent.run(text, notes, when, self.cfg.timezone, m.meta)
        self._ollama_warned, self._ollama_problem = False, ""
        notes.log_memo(m.meta.get("duration_ms", 0), m.meta.get("device_id", "?"), text,
                       m.meta.get("language", ""), r.summary)
        m.update(status="done", actions=r.actions, summary=r.summary, llm=self.cfg.llm_model,
                 llm_seconds=r.seconds, llm_rounds=r.rounds, fallback=r.fallback, processed_at=_now(), error=None,
                 llm_tokens=r.tokens)
        if r.tokens:
            share = r.tokens["peak"] / r.tokens["num_ctx"]
            (log.warning if share > 0.85 else log.info)(
                "  context: peak %d of %d tokens (%d%%; prompt %d, model wrote %d)%s", r.tokens["peak"],
                r.tokens["num_ctx"], round(share * 100), r.tokens["prompt"], r.tokens["output"],
                " — near the limit: raise [llm] num_ctx" if share > 0.85 else "")
        log.info("  done in %.1f s: %s", r.seconds, "; ".join(a["summary"] for a in r.actions))

    def forget_events(self, actions: list[dict]) -> None:
        """Re-filing: take back the family-calendar events the earlier filing made."""
        for a in actions:
            if a.get("tool") == "family_event" and a.get("event_id") and self.family_account is not None:
                try:
                    self.family_account.delete_family_event(a["event_id"])
                    log.info("  re-filing: removed family event %s", a.get("summary", a["event_id"]))
                except Exception as e:  # noqa: BLE001
                    log.warning("  re-filing: couldn't remove family event %s: %s", a["event_id"], e)

    def sync_event_deletes(self) -> int:
        """A deleted follow-up task ("add details or delete it") deletes its calendar event too."""
        if self.family_account is None or self.tasks is None:
            return 0
        n = 0
        for t in self.tasks.events_to_delete():
            ev = t["event"]
            try:
                self.family_account.delete_family_event(ev["id"])
            except Exception as e:  # noqa: BLE001 — try again next poll
                log.warning("couldn't delete family event “%s”: %s", ev.get("title", ev["id"]), e)
                continue
            self.tasks.event_removed(t["id"])
            log.info("deleted family event “%s” %s (its task was deleted)", ev.get("title", ""), ev.get("date", ""))
            n += 1
        return n

    def join_info(self, person) -> dict:
        """What someone needs to start using Jar: the download page and, for family members, their own
        pairing link (token + this PC's addresses), and the tappable join page when the PC is public."""
        from . import join
        info = {"download": join.DOWNLOAD, "pair_link": "", "join_url": ""}
        if person is not None:
            try:
                from server import pairing
                urls = pairing.pairing_urls(pairing.discover(), self.cfg.port)
                info["pair_link"] = pairing.pairing_link(self.family.token_for(person.id), urls)
                info["join_url"] = join.join_url(urls, info["pair_link"])
            except Exception as e:  # noqa: BLE001
                log.warning("  pairing link unavailable: %s", e)
        return info

    def heartbeat(self, doing: str = "idle") -> None:
        """data/worker.json: lets the dashboard and start-jar.ps1 -Status see the worker is alive."""
        import json
        import os
        import time as _t
        hb = {"pid": os.getpid(), "epoch": _t.time(), "at": _now(), "doing": doing,
              "whisper": f"{self.cfg.whisper_model} on {self.transcriber.device}",
              "llm": self.cfg.llm_model, "ollama_waiting": self._ollama_warned,
              "ollama_problem": self._ollama_problem[:300], "accounts": self.account_status, "gpu": self.gpu_fit()}
        tmp = self.cfg.data_dir / "worker.json.tmp"
        try:
            tmp.write_text(json.dumps(hb), encoding="utf-8")
            os.replace(tmp, self.cfg.data_dir / "worker.json")
        except OSError:
            pass  # never let the heartbeat stop real work

    def gpu_fit(self) -> str:
        """How much of the loaded model Ollama has on the GPU ("100% GPU", "78% GPU / 22% CPU", "not loaded"),
        from /api/ps, checked at most once a minute. A model that spills to the CPU gets slow: lower
        [llm] num_ctx, or run tools/ollama-tuning.ps1."""
        import json
        import time as _t
        import urllib.request
        if _t.monotonic() - getattr(self, "_gpu_at", -1e9) < 60:
            return getattr(self, "_gpu", "")
        self._gpu_at, self._gpu = _t.monotonic(), "unknown"
        try:
            with urllib.request.urlopen(self.cfg.ollama_url + "/api/ps", timeout=3) as r:
                models = json.loads(r.read().decode()).get("models", [])
        except Exception:  # noqa: BLE001
            return self._gpu
        m = next((x for x in models if x.get("name", "").split(":")[0] == self.cfg.llm_model.split(":")[0]), None)
        if m is None:
            self._gpu = "not loaded"
            return self._gpu
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        pct = round(100 * vram / size) if size else 0
        ctx = m.get("context_length")
        self._gpu = (f"{pct}% GPU" if pct >= 100 else f"{pct}% GPU / {100 - pct}% CPU") + \
            f", {size / 2**30:.1f} GB" + (f", ctx {ctx}" if ctx else "")
        if pct < 100 and not getattr(self, "_gpu_warned", False):
            log.warning("Ollama: %s — part of the model runs on the CPU (slower). Lower [llm] num_ctx or run "
                        "tools/ollama-tuning.ps1", self._gpu)
            self._gpu_warned = True
        elif pct >= 100 and not getattr(self, "_gpu_logged", False):
            log.info("Ollama: %s", self._gpu)
            self._gpu_logged = True
        return self._gpu

    def retry_failed(self) -> int:
        n = 0
        for meta_path in (self.cfg.data_dir / "memos").glob("*/*.json"):
            import json
            m = MemoFile(meta_path, json.loads(meta_path.read_text(encoding="utf-8")))
            if m.status == "failed":
                m.update(status="transcribed" if m.meta.get("transcript") else "received", attempts=0, error=None)
                n += 1
        log.info("re-queued %d failed memo(s)", n)
        return n

    def rate_pending(self, limit: int = 4) -> int:
        """Give every new task its effort rating (what it is worth in coins), newest first. Needs Ollama;
        when it is away the tasks wait and are tried again in two minutes."""
        if time.time() < self._rate_retry_at:
            return 0
        from . import effort
        n = 0
        areas = self.tasks.areas()
        for t in self.tasks.unrated(limit):
            who = self.family.get(t.get("assignee")) or self.family.admin
            todo = [] if t.get("area") else areas          # the AI picks an area only when no keyword did
            self.heartbeat("rating tasks")
            try:
                rating = effort.rate(self.cfg.ollama_url, self.cfg.llm_model, t.get("title", ""), t.get("notes", ""),
                                     who, self.points.known_keys(), self.points.parent_effort,
                                     self.cfg.num_ctx, self.cfg.keep_alive, areas=todo)
            except effort.RateError as e:
                log.warning("  can't rate tasks right now: %s", e)
                self._rate_retry_at = time.time() + 120
                break
            if self.tasks.rate(t["id"], rating):
                n += 1
                log.info("  rated “%s” for %s: effort %s (%s, %s min) — %s%s", t.get("title", "")[:40], who.id,
                         rating.get("effort"), rating.get("chore_key"), rating.get("minutes"), rating.get("reason"),
                         f" · area {rating['area']}" if rating.get("area") else "")
        return n

    def maybe_asr_bench(self) -> None:
        """data/eval/asr-run exists: compare Whisper models on the real memos (worker/asr_bench.py) while idle."""
        import json
        flag = self.cfg.data_dir / "eval" / "asr-run"
        if not flag.exists():
            return
        try:
            txt = flag.read_text(encoding="utf-8", errors="ignore").strip()
            flag.unlink()
            args = json.loads(txt) if txt.startswith("{") else {}
        except (OSError, ValueError):
            args = {}
        from . import asr_bench
        self.heartbeat("comparing speech models")
        log.info("ASR bench: comparing speech models on real memos")
        self.transcriber.close()                     # free the GPU; it loads again for the next memo
        try:
            rep = asr_bench.run(self.cfg, limit=int(args.get("limit", 40)), person=str(args.get("person", "")),
                                keys=args.get("candidates"))
            log.info("ASR bench done in %s s: %s (data/eval/asr/report.md)", rep["seconds"], rep["recommendation"])
        except Exception:  # noqa: BLE001
            log.exception("ASR bench failed")

    def maybe_eval(self) -> None:
        """data/eval/run exists (VS Code task, or remotely): run the sample memos while idle."""
        self.maybe_asr_bench()
        flag = self.cfg.data_dir / "eval" / "run"
        if not flag.exists():
            return
        try:
            txt = flag.read_text(encoding="utf-8", errors="ignore").strip()
            flag.unlink()
        except OSError:
            return
        from . import evaluate
        repeats, models = evaluate.parse_models(txt)      # "3" = each memo 3 times; "1 m1 m2/nothink" = compare
        self.heartbeat("testing the AI on sample memos")
        if models:
            log.info("AI test: comparing %s", ", ".join(m + ("" if t else "/nothink") for m, t in models))
            try:
                rep = evaluate.compare(self.cfg, models, repeats)
                log.info("AI test compare: %s (data/eval/compare.md)", "; ".join(
                    f"{r['model']} {r['passed']}/{r['total']}" if "passed" in r else f"{r['model']} {r['missing']}"
                    for r in rep["rows"]))
            except Exception:  # noqa: BLE001
                log.exception("AI test compare failed")
            return
        log.info("AI test: running the sample memos")
        try:
            rep = evaluate.run(self.cfg, repeats=repeats)
            log.info("AI test: %d/%d passed in %.0f s (data/eval/report.md)", rep["passed"], rep["total"],
                     rep["seconds"])
        except Exception:  # noqa: BLE001
            log.exception("AI test failed to run")

    def run_once(self) -> int:
        n = 0
        for m in pending(self.cfg.data_dir):
            self.heartbeat(f"memo {m.id}")
            try:
                self.process(m)
            except OllamaUnavailable:
                break  # every later memo needs Ollama too
            n += 1
        try:
            if self.tasks is not None and self.tasks.roll():
                log.info("recurring tasks: today's made")
                n_old = self.tasks.purge_old()      # once a day, with the roll: the parents' archive setting
                if n_old:
                    log.info("archive: removed %d finished task(s) past the parents' keep setting", n_old)
        except Exception:  # noqa: BLE001 — never stops memos
            log.exception("rolling recurring tasks failed")
        try:
            self.sync_event_deletes()
        except Exception:  # noqa: BLE001 — never stops memos
            log.exception("syncing deleted events failed")
        try:
            self.rate_pending()
        except Exception:  # noqa: BLE001 — a rating problem must never stop memos
            log.exception("rating tasks failed")
        if n == 0:
            self.maybe_eval()
        self.heartbeat()
        return n

    def warmup(self) -> bool:
        import tempfile
        import wave
        silence = Path(tempfile.gettempdir()) / "jar-warmup.wav"
        with wave.open(str(silence), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16000)
            f.writeframes(b"\0\0" * 16000)
        try:
            t = self.transcriber.transcribe(silence)
        except Exception:  # noqa: BLE001
            log.exception("Whisper warm-up failed")
            return False
        log.info("Whisper OK on %s (%s), test took %.1f s", self.transcriber.device,
                 self.transcriber.compute_type, t.seconds)
        return True

    def check(self) -> bool:
        ok = True
        problem = self.agent.ping()
        log.info("Ollama: %s", problem or f"ok, model {self.cfg.llm_model} available")
        ok &= problem is None
        log.info("Whisper: %s on %s (%s)", self.cfg.whisper_model, self.transcriber.device,
                 self.transcriber.compute_type)
        log.info("Data: %s   Notes: %s", self.cfg.data_dir, self.cfg.notes_dir)
        self.account_status = {}
        for role, conn in {**self.accounts, "family": self.family_account}.items():
            try:
                who = conn.account() if conn else None
            except Exception:  # noqa: BLE001
                who = None
            self.account_status[role] = {"provider": conn.name if conn else "", "who": who or ""}
            log.info("Account %s: %s", role, f"{conn.name}, {'connected as ' + who if who else 'not connected (falls back to files)'}"
                     if conn else "not configured")
        return ok


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m worker")
    p.add_argument("--once", action="store_true", help="process waiting memos and exit")
    p.add_argument("--check", action="store_true", help="check setup and exit")
    p.add_argument("--warmup", action="store_true", help="download + load Whisper and test it")
    p.add_argument("--retry-failed", action="store_true", help="put failed memos back in the queue and exit")
    p.add_argument("--config", type=Path)
    a = p.parse_args()

    cfg = config_mod.load(a.config)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(cfg.data_dir)
    w = Worker(cfg)
    if a.check:
        raise SystemExit(0 if w.check() else 1)
    if a.warmup:
        raise SystemExit(0 if w.warmup() else 1)
    if a.retry_failed:
        w.retry_failed()
        return

    _lock = SingleInstance(cfg.data_dir / "worker.lock")  # noqa: F841 — held for the process lifetime
    log.info("Jar worker started — Whisper %s, LLM %s, notes in %s", cfg.whisper_model, cfg.llm_model,
             cfg.notes_dir)
    w.check()
    if a.once:
        w.run_once()
        return
    try:
        while True:
            try:
                w.run_once()
            except Exception:  # noqa: BLE001 — the loop must survive anything
                log.exception("unexpected error in loop")
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
