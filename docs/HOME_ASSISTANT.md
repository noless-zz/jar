# Jar and Home Assistant

Jar's tasks on the family's Home Assistant (a wall panel, automations), and memos that switch things in the house.

## What you get

| In Home Assistant | What it does |
|---|---|
| `todo.jar_<id>` per family member | that person's **household** tasks. Ticking one ticks it in Jar *for that person*: their coins, their part of an "each of them" task. Unticking undoes it. A new item becomes a Jar task for that person (it pops up on their phone). Titles are changed in the Jar app. |
| `sensor.jar_<id>_coins_week` | the leaderboard: coins this week, with all-time, tasks this week, streak and rank as attributes |
| `sensor.jar_<id>_open_tasks` | how many tasks are open for that person; attribute `next` = the 3 most urgent (overdue first, then by due; area chores included) with title, due, overdue, coins, area |
| `todo.jar_<id>_shopping` per family member | what that person is going to buy (docs/FAMILY.md, shopping lists). Ticking = bought; a new item lands on their list |
| action `jar.add_task` | add a task from an automation: `title`, `people` (ids or names), optional `due`, `notes`, `each_of_them` |
| events `jar_task_new`, `jar_task_done` | for automations (announce a finished chore, flash a light…) |
| **voice control** (optional) | a memo like "תכבה את האור במטבח" switches it now, through Home Assistant's Assist |

What Home Assistant sees: a child's task, a shared task, a chore in an area of responsibility, or a task one family member
asked another to do. **Not** a parent's own to-dos, Jar ideas or WhatsApp drafts. Home Assistant earns no coins, is not on
the leaderboard and isn't in anyone's family list. Its token reaches only the task list (`server.HOME_PATHS`).

## Set it up

1. **Install the integration.** Home Assistant → HACS → ⋮ → *Custom repositories* → `https://github.com/noless-zz/jar`,
   type *Integration* → add. Find **Jar** in HACS → *Download* → restart Home Assistant.
2. **Get the link.** On the Jar PC open the dashboard → **Home Assistant** (from the phone: Jar app → menu →
   *Open dashboard* → Home Assistant). Copy the link. It is a password for Jar: paste it only into your own Home Assistant.
3. **Connect.** Home Assistant → Settings → Devices & services → *Add integration* → **Jar** → paste the link.
   Leave *Let Jar's memos control the house* on for voice control.

The link lists all of the PC's addresses; Home Assistant uses the first that answers (the public Funnel address first,
since Home Assistant may not be on the same network as the Jar PC) and keeps using it.
**New link** on the dashboard page replaces the token: the old one stops working, and Home Assistant asks for the new one.

## Voice control

With the option on, the integration makes a Home Assistant user **Jar** (not an administrator) with a token, and gives
Jar the token and Home Assistant's external address (`POST /v1/home/link`, saved in `data/secrets/home_assistant.json`).
The model then has a `home` tool: it rewrites the request in plain English and Home Assistant's built-in Assist does it
(`/api/conversation/process`, agent `conversation.home_assistant`). Home Assistant matches names and areas itself, so
nothing about the house is in Jar's prompt.

- **What a memo can switch** = what is exposed to Assist: Home Assistant → Settings → Voice assistants → *Expose*.
  Leave out anything a memo shouldn't touch. Everyone in the family can use it, the kids too.
- Names: Assist knows the English names and areas. Rooms with groups (Kitchen lights, Living room lights) work best.
- Every request and its answer is logged in the speaker's notes, `Home.md`.
- Turn it off: Settings → Devices & services → Jar → *Configure*. Removing the integration also removes the Jar user
  and tells Jar to forget Home Assistant.

## API (for the integration)

All with the Home Assistant token (`Authorization: Bearer …`):
`GET /v1/tasks`, `GET /v1/points`, `GET /v1/me`, `POST /v1/tasks` (needs `assignee`/`assignees`),
`POST /v1/tasks/{id}/done|reopen` with `{"as": "<person id>"}` (optional when the task has one person),
`GET /v1/shopping`, `POST /v1/shopping {"items", "buyer"}`, `POST /v1/shopping/{id}/bought|unbought`,
`GET /v1/home`, `POST /v1/home/link {"url", "token"}` (both empty = forget).
