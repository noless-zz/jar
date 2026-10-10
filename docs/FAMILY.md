# Jar for the family

Each family member gets the **Jar app** on their Android phone, signed in as themselves.

- **Record** a memo, or tap **Task** to add one by hand. "Remind me to…" lands on your own list. "Remind Yoni to take the dog out" / "תזכיר ליוני להוציא את הכלב" lands on Yoni's phone.
- **Reminders** ring at the due time, with **Done**, **Snooze 1 hour** and **Tomorrow morning** buttons.
  Tasks without a time show up in the **08:00 summary** instead.
- **Tick** a task or **swipe** it sideways to mark it done. Whoever gave you the task sees it ticked in their **I asked** tab.
- **The kids** can ask anyone for anything. A child's task for someone else arrives as a **request**, and a parent taps **OK, add it** or **Decline**.
- **Parents** also see a **Family** tab with the kids' lists.

## Who sees what

| | Admin (owns the PC) | Other parent | Kids |
|---|---|---|---|
| Own tasks | ✓ | ✓ | ✓ |
| Tasks they gave someone | ✓ | ✓ | ✓ |
| The kids' tasks | ✓ | ✓ | only their own |
| The other parent's own to-dos | – | – | – |
| Dashboard (transcripts, audio) | ✓ (other parent's memos hidden) | – | – |
| Calendar events and email drafts | ✓ | – | – |

The worker only uses the admin's Outlook/Google accounts for the admin's own memos. Memos from everyone else only make tasks,
plus private notes in `notes/Family/<name>/`.

## Setting up a phone

1. Install **Tailscale** from the Play Store and sign in with **the same account as the PC**.
   The phone can then reach Jar from anywhere. At home on Wi-Fi it works without Tailscale.
2. Install the app: on the phone open https://github.com/noless-zz/jar/releases/latest and tap the `.apk` under Assets. Android asks to allow installs from the browser once. After that the app updates itself (see [RELEASES.md](RELEASES.md)).
3. On the PC, open the dashboard and click **Pair a phone**, then pick the person's name. Each person has their own code.
4. In the app, tap **Pair with PC** and scan the code. The title then shows their name.
5. Allow **notifications** when asked. Otherwise reminders can't appear.

The admin's phone keeps using `[server] token`, so it stays paired. Updating the app keeps the pairing.

## Fixing things

- **A task is wrong.** In the app, tap the task, then **Edit…** to change the text, the person or the time.
  On the dashboard, click the task in the Family tasks panel. **+ task** adds a new one.
- **Jar misheard a memo.** In the app, open **⋮ → My memos**, tap the memo, correct the words, then tap **Save & file again**.
  On the dashboard, click **Edit** on the memo card. The tasks the first filing made are replaced, so nothing doubles.
  Notes, calendar events and email drafts from the first filing stay, so delete those yourself if needed.
- **By voice.** Record something like "move the dentist to Thursday at 10", "סיימתי לתלות כביסה" (I finished hanging the laundry)
  or "cancel the milk reminder". Jar finds the existing task and changes it instead of adding a new one.

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
