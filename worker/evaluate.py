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
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from . import config as config_mod
from . import effort
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
    series: list[dict] = field(default_factory=list)

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


def _one_series(r: Result, owners: list[str], rule: str, time: str = "", rotate: bool = False) -> str | None:
    ss = [x for x in r.series if x.get("status") == "active"]
    if len(ss) != 1:
        return f"expected 1 recurring task, got {len(ss)} (tools: {r.tools()}, tasks: {len(r.new())})"
    x = ss[0]
    if sorted(x["owners"]) != sorted(owners):
        return f"recurring task is for {x['owners']}, should be {owners}"
    if x["rule"] != rule:
        return f"repeat {x['rule']}, should be {rule}"
    if time and x.get("time") != time:
        return f"time {x.get('time')}, should be {time}"
    if bool(x.get("rotate")) != rotate:
        return "should take turns" if rotate else "should not take turns"
    if len([t for t in r.new() if not t.get("series_id")]) or len(r.new()) != 1:
        return f"expected just the first occurrence, got {len(r.new())} tasks"
    return None


def _one_idea(r: Result, admin: str, must: str) -> str | None:
    ideas = r.new("idea")
    if len(ideas) != 1 or r.new():
        return f"expected 1 Jar idea and no task, got {len(ideas)} ideas, {len(r.new())} tasks (tools: {r.tools()})"
    if ideas[0]["assignee"] != admin or must not in ideas[0]["title"] + ideas[0].get("notes", ""):
        return f"idea “{ideas[0]['title']}” should mention “{must}”"
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
             lambda r: _message(r, name(son), r"releases/latest", r"(jar://pair|/v1/join#)")),
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
        Case("an action without 'remind me' is a task",
             "לקנות סוללות לשלט של המזגן",
             lambda r: _one_task(r, admin, "סוללות")),
        Case("a child's to-do is a task they can see",
             "להכין לוח שנה לסבתא",
             lambda r: _one_task(r, son, "לוח שנה"),
             speaker=son),
        Case("a question about a child's task goes on that task",
             "תשאל את ליבנה אם הוא כבר סידר את החדר",
             lambda r: (None if (_seeded(r, "לסדר את החדר").get("waiting_on") == son and not r.new()
                                 and not r.new("message"))
                        else f"no question on the task (tools: {r.tools()}, waiting_on: "
                             f"{_seeded(r, 'לסדר את החדר').get('waiting_on')})"),
             seed=[{"title": "לסדר את החדר", "assignee": son}]),
        Case("a chore on fixed days repeats",
             "כל ראשון ורביעי ליבנה צריך להוציא את הזבל בשמונה בערב",
             lambda r: _one_series(r, [son], "weekly:sun,wed", "20:00")),
        Case("kids taking turns",
             "תורנות לפרוק את המדיח כל יום, ליבנה ואלונה",
             lambda r: _one_series(r, [son, daughter], "daily", rotate=True)),
        Case("every other day for me",
             "להשקות את העציצים כל יומיים",
             lambda r: _one_series(r, [admin], "every:2d")),
        Case("a one-time chore does not repeat",
             "תזכיר לליבנה מחר להוציא את הזבל",
             lambda r: _one_task(r, son, "זבל") or (f"made a recurring task: {r.series}" if r.series else None)),
        Case("stopping a recurring task",
             "תפסיק להזכיר לליבנה להוציא את הזבל כל יום, כבר לא צריך",
             lambda r: (None if r.series and r.series[0]["status"] == "ended" and not r.new()
                        else f"series still {r.series[0]['status'] if r.series else '?'} (tools: {r.tools()})"),
             seed=[{"title": "להוציא את הזבל", "assignee": son, "repeat": "daily"}]),
        Case("a child's idea for the app",
             "רעיון לג׳אר: שיהיה מצב לילה באפליקציה",
             lambda r: _one_idea(r, admin, "לילה"),
             speaker=son),
        Case("feature request worded as a task",
             "תוסיף לאפליקציה אפשרות לראות מי ניצח בשבוע שעבר",
             lambda r: _one_idea(r, admin, "ניצח"),
             speaker=daughter),
        Case("lesson idea",
             "רעיון לשיעור: להשתמש בבינגו כדי לתרגל פונקציות רציונליות בכיתה י'",
             lambda r: None if "save_lesson_idea" in r.tools() else f"not a lesson idea (tools: {r.tools()})"),
    ][:]


@dataclass
class RatingCase:
    """A task title and the effort the points game should give it (within ±tol), or "no coins"."""
    name: str
    title: str
    who: str                         # "adult" or "child" (a 9-year-old)
    expect: int | None = None        # None with no_coins=True
    tol: int = 1
    no_coins: bool = False
    kind: str = "task"
    notes: str = ""


def rating_cases() -> list[RatingCase]:
    """The calibration list from docs/POINTS.md. The prompt never mentions these chores, so a pass means
    the model can judge, not copy."""
    return [
        RatingCase("toilets", "לנקות את השירותים", "adult", 8),
        RatingCase("a whole room", "לנקות את החדר: לאסוף, לשאוב ולנגב", "adult", 7),
        RatingCase("hang laundry", "לתלות כביסה", "adult", 4),
        RatingCase("walk the dog", "לטייל עם הכלב", "adult", 3),
        RatingCase("dishwasher", "לפרוק את המדיח", "adult", 3),
        RatingCase("make the bed", "לסדר את המיטה", "adult", 1),
        RatingCase("help grandma with her calendar", "לעזור לסבתא עם לוח השנה בטלפון", "adult", 5),
        RatingCase("harder for a 9-year-old", "לתלות כביסה", "child", 5),
        RatingCase("a WhatsApp draft earns nothing", "WhatsApp → סבתא", "adult", no_coins=True, kind="message"),
        RatingCase("a 'send the email' reminder earns nothing", "לשלוח את המייל: חידוש ביטוח (חברת הביטוח)",
                   "adult", no_coins=True),
    ]


def check_rating(rc: RatingCase, rating: dict) -> str | None:
    if rc.no_coins:
        return None if rating.get("no_coins") else f"should earn no coins, got effort {rating.get('effort')}"
    if rating.get("no_coins"):
        return "got no coins, should earn some"
    e = int(rating.get("effort", 0))
    if abs(e - (rc.expect or 0)) > rc.tol:
        return f"effort {e}, expected {rc.expect} ± {rc.tol} ({rating.get('minutes')} min, {rating.get('reason')})"
    if rating.get("category") not in effort.CATEGORIES:
        return f"category {rating.get('category')!r} is not one of the list"
    return None


def run_ratings(cfg: config_mod.Config, real: Family) -> list[dict]:
    """The effort-rating cases against the real model, in the same shape as the memo results."""
    adult = real.admin
    child = next((p for p in real.people.values() if not p.is_parent), None)
    child = replace(child, age=9) if child else replace(adult, role="child", age=9)
    out = []
    for rc in rating_cases():
        who = child if rc.who == "child" else adult
        t0 = time.monotonic()
        try:
            rating = effort.rule_rating(rc.title, rc.kind, who) or effort.rate(
                cfg.ollama_url, cfg.llm_model, rc.title, rc.notes, who, [], None, cfg.num_ctx, cfg.keep_alive)
            problem = check_rating(rc, rating)
            detail = ("no coins: " + rating.get("reason", "")) if rating.get("no_coins") else (
                f"effort {rating.get('effort')} (expected {rc.expect}) · {rating.get('minutes')} min · "
                f"{rating.get('category')} · {rating.get('chore_key')} — {rating.get('reason')}")
        except Exception as e:  # noqa: BLE001
            problem, detail = f"{type(e).__name__}: {e}", ""
        out.append({"case": "rating: " + rc.name, "memo": f"{rc.title} ({'a 9-year-old' if rc.who == 'child' else 'an adult'})",
                    "ok": problem is None, "problem": problem, "seconds": round(time.monotonic() - t0, 1),
                    "actions": [detail] if detail else [], "messages": [], "reply": ""})
    return out


def run(cfg: config_mod.Config | None = None, out_dir: Path | None = None, repeats: int = 1) -> dict:
    cfg = cfg or config_mod.load()
    tz = ZoneInfo(cfg.timezone)
    agent = Agent(cfg.ollama_url, cfg.llm_model, cfg.temperature, cfg.keep_alive, cfg.max_rounds,
                  about=cfg.about, think=cfg.think, num_ctx=cfg.num_ctx)
    real = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
    results, t_all = [], time.monotonic()
    for c in [c for c in cases(real.admin.id, real) for _ in range(max(1, repeats))]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fam = Family.from_config(cfg.family or {}, "eval-token", tmp, cfg.contacts)
            store = TaskStore(tmp / "tasks.json", fam)
            speaker = fam.get(c.speaker) or fam.admin
            for sd in c.seed:
                who = fam.get(sd.get("assignee", "")) or speaker
                if sd.get("repeat"):
                    t = store.add_series(speaker, sd["title"], [who], sd["repeat"], now=datetime(*WHEN, tzinfo=tz))
                else:
                    t = store.add(speaker, sd["title"], who, sd.get("due"))
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
                saved = json.loads((tmp / "tasks.json").read_text(encoding="utf-8")) \
                    if (tmp / "tasks.json").exists() else {}
                res = Result(r.actions, saved.get("tasks", []), r.summary, fam, saved.get("series", []))
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
    # Effort ratings for the points game (repeats count like the memo cases: the model varies a little).
    for _ in range(max(1, repeats)):
        results += run_ratings(cfg, real)
    # Quick replies (the app's ✨ button): one sample, shown in the report for a human to judge.
    from . import replies
    sample = {"title": "לסדר את החדר", "assignee": "son", "created_by": "dad", "waiting_on": "son",
              "thread": [{"id": 1, "by": "dad", "text": "סידרת כבר את הארון? עד מתי זה יהיה מוכן?", "ask": True}]}
    t0 = time.monotonic()
    try:
        quick = replies.suggest(cfg.ollama_url, cfg.llm_model, sample, "son", {"son": "ליבנה", "dad": "אבא"})
    except replies.SuggestError as e:
        quick = [f"(failed: {e})"]
    quick_s = round(time.monotonic() - t0, 1)
    by_case: dict[str, list[bool]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r["ok"])
    report = {"model": cfg.llm_model, "think": cfg.think, "at": time.strftime("%Y-%m-%d %H:%M"),
              "repeats": max(1, repeats),
              "per_case": {k: f"{sum(v)}/{len(v)}" for k, v in by_case.items()},
              "passed": sum(r["ok"] for r in results), "total": len(results),
              "seconds": round(time.monotonic() - t_all, 1), "results": results,
              "quick_replies": {"seconds": quick_s, "for": sample["thread"][0]["text"], "replies": quick}}
    out = out_dir or (cfg.data_dir / "eval")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# AI test: {report['passed']}/{report['total']} passed",
             f"{report['model']}, thinking {'on' if report['think'] else 'off'}, {report['seconds']} s, {report['at']}", "",
             "| case | passed |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["per_case"].items()] + [""]
    lines += [f"## ✨ Quick replies ({quick_s} s) to: {sample['thread'][0]['text']}"] + [f"- {q}" for q in quick] + [""]
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
