"""Sample memos with known right answers, run against the real local model.

    python -m worker.evaluate            (VS Code: More -> Test the AI on sample memos)

Everything happens in a throwaway folder: a copy of the family, an empty task list, no calendar or
email accounts. Your real tasks, notes, calendars and mail are never touched.
Writes data/eval/report.md and report.json. The worker also runs it when data/eval/run exists.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from . import config as config_mod
from .agent import Agent
from .family import Family
from .taskstore import TaskStore
from .tools import MemoContext, Notes

WHEN = (2026, 10, 12, 13, 0)        # a Monday, 13:00


@dataclass
class Case:
    name: str
    memo: str
    check: Callable[["Result"], str | None]    # None = pass, else what went wrong
    speaker: str = ""                          # family id; "" = the admin
    seed: list[dict] = field(default_factory=list)


@dataclass
class Result:
    actions: list[dict]
    tasks: list[dict]
    summary: str
    fam: Family

    def tools(self) -> list[str]:
        return [a["tool"] for a in self.actions]

    def new(self, kind: str = "task") -> list[dict]:
        return [t for t in self.tasks if not t.get("seeded") and t.get("kind", "task") == kind
                and t["status"] != "deleted"]

    def pid(self, name: str) -> str:
        p = self.fam.resolve(name)
        return p.id if p else name


def _one_task(r: Result, assignee: str, must_in_title: str = "", due: str | None = None) -> str | None:
    ts = r.new()
    if len(ts) != 1:
        return f"expected 1 new task, got {len(ts)} (tools: {r.tools()})"
    t = ts[0]
    if t["assignee"] != assignee:
        return f"task is for {t['assignee']}, should be {assignee}"
    if must_in_title and must_in_title not in t["title"]:
        return f"title “{t['title']}” lacks “{must_in_title}”"
    if due is not None and (t.get("due") or "") != due:
        return f"due {t.get('due')}, should be {due}"
    return None


def _message(r: Result, to: str, *must: str) -> str | None:
    ms = r.new("message")
    if len(ms) != 1:
        return f"expected 1 WhatsApp draft, got {len(ms)} (tools: {r.tools()})"
    m = ms[0]
    if m["to"] != to:
        return f"message to {m['to']}, should be {to}"
    for s in must:
        if not re.search(s, m["message"]):
            return f"message lacks {s!r}: {m['message'][:200]}"
    return None


def _seeded(r: Result, title: str) -> dict:
    return next(t for t in r.tasks if t.get("seeded") and t["title"] == title)


def cases(admin: str, fam: Family) -> list[Case]:
    def person(names: list[str]) -> str:
        for n in names:
            p = fam.resolve(n)
            if p:
                return p.id
        return names[0]
    wife, son, daughter = person(["sveta", "סווטה"]), person(["livne", "ליבנה"]), person(["alona", "אלונה"])
    name = lambda pid: fam.get(pid).name if fam.get(pid) else pid  # noqa: E731
    return [
        Case("errand about someone else stays mine",
             "לחדש את הביטוח של האוטו של סווטה",
             lambda r: _one_task(r, admin, "ביטוח")),
        Case("doing something for a child stays mine",
             "אני צריך לחבר לאלונה את הראש מיטה",
             lambda r: _one_task(r, admin, "מיטה")),
        Case("reminding a child goes to the child",
             "תזכיר לליבנה להוציא את הכלב בשש בערב",
             lambda r: _one_task(r, son, "כלב", "2026-10-12T18:00")),
        Case("join instructions contain the real steps",
             "לשלוח לליבנה בוואטסאפ הוראות איך להתקין את האפליקציה של Jar ולהצטרף",
             lambda r: _message(r, name(son), r"releases/latest", r"jar://pair")),
        Case("short WhatsApp message",
             "תשלח לסווטה שאני מגיע בשש",
             lambda r: _message(r, name(wife), r"(שש|18)")),
        Case("finishing a task by voice",
             "סיימתי למלא מים באוטו של סווטה",
             lambda r: (None if _seeded(r, "למלא מים באוטו של סווטה")["status"] == "done" and not r.new()
                        else f"task not marked done (tools: {r.tools()}, new tasks: {len(r.new())})"),
             seed=[{"title": "למלא מים באוטו של סווטה"}]),
        Case("moving a task by voice",
             "תעביר את התור לרופא שיניים ליום חמישי בעשר",
             lambda r: (None if _seeded(r, "תור לרופא שיניים").get("due") == "2026-10-15T10:00" and not r.new()
                        else f"due is {_seeded(r, 'תור לרופא שיניים').get('due')} (tools: {r.tools()})"),
             seed=[{"title": "תור לרופא שיניים", "due": "2026-10-14T09:00"}]),
        Case("appointment goes to the calendar",
             "קבע לי תור לרופא שיניים ביום רביעי בתשע בבוקר",
             lambda r: (f"no calendar event (tools: {r.tools()})" if "create_event" not in r.tools()
                        else None if any("2026-10-14 09:00" in a["summary"] for a in r.actions)
                        else f"wrong day/time: {[a['summary'] for a in r.actions]}")),
        Case("a child asking a parent makes a request",
             "תזכיר לאבא לקנות לי מחברת חשבון",
             lambda r: (_one_task(r, admin, "מחברת") or
                        (None if r.new()[0]["status"] == "requested" else "not a request")),
             speaker=son),
        Case("lesson idea",
             "רעיון לשיעור: להשתמש בבינגו כדי לתרגל פונקציות רציונליות בכיתה י'",
             lambda r: None if "save_lesson_idea" in r.tools() else f"not a lesson idea (tools: {r.tools()})"),
    ][:]


def run(cfg: config_mod.Config | None = None, out_dir: Path | None = None, repeats: int = 1) -> dict:
    cfg = cfg or config_mod.load()
    tz = ZoneInfo(cfg.timezone)
    agent = Agent(cfg.ollama_url, cfg.llm_model, cfg.temperature, cfg.keep_alive, cfg.max_rounds,
                  about=cfg.about, think=cfg.think)
    real = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
    results, t_all = [], time.monotonic()
    for c in [c for c in cases(real.admin.id, real) for _ in range(max(1, repeats))]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fam = Family.from_config(cfg.family or {}, "eval-token", tmp, cfg.contacts)
            store = TaskStore(tmp / "tasks.json", fam)
            speaker = fam.get(c.speaker) or fam.admin
            for sd in c.seed:
                t = store.add(speaker, sd["title"], speaker, sd.get("due"))
                data = json.loads((tmp / "tasks.json").read_text(encoding="utf-8"))
                for x in data["tasks"]:
                    if x["id"] == t["id"]:
                        x["seeded"] = True
                (tmp / "tasks.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            notes = Notes(tmp / "notes", tz, MemoContext("e" * 16, datetime(*WHEN, tzinfo=tz)), accounts={},
                          store=store, family=fam, speaker=speaker,
                          join_info=lambda who: {"download": "https://github.com/noless-zz/jar/releases/latest",
                                                 "pair_link": f"jar://pair?v=1&t=EXAMPLE-{who.id}&u=http%3A%2F%2Fpc%3A8080"
                                                 if who else ""})
            t0 = time.monotonic()
            try:
                r = agent.run(c.memo, notes, datetime(*WHEN, tzinfo=tz), cfg.timezone, {})
                tasks = json.loads((tmp / "tasks.json").read_text(encoding="utf-8"))["tasks"] \
                    if (tmp / "tasks.json").exists() else []
                res = Result(r.actions, tasks, r.summary, fam)
                problem = c.check(res)
                summary = r.summary
            except Exception as e:  # noqa: BLE001
                res, problem, summary = Result([], [], "", fam), f"{type(e).__name__}: {e}", ""
            results.append({
                "case": c.name, "memo": c.memo, "ok": problem is None, "problem": problem,
                "seconds": round(time.monotonic() - t0, 1),
                "actions": [a["summary"] for a in res.actions],
                "messages": [m["message"] for m in res.new("message")],
                "reply": summary})
    by_case: dict[str, list[bool]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r["ok"])
    report = {"model": cfg.llm_model, "think": cfg.think, "at": time.strftime("%Y-%m-%d %H:%M"),
              "repeats": max(1, repeats),
              "per_case": {k: f"{sum(v)}/{len(v)}" for k, v in by_case.items()},
              "passed": sum(r["ok"] for r in results), "total": len(results),
              "seconds": round(time.monotonic() - t_all, 1), "results": results}
    out = out_dir or (cfg.data_dir / "eval")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# AI test: {report['passed']}/{report['total']} passed",
             f"{report['model']}, thinking {'on' if report['think'] else 'off'}, {report['seconds']} s, {report['at']}", "",
             "| case | passed |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["per_case"].items()] + [""]
    for r in results:
        lines.append(f"## {'✅' if r['ok'] else '❌'} {r['case']} ({r['seconds']} s)")
        lines.append(f"> {r['memo']}")
        lines += [f"- {a}" for a in r["actions"]] or ["- (nothing filed)"]
        lines += [f"\n```\n{m}\n```" for m in r["messages"]]
        if r["problem"]:
            lines.append(f"**Problem:** {r['problem']}")
        lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    import sys
    rep = run(repeats=int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1)
    for r in rep["results"]:
        print(("PASS " if r["ok"] else "FAIL ") + r["case"] + ("" if r["ok"] else f"  -> {r['problem']}"))
    print(f"\n{rep['passed']}/{rep['total']} passed in {rep['seconds']} s — details in data/eval/report.md")


if __name__ == "__main__":
    main()
