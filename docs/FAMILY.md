# Jar for the family

Each family member gets the **Jar app** on their Android phone, signed in as themselves.

- **Record** a memo, or tap **Task** to add one by hand. "Remind me to…" lands on your own list. "Remind Yoni to take the dog out" / "תזכיר ליוני להוציא את הכלב" lands on Yoni's phone.
- **Reminders** ring at the due time, with **Done**, **Snooze 1 hour** and **Tomorrow morning** buttons.
  Tasks without a time show up in the **08:00 summary** instead.
- **Tick** a task or **swipe** it sideways to mark it done. Whoever gave you the task sees it ticked in their **I asked** tab.
- **The kids** can ask anyone for anything. A child's task for someone else arrives as a **request**, and a parent taps **OK, add it** or **Decline**.
- **Parents** also see a **Family** tab with the kids' lists.
- **Shared (family) tasks:** tap several people in the task dialog (or say "Livne and Alona tidy the living room, each of
  you"). Choose **One of them is enough** (the first one to tick it finishes it and gets the coins) or **Each of them**
  (everyone ticks their own part — "My part is done" — and earns their own coins; the task is done when all have).
  A parent who isn't on the task can tick it for everyone. Everyone on a shared task sees it in **Mine**; parents
  see shared kids' tasks under **👥 Shared** in the Family tab. Server fields: `assignees`, `mode` (`any`/`all`),
  `done_parts`; `assignee` stays the first person so older apps keep working.

## Who sees what

| | Admin (owns the PC) | Other parent | Kids |
|---|---|---|---|
| Own tasks | ✓ | ✓ | ✓ |
| Tasks they gave someone | ✓ | ✓ | ✓ |
| The kids' tasks | ✓ | ✓ | only their own |
| The other parent's own to-dos | – | – | – |
| Dashboard (transcripts, audio) | ✓ (other parent's memos hidden) | – | – |
| Calendar events and email drafts (own accounts) | ✓ | – | – |
| Family events (invitations) and emails to family, via the family Jar account | ✓ | ✓ | ✓ |

With the family Jar account set up (docs/CONNECT.md, part C), anyone's memo can put a family event on the family
calendar with invitations ("Alona's show on Friday at 6, all of us") or email family members; it never writes to
anyone outside `[family]`. A child's own events also go to the family calendar.
The worker only uses the admin's Outlook/Google accounts for the admin's own memos. Memos from everyone else only make tasks,
plus private notes in `notes/Family/<name>/`.

## Setting up a phone

1. Nothing to install for away-from-home, once the admin has run **More → Let phones connect from anywhere**
   on the PC (once). That publishes only the phone part of Jar (`/v1`) at an `https://….ts.net` address
   through Tailscale Funnel. The dashboard stays private, and every request needs that person's code.
   Without it, a phone reaches Jar only on the home Wi-Fi, or with the Tailscale app signed in to the PC's account.
2. Install the app: on the phone open https://github.com/noless-zz/jar/releases/latest and tap the `.apk` under Assets. Android asks to allow installs from the browser once. After that the app updates itself (see [RELEASES.md](RELEASES.md)).
3. On the PC, open the dashboard and click **Pair a phone**, then pick the person's name. Each person has their own code.
4. In the app, tap **Pair with PC** and scan the code. The title then shows their name.
5. Allow **notifications** when asked. Otherwise reminders can't appear.

**From anywhere (no PC needed):** on the admin's phone, ⋮ → **Invite someone to Jar…**, pick the person, and WhatsApp
opens with their message: the download link and their own join link. Once the public address is on, they tap the link,
then **Open in Jar**, and they're paired. Saying "send Livne how to join Jar" in a memo makes the same message.

**Widgets:** long-press the home screen → Widgets → Jar, or in the app Settings → App → Widgets.
*Jar mic* is one button: tap to record, tap to stop; an orange badge counts memos still waiting to upload.
*Jar tasks* lists requests waiting for your OK, your open tasks and WhatsApp messages to send, plus what Jar did
with your last memo. Tap the box to tick a task done, ✓ to accept a request, the arrow to send a message.

**Settings** has pages: *Connection* (pair, test, the PC's addresses), *Memos* (upload queue, log), *App*
(version, a check that notifications, microphone, exact reminders and background running are allowed; tap a ⚠ to fix)
and, for the admin, *PC*: status, **Update the PC's code from GitHub**, restart, the AI test and the logs, from anywhere.

**Emails:** Jar only drafts emails. Each draft also makes a task "send the email: …", so tick it once you've sent it.

The admin's phone keeps using `[server] token`, so it stays paired. Updating the app keeps the pairing.

Phones paired before the public address existed learn it by themselves on their next sync at home (app 0.6.0 or newer),
or scan the pair code again. **Test connection** then says "Connected over the internet, encrypted" when away.

## Fixing things

- **A task is wrong.** In the app, tap the task, then **Edit…** to change the text, the person or the time.
  On the dashboard, click the task in the Family tasks panel. **+ task** adds a new one.
- **Jar misheard a memo.** In the app, open **⋮ → My memos**, tap the memo, correct the words, then tap **Save & file again**.
  On the dashboard, click **Edit** on the memo card. The tasks the first filing made are replaced, so nothing doubles.
  Notes, calendar events and email drafts from the first filing stay, so delete those yourself if needed.
- **By voice.** Record something like "move the dentist to Thursday at 10", "סיימתי לתלות כביסה" (I finished hanging the laundry)
  or "cancel the milk reminder". Jar finds the existing task and changes it instead of adding a new one.

## Recurring tasks 🔁 (משימות רב פעמיות)

Say "כל ראשון ורביעי ליבנה צריך להוציא את הזבל בשמונה", "תורנות לפרוק את המדיח כל יום, ליבנה ואלונה", or
"להשקות את העציצים כל יומיים". In the app: **+** → **Repeats?** → every day / on days… / every week / every month,
optionally ⏰ at a time; with several people pick **Taking turns** (or one of them / each of them as usual).

- Each time is an ordinary task on that day's list: tick it, coins as usual. The first one shows right away; the next
  ones appear on their day (`TaskStore.roll`, run by the worker and on every app sync).
- One not done by the time the next one comes is quietly dropped ("missed"): no coins taken, nothing shown.
- Turns go round even when someone skips theirs. After the PC was off, only the latest one is made.
- A child's recurring task for someone else waits for a parent's OK once, for the whole series.
- Rated once: the coins (and a parent's correction) carry over to every next time.
- Stop or pause: tap one → **🔁 Stop repeating**, or ⋮ → **🔁 Recurring tasks**; **Delete** asks "only this time /
  stop repeating". By voice: "תפסיק להזכיר לליבנה להוציא את הזבל".
- Rules: `daily`, `weekdays` (Sun–Thu), `weekly:sun,wed`, `weekly`, `every:3d`, `every:2w`, `monthly:15`
  (31 = the month's last day). API: `POST /v1/tasks` with `"repeat": {"rule", "time", "rotate"}`;
  `POST /v1/series/{id}/stop|pause|resume|edit`.

## Areas of responsibility 🧭 (תחומי אחריות)

Each area has an owner: 🍳 kitchen (Noam), 🧽 floors (Sveta), 👕 laundry (Alona), 🛒 food & shopping and general
order (Livne). Each comes with starter recurring tasks (`tools/seed_areas.py`). Manage them in the app: ⋮ →
**🧭 Areas of responsibility**. Parents can add or delete an area, change its owner, or edit the words that put a
task in it. A new owner also takes over the area's recurring tasks and their open occurrence.

- A new task is put in an area by its words. If no word matches, or words from two areas match ("לשטוף את
  הרצפה במטבח"), the AI picks the area when it rates the task.
- A chore said without naming anyone stays with whoever said it. When it's in someone else's area, the app shows
  "🧽 רצפות: התחום של סווטה" and offers **↪ Move it to Sveta** or **Keep it with me**.
- A move waits for the area's owner or a parent (not the one who asked). They get a notification with
  **Take it / Not now**; the task shows "⏳ waiting for Sveta". If they decline, it stays and the suggestion is gone.
- API: `POST /v1/areas`, `POST /v1/areas/{id}/edit|delete` (parents); task actions `handover`,
  `handover_accept`, `handover_decline`, `dismiss_suggest`. The snapshot includes `areas`.

## Jar ideas 💡

Ideas for Jar itself ("רעיון לג׳אר: מצב לילה", "תוסיף לאפליקציה אפשרות…", or the 💡 tab → **+**) go to the admin on
their own tab, not among the chores. The whole family sees every idea and what happened to it.

- The admin taps one: **✅ Accept** (whoever suggested it gets `idea_coins`, 20), **Decline** (with an optional word to
  them), and later **🚀 It's in Jar now** (`idea_shipped_bonus`, 10). Nobody earns coins for building an idea.
- At most `idea_credits_per_week` (3) accepted ideas pay per person per week; the admin's own ideas and (by default)
  the other parent's earn nothing. Settings under `[points]`.

## WhatsApp messages (prepared, you press Send)

Say "תשלח לסווטה שאני מגיע בשש" ("tell Sveta I'm coming at six") or "write Dana on WhatsApp that…". A 💬 item appears
on **your** list, and a notification says the message is ready. Tap **Send in WhatsApp**: WhatsApp opens with the text
filled in, and you press Send. Jar never sends anything by itself.

- To open the right chat directly, add the number: `phone = "+972…"` on the person's line in `[family]`, or under
  `[contacts]` for anyone else. Without a number, WhatsApp asks which chat. Jar never guesses numbers.
- Tap the item for **Edit the message…** or **Copy the text**.

## Sharing and updating the app

- **⋮ → Share the app** sends the download link (WhatsApp, SMS…).
- **⋮ → Check for updates** checks GitHub right away. When there's a newer version, a banner shows **Update**.
  When you're up to date, the same screen offers **Download page** and **Share the app**.
- The PC's Pair page also has a "Get the app" QR code for new phones.

## Changing the family

Edit `[family]` in `config.toml`, then click ▶ Jar:
- `name` is what the app shows.
- `aliases` are other names the voice model should recognise ("אמא", nicknames).
- `role` is `parent` or `child`.

Personal tokens live in `data/secrets/family_tokens.json`. Deleting someone's line there un-pairs their phone, and they get a new code next time.

## Dashboard on the admin's phone

Open the menu (⋮) and tap **Open dashboard**. That logs the phone's browser in for 30 days. Other family phones on Tailscale get "forbidden".

## Shopping lists 🛒

Everyone has a shopping list: the things *they* are going to buy. Anyone adds to anyone's list, and anyone ticks
what they bought (menu → 🛒 Shopping in the app, Home Assistant's family panel, or a memo).

- "אבא, תקנה לי אפוקסי" from Livne → on Noam's list, "asked by Livne".
- "נגמר החלב, צריך גם ביצים" (nobody named) → the list of whoever owns the 🛒 food & shopping area.
- "אני צריך לקנות סוללות" → the speaker's own list. "קניתי את האפוקסי" ticks it off.
- No coins for items; a shopping trip that is a task ("לעשות קניות בסופר") earns as any task.
- Bought items stay crossed out for two days, then disappear (the server keeps them two weeks).

