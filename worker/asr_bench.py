"""ASR bench: compares Whisper models and settings on the family's REAL memos (read-only).

    python -m worker.asr_bench                 (or: write data/eval/asr-run; the worker runs it while idle)
    data/eval/asr-run may hold JSON: {"limit": 40, "person": "alona", "candidates": ["base", "parakeet-he"],
                                      "cloud": true, "cloud_model": "gemini-3.5-transcribe"}

Per memo the reference is, in this order: the human-corrected transcript when the memo was fixed in the
dashboard ("edited"); else Gemini's transcript when a Gemini key is set up (worker/cloud_ref.py, opt-in, cached,
"cloud"); else the slow ivrit large-v3 output ("auto", not human). Only the human group is fully trustworthy; the
report also scores Gemini itself on the hand-corrected memos, to show how far the cloud reference can be trusted. Metrics: WER, CER, deletion rate (dropped words: the complaint) and RTF (seconds of work per
second of audio), overall and per person. Writes data/eval/asr/report.md + report.json — private (data/ is
gitignored): they contain the family's transcripts.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import unicodedata
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("jar.asr_bench")

IVRIT_TURBO = "ivrit-ai/whisper-large-v3-turbo-ct2"
IVRIT_LARGE = "ivrit-ai/whisper-large-v3-ct2"
PARAKEET_HE = "thewh1teagle/parakeet-tdt-0.6b-v3-he"


@dataclass
class Candidate:
    key: str
    label: str
    model: str            # "" = the configured model
    vad: str = "default"
    normalize: bool = False
    language: str | None = None   # None = the configured language
    clean: str = ""               # audio cleanup steps (transcribe.clean)
    vocab: str = "config"         # "config" = [transcribe] vocabulary; "family" = + the family's names (and Gemini's list)
    runner: str = ""              # not faster-whisper: "parakeet", run by worker/asr_runner.py in its own env
    env: str = ""                 # that env (worker/asr_extra.py ENVS)


CANDIDATES = [
    Candidate("base", "current settings", ""),
    Candidate("ivrit-gentle", "ivrit turbo + gentle VAD + normalize", IVRIT_TURBO, "gentle", True, "he"),
    Candidate("ivrit-novad", "ivrit turbo, VAD off", IVRIT_TURBO, "off", True, "he"),
    Candidate("ivrit-large", "ivrit large-v3 + gentle VAD + normalize (auto reference)", IVRIT_LARGE, "gentle", True,
              "he"),
    # audio cleanup and the family's words on the production setup: no gain on 11-09, kept to re-check with more
    # hand-fixed memos (denoise and trim made it worse and were dropped)
    Candidate("clean-hp", "production + rumble/hum filter", IVRIT_TURBO, "gentle", True, "he", "hp"),
    Candidate("clean-loud", "production + filter + steady level (up to 30x)", IVRIT_TURBO, "gentle", True, "he",
              "hp,loud"),
    Candidate("vocab-family", "production + family names in the vocabulary", IVRIT_TURBO, "gentle", True, "he",
              vocab="family"),
    # Parakeet: as accurate as production on 11-09 and ~7x faster; runs in its own environment (data/asr-envs/tf5).
    # Caspi-1.7B, qwen-asr-0.6b-he and the LLM-combined transcripts were tried on 11-09 and dropped.
    Candidate("parakeet-he", "Parakeet TDT 0.6B v3 Hebrew", PARAKEET_HE, runner="parakeet", env="tf5"),
]
REFERENCE = "ivrit-large"
MIN_WORDS = 60            # a group needs this many reference words before it decides the recommendation

# ---------------------------------------------------------------- scoring (pure)

NIQQUD = re.compile(r"[֑-ׇ]")
FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})


def norm_text(text: str) -> str:
    """For scoring only: no niqqud, punctuation, geresh/gershayim or final-letter differences, lower case."""
    t = unicodedata.normalize("NFC", text or "")
    t = NIQQUD.sub("", t)
    t = re.sub(r"[׳״'\"`’‘“”]", "", t)          # geresh, gershayim and their ASCII stand-ins
    t = re.sub(r"[^\w\s]", " ", t)                          # punctuation (and maqaf) → space
    t = t.translate(FINALS).lower()
    return re.sub(r"\s+", " ", t).strip()


def edit_ops(ref: list, hyp: list) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) turning ref into hyp, minimal total (Levenshtein with counts)."""
    n, m = len(ref), len(hyp)
    # cost, S, D, I per cell; keep two rows
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                best = prev[j - 1]
            else:
                c_s, c_d, c_i = prev[j - 1], prev[j], cur[j - 1]
                options = [(c_s[0] + 1, c_s[1] + 1, c_s[2], c_s[3]),
                           (c_d[0] + 1, c_d[1], c_d[2] + 1, c_d[3]),
                           (c_i[0] + 1, c_i[1], c_i[2], c_i[3] + 1)]
                best = min(options, key=lambda o: (o[0], -o[2]))   # tie: count it as a deletion
            cur.append(best)
        prev = cur
    _, s, d, ins = prev[m]
    return s, d, ins


def score(ref: str, hyp: str) -> dict:
    rw, hw = norm_text(ref).split(), norm_text(hyp).split()
    s, d, i = edit_ops(rw, hw)
    rc, hc = list(norm_text(ref).replace(" ", "")), list(norm_text(hyp).replace(" ", ""))
    cs, cd, ci = edit_ops(rc, hc)
    n, nc = max(1, len(rw)), max(1, len(rc))
    return {"words": len(rw), "wer": (s + d + i) / n, "del": d / n, "sub": s / n, "ins": i / n,
            "cer": (cs + cd + ci) / nc, "S": s, "D": d, "I": i}


def aggregate(rows: list[dict]) -> dict:
    """Word-weighted totals over memos (not an average of per-memo rates)."""
    words = sum(r["words"] for r in rows)
    if not rows or not words:
        return {"n": len(rows), "words": 0}
    S, D, I = (sum(r[k] for r in rows) for k in ("S", "D", "I"))
    audio = sum(r.get("audio_s", 0) for r in rows)
    work = sum(r.get("seconds", 0) for r in rows)
    return {"n": len(rows), "words": words, "wer": (S + D + I) / words, "del": D / words, "sub": S / words,
            "ins": I / words, "rtf": (work / audio) if audio else None}

# ---------------------------------------------------------------- memos


@dataclass
class Memo:
    id: str
    wav: Path
    person: str
    recorded_at: str
    human_ref: str = ""          # the dashboard-corrected transcript, when there is one
    production: str = ""         # what Jar actually heard
    cloud_ref: str = ""          # Gemini's transcript (cloud_ref.py), when the bench asked for one
    shadow: str = ""             # the shadow model's reading saved at the time (worker/shadow.py)
    shadow_model: str = ""
    audio_s: float = 0.0
    hyps: dict = field(default_factory=dict)      # candidate key -> {"text", "seconds"}


def audio_seconds(wav: Path) -> float:
    try:
        with wave.open(str(wav), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except (wave.Error, OSError, EOFError):
        return 0.0


def select(memo_dir: Path, family, limit: int = 40, person: str = "") -> list[Memo]:
    """All hand-corrected memos first (human references), then the kids', then the newest others."""
    found = []
    for j in memo_dir.glob("*/*.json"):
        wav = j.with_suffix(".wav")
        if not wav.exists():
            continue
        try:
            m = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        who = m.get("person") or (family.admin.id if family else "")
        if person and who != person:
            continue
        found.append(Memo(m.get("id") or j.stem, wav, who, m.get("recorded_at") or "",
                          human_ref=(m.get("transcript") or "") if (m.get("edited") or m.get("checked")) else "",
                          production=m.get("original_transcript") or m.get("transcript") or "",
                          shadow=(m.get("shadow") or {}).get("text") or "",
                          shadow_model=(m.get("shadow") or {}).get("model") or ""))
    def is_kid(mm):
        p = family.get(mm.person) if family else None
        return p is not None and not p.is_parent
    found.sort(key=lambda mm: (not mm.human_ref, not is_kid(mm), "" if not mm.recorded_at else
                               "~" + "".join(chr(0x10FFFF - ord(c)) for c in mm.recorded_at)))
    out = found[:max(1, limit)]
    for mm in out:
        mm.audio_s = audio_seconds(mm.wav)
    return out

# ---------------------------------------------------------------- running


def free_llm(ollama_url: str, model: str) -> None:
    """Unload the LLM from VRAM so each Whisper candidate has the GPU to itself."""
    try:
        body = json.dumps({"model": model, "keep_alive": 0}).encode()
        req = urllib.request.Request(ollama_url.rstrip("/") + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:  # noqa: BLE001
        log.info("couldn't unload the LLM (%s); carrying on", e)


def choose(keys: list[str] | None) -> list[Candidate]:
    """The candidates named (plus the auto reference), or all of them."""
    if keys:
        want = set(keys) | {REFERENCE}
        return [c for c in CANDIDATES if c.key in want]
    return list(CANDIDATES)


def run(cfg=None, limit: int = 40, person: str = "", keys: list[str] | None = None, out_dir: Path | None = None,
        make=None, cloud: bool | None = None, cloud_model: str = "", cloud_post=None, beat=None, **_old) -> dict:
    """make(candidate, cfg) -> an object with transcribe(wav) -> .text and close(); default: Transcriber, or
    asr_extra.ExternalTranscriber for runner candidates. beat() keeps the worker's heartbeat fresh during long
    installs and downloads.
    cloud: None = use Gemini references when a key is set up, False = never, True = report it when it can't."""
    from . import config as config_mod
    from .family import Family
    cfg = cfg or config_mod.load()
    out_dir = out_dir or cfg.data_dir / "eval" / "asr"
    out_dir.mkdir(parents=True, exist_ok=True)
    fam = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
    memos = select(cfg.data_dir / "memos", fam, limit, person)
    cands = choose(keys)
    cloud_status = None
    if cloud is not False:
        from . import cloud_ref
        cloud_status = cloud_ref.references(memos, cfg, fam, out_dir, cloud_model or cloud_ref.DEFAULT_MODEL,
                                            post=cloud_post)
        if cloud is None and cloud_status["error"].startswith("no key"):
            cloud_status = None
        else:
            log.info("ASR bench: Gemini references %s", cloud_status)
    from .cloud_ref import vocabulary as vocab_list
    family_vocab = ", ".join(vocab_list(cfg, fam))
    if make is None:
        free_llm(cfg.ollama_url, cfg.llm_model)

        def make(c, cfg):
            if c.runner:
                from .asr_extra import ExternalTranscriber, ensure_env
                py = ensure_env(cfg.data_dir, c.env, beat)
                return ExternalTranscriber(py, c.runner, c.model, c.language or "", out_dir / f"{c.key}.log", beat)
            from .transcribe import Transcriber
            return Transcriber(c.model or cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute,
                               cfg.whisper_language if c.language is None else c.language,
                               family_vocab if c.vocab == "family" else cfg.vocabulary, c.vad, c.normalize, c.clean)
    t_all = time.monotonic()
    errors = {}
    for c in cands:
        log.info("ASR bench: %s on %d memos", c.key, len(memos))
        if beat:
            beat()
        try:
            tr = make(c, cfg)
        except Exception as e:  # noqa: BLE001
            errors[c.key] = f"{type(e).__name__}: {e}"
            continue
        try:
            for mm in memos:
                t0 = time.monotonic()
                try:
                    text = tr.transcribe(mm.wav).text
                except Exception as e:  # noqa: BLE001
                    errors[c.key] = f"{type(e).__name__}: {e}"
                    break
                mm.hyps[c.key] = {"text": text, "seconds": round(time.monotonic() - t0, 2)}
        finally:
            try:
                tr.close()
            except Exception:  # noqa: BLE001
                pass
    report = build_report(memos, cands, fam, errors, round(time.monotonic() - t_all), cloud_status)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(render(report), encoding="utf-8")
    return report


def reference(mm: Memo) -> tuple[str, str]:
    if mm.human_ref:
        return mm.human_ref, "human"
    if mm.cloud_ref:
        return mm.cloud_ref, "cloud"
    return mm.hyps.get(REFERENCE, {}).get("text", ""), "auto"


def build_report(memos: list[Memo], cands: list[Candidate], fam, errors: dict, seconds: int,
                 cloud_status: dict | None = None) -> dict:
    name = lambda pid: (fam.get(pid).name if fam and fam.get(pid) else pid)  # noqa: E731
    rows: dict[str, list] = {c.key: [] for c in cands}
    for mm in memos:
        ref, kind = reference(mm)
        if not ref:
            continue
        for c in cands:
            h = mm.hyps.get(c.key)
            if h is None or (kind == "auto" and c.key == REFERENCE):
                continue
            r = score(ref, h["text"])
            r.update(memo=mm.id, person=mm.person, kind=kind, seconds=h["seconds"], audio_s=mm.audio_s)
            rows[c.key].append(r)
    summary = {}
    for c in cands:
        rs = rows[c.key]
        summary[c.key] = {
            "label": c.label, "error": errors.get(c.key),
            "human": aggregate([r for r in rs if r["kind"] == "human"]),
            "cloud": aggregate([r for r in rs if r["kind"] == "cloud"]),
            "auto": aggregate([r for r in rs if r["kind"] == "auto"]),
            "people": {name(p): aggregate([r for r in rs if r["person"] == p]) for p in sorted({r["person"] for r in rs})},
            "rtf": aggregate([dict(r) for r in rs]).get("rtf"),
        }
    # How good is the cloud reference itself? Gemini against the hand-corrected memos.
    check = [dict(score(m.human_ref, m.cloud_ref), person=m.person) for m in memos if m.human_ref and m.cloud_ref]
    cloud = None
    if cloud_status is not None:
        cloud = dict(cloud_status, refs=sum(1 for m in memos if m.cloud_ref and not m.human_ref),
                     vs_human=aggregate(check))
    # Real use: what production heard vs what the shadow model heard, on memos people fixed by hand
    both = [m for m in memos if m.human_ref and m.shadow]
    live = None
    if both:
        live = {"memos": len(both), "model": both[-1].shadow_model,
                "production": aggregate([score(m.human_ref, m.production) for m in both]),
                "shadow": aggregate([score(m.human_ref, m.shadow) for m in both])}
    return {"memos": len(memos), "human_refs": sum(1 for m in memos if m.human_ref), "seconds": seconds,
            "cloud": cloud, "live": live, "summary": summary, "recommendation": recommend(summary),
            "samples": [{"id": m.id, "person": name(m.person), "audio_s": round(m.audio_s, 1),
                         "human_ref": m.human_ref, "cloud_ref": m.cloud_ref, "production": m.production,
                         "shadow": m.shadow,
                         "hyps": {k: v["text"] for k, v in m.hyps.items()}} for m in memos]}


def recommend(summary: dict) -> str:
    """Lowest WER on the human-corrected memos when there are enough of them, else lowest WER against Gemini,
    else lowest deletion rate on the auto group (the reference itself is excluded there)."""
    def pick(group: str, metric: str, min_words: int):
        ok = [(v[group][metric], k) for k, v in summary.items()
              if v[group].get("words", 0) >= min_words and metric in v[group] and not v.get("error")
              and not (group == "auto" and k == REFERENCE)]
        return min(ok) if ok else None
    best = pick("human", "wer", MIN_WORDS)
    if best:
        return f"{best[1]} ({summary[best[1]]['label']}): lowest WER on hand-corrected memos ({best[0]:.1%})"
    best = pick("cloud", "wer", MIN_WORDS)
    if best:
        return (f"{best[1]} ({summary[best[1]]['label']}): lowest WER against Gemini's transcripts ({best[0]:.1%}) "
                "— a strong reference but not a human one; check Gemini's own score on the corrected memos")
    best = pick("auto", "del", MIN_WORDS)
    if best:
        return (f"{best[1]} ({summary[best[1]]['label']}): fewest dropped words against the auto reference "
                f"({best[0]:.1%}) — not enough hand-corrected memos to be sure; correct a few kids' memos in the "
                "dashboard and run again")
    return "not enough data: correct some memos in the dashboard and run again"


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def render(r: dict) -> str:
    L = [f"# ASR bench: {r['memos']} memos ({r['human_refs']} hand-corrected), {r['seconds']} s", "",
         f"**Recommendation:** {r['recommendation']}", "",
         "WER = word error rate, Del = dropped words, CER = character errors, RTF = work seconds per audio second.",
         "Human = against the dashboard-corrected text (trustworthy); cloud = against Gemini (memos nobody corrected);",
         "auto = against ivrit large-v3 (not human; only when there's no Gemini transcript).", ""]
    c = r.get("cloud")
    if c:
        vh = c.get("vs_human") or {}
        L += [f"**Gemini reference** ({c['model']}): {c['refs']} memos used it; {c['sent']} sent now, "
              f"{c['cached']} from the cache, {c['failed']} failed" + (f" — {c['error']}" if c.get("error") else "") + ".",
              f"Gemini on the hand-corrected memos: WER {_pct(vh.get('wer'))}, dropped {_pct(vh.get('del'))} "
              f"({vh.get('words', 0)} words).", ""]
    lv = r.get("live")
    if lv:
        L += [f"**Real use** ({lv['memos']} hand-fixed memos that also have a shadow reading): production WER "
              f"{_pct(lv['production'].get('wer'))}, dropped {_pct(lv['production'].get('del'))} · shadow "
              f"{lv['model']} WER {_pct(lv['shadow'].get('wer'))}, dropped {_pct(lv['shadow'].get('del'))}.", ""]
    L += ["| candidate | human WER | human Del | cloud WER | cloud Del | auto WER | auto Del | RTF |",
          "|---|---|---|---|---|---|---|---|"]
    for k, v in r["summary"].items():
        h, cl, a = v["human"], v.get("cloud", {}), v["auto"]
        rtf = "—" if v.get("rtf") is None else f"{v['rtf']:.2f}"
        err = f" — ERROR {v['error']}" if v.get("error") else ""
        L.append(f"| {k}: {v['label']}{err} | {_pct(h.get('wer'))} ({h.get('words', 0)} w) | {_pct(h.get('del'))} | "
                 f"{_pct(cl.get('wer'))} ({cl.get('words', 0)} w) | {_pct(cl.get('del'))} | "
                 f"{_pct(a.get('wer'))} ({a.get('words', 0)} w) | {_pct(a.get('del'))} | {rtf} |")
    L += ["", "## Per person (all memos, WER / dropped)", ""]
    people = sorted({p for v in r["summary"].values() for p in v["people"]})
    L.append("| candidate | " + " | ".join(people) + " |")
    L.append("|---|" + "---|" * len(people))
    for k, v in r["summary"].items():
        L.append(f"| {k} | " + " | ".join(
            f"{_pct(v['people'].get(p, {}).get('wer'))} / {_pct(v['people'].get(p, {}).get('del'))}" for p in people) + " |")
    L += ["", "## Memos side by side", ""]
    for s in r["samples"][:30]:
        L.append(f"### {s['person']} · {s['audio_s']} s · `{s['id'][:8]}`")
        if s["human_ref"]:
            L.append(f"- **corrected:** {s['human_ref']}")
        if s.get("cloud_ref"):
            L.append(f"- **Gemini:** {s['cloud_ref']}")
        L.append(f"- *Jar heard:* {s['production']}")
        if s.get("shadow"):
            L.append(f"- *shadow heard:* {s['shadow']}")
        for k, t in s["hyps"].items():
            L.append(f"- {k}: {t}")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    rep = run(limit=int(args.get("limit", 40)), person=str(args.get("person", "")), keys=args.get("candidates"),
              cloud=args.get("cloud"), cloud_model=str(args.get("cloud_model", "")))
    print(rep["recommendation"])


if __name__ == "__main__":
    main()
