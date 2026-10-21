"""Repeat rules for recurring tasks (משימות רב פעמיות).

A rule is a short string, so the model, the app and the dashboard all speak the same language:
    daily              every day
    weekdays           Sunday to Thursday (the Israeli week)
    weekly:sun,wed     these weekdays (sun mon tue wed thu fri sat)
    weekly             every week, on the weekday of the first one
    every:3d           every 3 days            every:2w   every 2 weeks
    monthly:15         the 15th of every month (31 = the month's last day)
Times live next to the rule ("20:00" or "" for no time). Everything is in local dates: the family's
time zone, as with due dates.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]           # date.weekday() order
HE_DAY = {"sun": "ראשון", "mon": "שני", "tue": "שלישי", "wed": "רביעי", "thu": "חמישי", "fri": "שישי", "sat": "שבת"}
EN_DAY = {"sun": "Sunday", "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
          "fri": "Friday", "sat": "Saturday"}
WEEK_ORDER = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]       # how people list them here
ALIASES = {"sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
           "friday": "fri", "saturday": "sat", "ראשון": "sun", "שני": "mon", "שלישי": "tue", "רביעי": "wed",
           "חמישי": "thu", "שישי": "fri", "שבת": "sat", "tues": "tue", "thur": "thu", "thurs": "thu"}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    freq: str                      # daily | weekdays | weekly | every | monthly
    days: tuple[int, ...] = ()     # weekly: weekday numbers (0 = Monday)
    n: int = 1                     # every: the count
    unit: str = "d"                # every: d | w
    dom: int = 0                   # monthly: day of the month

    def text(self) -> str:
        """The canonical rule string."""
        if self.freq == "weekly":
            return "weekly:" + ",".join(d for d in WEEK_ORDER if DAYS.index(d) in self.days) if self.days else "weekly"
        if self.freq == "every":
            return f"every:{self.n}{self.unit}"
        if self.freq == "monthly":
            return f"monthly:{self.dom}"
        return self.freq


def parse(raw: str) -> Rule:
    s = re.sub(r"\s+", "", str(raw or "").strip().lower())
    if not s:
        raise RuleError("empty repeat rule")
    if s in ("daily", "day", "everyday", "1d", "every:1d"):
        return Rule("daily")
    if s in ("weekdays", "workdays"):
        return Rule("weekdays")
    if s in ("weekly", "week", "every:1w"):
        return Rule("weekly")
    if s in ("biweekly", "fortnightly"):
        return Rule("every", n=2, unit="w")
    if s in ("monthly", "month"):
        return Rule("monthly", dom=0)
    head, _, rest = s.partition(":")
    if head == "weekly" and rest:
        days = set()
        for part in rest.split(","):
            key = ALIASES.get(part, part[:3])
            if key not in DAYS:
                raise RuleError(f"unknown weekday '{part}'")
            days.add(DAYS.index(key))
        if len(days) == 7:
            return Rule("daily")
        return Rule("weekly", days=tuple(sorted(days)))
    if head == "every":
        m = re.fullmatch(r"(\d{1,3})([dw])", rest)
        if not m or int(m.group(1)) < 1:
            raise RuleError("every: use e.g. every:3d or every:2w")
        n, unit = int(m.group(1)), m.group(2)
        if unit == "d" and n == 1:
            return Rule("daily")
        if unit == "w" and n == 1:
            return Rule("weekly")
        return Rule("every", n=n, unit=unit)
    if head == "monthly":
        if not rest.isdigit() or not 1 <= int(rest) <= 31:
            raise RuleError("monthly: give the day of the month, 1-31")
        return Rule("monthly", dom=int(rest))
    raise RuleError(f"unknown repeat rule '{raw}' (daily, weekdays, weekly:sun,wed, every:3d, every:2w, monthly:15)")


def clean_time(raw: str | None) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    m = TIME_RE.match(s)
    if not m:
        raise RuleError("time must be HH:MM")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def settle(rule: Rule, start: date) -> Rule:
    """Fill in what a rule leaves to its first day: plain "weekly" = that weekday, plain "monthly" = that date."""
    if rule.freq == "weekly" and not rule.days:
        return Rule("weekly", days=(start.weekday(),))
    if rule.freq == "monthly" and not rule.dom:
        return Rule("monthly", dom=start.day)
    return rule


def _month_day(year: int, month: int, dom: int) -> date:
    return date(year, month, min(dom, calendar.monthrange(year, month)[1]))


def matches(rule: Rule, d: date) -> bool:
    if rule.freq == "daily":
        return True
    if rule.freq == "weekdays":
        return d.weekday() in (6, 0, 1, 2, 3)
    if rule.freq == "weekly":
        return d.weekday() in rule.days
    if rule.freq == "monthly":
        return d == _month_day(d.year, d.month, rule.dom)
    return True                                   # every: any day can start it


def first(rule: Rule, now: datetime, time: str = "") -> date:
    """The first day on or after now that the rule hits; a timed one already past today starts later."""
    d = now.date()
    if matches(rule, d) and not (time and time <= f"{now:%H:%M}"):
        return d
    if rule.freq == "every":
        return d + timedelta(days=1)                 # timed and already past today: from tomorrow
    return after(rule, d)


def after(rule: Rule, prev: date) -> date:
    """The next day strictly after `prev`."""
    if rule.freq == "every":
        return prev + timedelta(days=rule.n * (7 if rule.unit == "w" else 1))
    if rule.freq == "monthly":
        cand = _month_day(prev.year, prev.month, rule.dom)
        if cand > prev:
            return cand
        y, m = (prev.year + (prev.month == 12), prev.month % 12 + 1)
        return _month_day(y, m, rule.dom)
    d = prev + timedelta(days=1)
    for _ in range(8):
        if matches(rule, d):
            return d
        d += timedelta(days=1)
    raise RuleError("rule never matches")      # pragma: no cover — every rule matches within a week


def label(rule: Rule, time: str = "", lang: str = "he") -> str:
    """'כל ראשון ורביעי ב-20:00' / 'every Sunday and Wednesday at 20:00'."""
    he = lang == "he"
    if rule.freq == "daily":
        s = "כל יום" if he else "every day"
    elif rule.freq == "weekdays":
        s = "בימי חול (א׳–ה׳)" if he else "Sunday to Thursday"
    elif rule.freq == "weekly":
        names = [(HE_DAY if he else EN_DAY)[d] for d in WEEK_ORDER if DAYS.index(d) in rule.days]
        if he:
            s = "כל " + (" ו".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0])
        else:
            s = "every " + (" and ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0])
    elif rule.freq == "every":
        if rule.unit == "w":
            s = ("כל שבועיים" if rule.n == 2 else f"כל {rule.n} שבועות") if he else f"every {rule.n} weeks"
        else:
            s = ("כל יומיים" if rule.n == 2 else f"כל {rule.n} ימים") if he else f"every {rule.n} days"
    else:
        last = rule.dom >= 31
        s = ("בסוף כל חודש" if last else f"כל חודש ב-{rule.dom}") if he else \
            ("at the end of every month" if last else f"every month on the {rule.dom}")
    if time:
        s += f" ב-{time}" if he else f" at {time}"
    return s
