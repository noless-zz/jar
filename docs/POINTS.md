# Points & leaderboard — design (agreed 2026-10-13)

Status: phase 1 shipped in app 1.1.0 (E only; phase 2 waits for the family's feedback). Decisions below are final unless family feedback changes them.

## Formula

```
coins = round(5 · E · R · S · T)        capped per person per day ([points] daily_cap, default 150)
```

| Factor | Meaning | Range | Rule |
|---|---|---|---|
| E effort | how hard the task is | 1–10 | AI rating at task creation; a parent can override (slider) |
| R repeat | same chore key, same person, last 7 days (n = earlier completions) | 0.25–1.0 | E 1–3: max(0.25, 0.7^n) · E 4–6: max(0.5, 0.85^n) · E 7–10: 1.0 |
| S streak | consecutive days with ≥1 parent-given task done | 1.0–1.5 | 1 + min(0.5, 0.05·days) |
| T timing | done vs due | 0.8–1.2 | on time 1.2 · no due 1.0 · ≤1 day late 1.0 · later 0.8 |
| habit | hard recurring chore done on schedule 3× in a row | ×1.25 | phase 3 (needs recurring chores) |

Phase 1 ships E only (R = S = T = 1.0); phase 2 turns on R, S, T, the cap and fair-play rules.

## AI effort rating
- When a task is created (voice, app, dashboard) the local model rates it once (~3 s, think off, JSON):
  `{effort 1-10, minutes, category, chore_key, reason}`. Categories: cleaning, kitchen, laundry, pets,
  outdoor, school, errand, job, lesson, other.
- Inputs: title + notes, who does it and their role/age group, past parent ratings for the same chore_key.
- Rated for who does it (age fairness): the same chore can be harder for the 9-year-old.
- Parent correction → stored per chore_key, used as the starting point next time.
- No coins: WhatsApp message tasks, "send the email" tasks, tasks a parent marks no_coins.
- Calibration samples: toilets 8 · full room clean 7 · hang laundry 4 · dog walk 3 · dishwasher 3 ·
  make bed 1 · helping grandma with the calendar 5.
- Add ~10 rating cases to `worker/evaluate.py` (effort within ±1 of expected) before shipping.

## Kinds of task that earn
- Chores and errands (as above).
- Grown-up jobs (parents): work day = fixed base from config (e.g. 30 coins), insurance, repairs,
  appointments — AI-rated on time and hassle.
- Lessons (kids, democratic school): coins for the "what I learned" note, not for attendance; the AI rates
  the note's effort 1–5; the note is shown to parents (family feed).

## Fair play (phase 2)
- Kids' self-created tasks: effort capped at 2 and 30 coins/day until a parent approves the rating.
- Reopen / delete / reassign a done task reverses its coins; done again pays the current rate.
- Same chore_key several times a day = repeats.
- Parent can revoke a completion within 48 h, with a note the child sees.
- Optional parent OK before paying for tasks worth 40+ coins (off by default).
- No negative coins; a miss just ends the streak.

## What people see
- Coins on each task row ("🪙 40", reduced value for easy repeats).
- Toast on done: "+58 🪙 — on time ×1.2, 6-day streak ×1.3".
- Leaderboard tab: this week (Sun–Sat) + all time, streak, best chore; tap a name → their ledger.
- Saturday 20:00 notification: winner + everyone's totals + "most improved" (vs own past weeks).
- Tasks widget footer: "🏆 <leader> leads with 312 · you 280". Dashboard: leaderboard + ledger with undo.
- Parents are on the same board.

## Data & API
| Where | What |
|---|---|
| task `points` | effort, minutes, category, chore_key, reason, rated_by (ai/parent), no_coins |
| `data/points.json` ledger | person, task_id, chore_key, at, coins, breakdown {E,R,S,T,habit}, reversed |
| `data/points.json` ratings | chore_key → parent effort |
| `GET /v1/points` | week + all-time totals, streaks, my ledger |
| `POST /v1/tasks/{id}/points` | parent: set effort / no_coins |
| `POST /v1/points/{line}/revoke` | parent: take back, with note (phase 2) |
| `POST /v1/lessons` | child: `{title, learned}` → finished lesson task, AI rates the note 1-5 (by length if the AI is away), 3 a day |
| `POST /v1/points/work-day` | parent: fixed `work_day_coins`, once per local day (409 when logged) |

Coins are paid when the PC records the task as done (offline ticks pay at sync, at the tick's time).
`[points]` config: daily_cap, work_day_coins, parent_ok_over, week_start = sunday, announce = "sat 20:00".

## Phase 1 as built
- `worker/effort.py` rates (rules first: WhatsApp drafts and "send the email" earn nothing, a parent's "work day" is the
  fixed base; else the model, JSON, thinking off). A parent's earlier slider value for the same `chore_key` replaces the
  model's effort. Unrated tasks (AI away) are stored with effort 3 and `rated_by: default`; the worker rates them later.
- `worker/points.py` is the ledger: `pay` is idempotent per task, reopen/delete/reassign `reverse`, a parent's change
  `repay`s. Weeks run Sunday–Saturday in the family's time zone. Ledger lines of private tasks show title `null`.
- Offline ticks send `at` (epoch s); the PC pays at that time (within 14 days, never in the future).
- App: 🪙 on task rows (grey = what it will pay), 🏆 Board tab, parent-only "What's it worth…" slider in the task menu,
  toast after done, Saturday notification from the phone's own alarm (cache remembers the announced week), widget footer.
- The AI test has 10 rating cases (`worker/evaluate.py: rating_cases`), tolerance ±1.

## Phases
1. AI rating + parent slider + ledger + coins on tasks + leaderboard tab + Saturday winner + jobs & lessons.
2. R, S, T factors, cap, fair-play rules, revoke.
3. Recurring chores + habit bonus.
4. Reward list (screen time, choosing dinner, pocket money) + "most improved" prize.
5. Chore market: waiting chores rise in price, crowded ones fall, weekly family budget (after weeks of data).

## Open: family feedback
A Hebrew explainer with research notes went to the other parent (motivation/overjustification, SDT,
token-economy fading, effort praise, sibling rivalry, streak anxiety, chores as contribution, lessons at a
democratic school, art-therapy ideas). Her answers may change: rewards, fading plan, how public the
leaderboard is (family goal vs individual), streak type, which chores stay outside the game.
