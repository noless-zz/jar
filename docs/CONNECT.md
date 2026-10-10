# Connecting calendars and email

Jar can put events in your calendar and leave **email drafts** for you to review.
It never sends email and never invites other people. Until an account is connected,
events are saved as `.ics` files and drafts as notes under `Email drafts/`, so nothing is lost.

| Role | Account | Used for |
|---|---|---|
| personal | your Outlook.com / Hotmail / Live account | everything that isn't school |
| school | your school's Google Workspace account | classes, students, parents, staff, lessons, grades |

The model chooses the role from what you say. To force it, say "school" or "personal" in the memo.

Each account needs a one-time **app registration**. That is your own private "app ID" that lets Jar's code
ask you for permission. You do this once, in a browser, then run the matching **Connect** button.

---

## Part A: Outlook.com (personal)

1. Go to <https://entra.microsoft.com> and sign in with your **personal Microsoft account**.
   If it asks you to create an Azure subscription or enter a credit card, stop and tell Claude. There's another route.
2. **App registrations** → **New registration**
   - Name: `Jar`
   - Supported account types: **Personal Microsoft accounts only**
   - Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost`
   - **Register**
3. On the overview page, copy the **Application (client) ID**, a GUID like `1a2b3c4d-...`.
4. **Authentication** → *Advanced settings* → **Allow public client flows: Yes** → Save.
   Jar has no client secret. That's normal for a desktop app.
5. **API permissions** → Add → Microsoft Graph → *Delegated* → tick
   `Calendars.ReadWrite` and `Mail.ReadWrite` → Add. No admin consent is needed for a personal account.
6. In `config.toml`:
   ```toml
   [outlook]
   client_id = "paste-the-GUID-here"
   ```
7. In VS Code, open **More** → **Connect Outlook (personal)**. Your browser opens. Sign in with that account and accept.
   The token is saved in `data/secrets/outlook_token.json` and refreshes by itself.
   Removing app access at <https://account.live.com/consent/Manage> disconnects Jar.

Events appear in the Outlook desktop app and on outlook.live.com. Drafts appear in the **Drafts** folder.

## Part B: Google Workspace (school)

**Best option:** make the Cloud project *with the school account*, so the app can be **Internal**. With Internal, Google doesn't review the app and the sign-in never expires.

1. Go to <https://console.cloud.google.com> and sign in with your **school account** → create a project named `Jar`.
   - If the school blocks creating projects, use a personal Gmail account instead. See "If the school blocks it" below.
2. **APIs & Services → Library**: enable **Google Calendar API** and **Gmail API**.
3. **APIs & Services → OAuth consent screen** (also called "Google Auth Platform"):
   - User type: **Internal**. This is only offered when the project belongs to the school.
   - App name `Jar`, support email = your school address → Save.
   - Data access / scopes: add `.../auth/calendar.events` and `.../auth/gmail.compose`.
4. **Clients** (or **Credentials**) → **Create OAuth client** → type **Desktop app** → name `Jar` → Create → **Download JSON**.
5. Save the downloaded file as ``data\secrets\google_client.json` in the jar folder`. Create the `secrets` folder if it's missing.
6. In VS Code, open **More** → **Connect Google (school)**, then sign in with the school account and allow access.
   The token goes to `data/secrets/google_token.json`.

### If the school blocks it
- *"Access blocked: this app is blocked by your admin"* or *"admin_policy_enforced"*: the Workspace admin
  only allows approved apps. Ask IT to trust the app's **client ID** (Admin console → Security → API controls →
  App access control). Until then, school events still land as `.ics` files.
- If the project had to be made with a personal Gmail, the consent screen must be **External** in **Testing** mode.
  Add your school address as a **test user**. Google then expires the sign-in **every 7 days**, so you'd click
  Connect Google again weekly. That works, but asking the school is the better long-term fix.

---

## Check it

- **More → Accounts status** shows the connection for each role, for example `school  Google  connected as you@your-school.org`.
- The dashboard shows a green pill for each connected account, or amber "(files)" for one that isn't connected.
- Restart Jar (▶ Jar) after connecting, so the worker picks up the new tokens.
- Record a test memo: *"קבע לי תור לרופא שיניים ביום רביעי ב-9"* → an event in Outlook.
  *"Remind me to email the 10th-grade parents about the trip, draft it"* → a Gmail draft on the school account.

## Privacy

- Tokens live only in `data/secrets/`. Don't commit that folder or sync it anywhere.
- Jar asks for the narrowest permissions that still work: calendar events, plus composing drafts.
  It can't read your Gmail inbox. On Outlook, `Mail.ReadWrite` is the smallest scope that allows drafts, but Jar only creates drafts.
- To disconnect, delete the token file. You can also remove the app at
  <https://myaccount.google.com/permissions> or <https://account.live.com/consent/Manage>.
