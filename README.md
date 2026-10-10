# Jar

A voice-memo pendant (ESP32-S3) plus a home server that files what you say: notes, tasks,
calendar events and email drafts, using a local Whisper + Ollama model. A family app for Android
shares tasks and reminders between the people in the house.

| Folder | What |
|---|---|
| `server/`, `worker/` | the home server (FastAPI) and the memo worker (Whisper → local LLM → tools) |
| `android/` | the phone app: record memos, family tasks with reminders, updates from GitHub Releases |
| `firmware/` | the XIAO ESP32-S3 Sense pendant |
| `docs/` | [calendars & email](docs/CONNECT.md) · [family](docs/FAMILY.md) · [releasing the app](docs/RELEASES.md) |

**Get the app:** [latest release](https://github.com/noless-zz/jar/releases/latest) → download the `.apk`.

Personal settings (`config.toml`, tokens, the signing key, memos, notes) stay on the PC and are never
committed. See `.gitignore`.

```
pendant / phone app ──HTTP──► server (FastAPI) ──► data\memos\<date>\<id>.wav + .json
                                                         │
                                  worker (python -m worker, runs in a loop)
                                    1. Whisper (GPU) → transcript
                                    2. local model (Ollama) → tool calls
                                    3. tools write to notes\  (Markdown + .ics)
```

## Run it (Windows)

```powershell
cd C:\Users\<you>\dev\jar
powershell -ExecutionPolicy Bypass -File .\setup.ps1     # once: venv, packages, token, Whisper download + GPU test
.\start-jar.ps1                                          # start server + worker in the background
.\start-jar.ps1 -Status                                  # running? memo counts, last log lines
.\start-jar.ps1 -Foreground                              # watch the worker live (Ctrl+C stops it)
.\start-jar.ps1 -Stop
.\install-autostart.ps1                                  # optional: start at Windows login
```

**It updates itself.** `start-jar.ps1` starts a small supervisor (`python -m server.supervise`). The supervisor runs the
server and the worker and restarts them when code or `config.toml` changes, or when one of them crashes.
Once this folder is linked to GitHub (VS Code: **More → Link this folder to GitHub**, needs `git`),
it also pulls new commits every 10 minutes. It only fast-forwards and never overwrites local edits.
The dashboard's **code** pill shows the version and the update status. Settings live under `[supervisor]` in `config.toml`.

**Phone app:** start Jar, open the dashboard → **Pair a phone**, and scan the QR code with
*Pair with PC* in Jar Companion. It saves the token and every address the PC has: home network
and Tailscale. Uploads use whichever answers, so the same setup works at home and away.
For away-from-home: install Tailscale on PC and phone with the same account; the pairing page
picks up the PC's Tailscale address automatically. `allow-firewall.ps1` (one UAC prompt) opens
TCP 8080 for the home network and for Tailscale.

### In VS Code

Run `.\install-vscode.ps1` once, open the `jar` folder and install the recommended extensions when asked
(Task Buttons, Python). The status bar then shows:

`▶ Jar` start/restart · `■` stop · `Status` · `Dashboard` · `More` → worker live, tail log,
send test memo, retry failed, check setup, tests, notes folder, firewall, autostart, firmware build/upload/monitor.

Everything is also under Ctrl+Shift+P → **Tasks: Run Task** → `Jar: …`, and F5 has
debug configurations for the worker, server and tests (stop the background Jar first).

**Dashboard** — `http://localhost:8080`, inside VS Code via Ctrl+Shift+P → *Simple Browser: Show*.
Every memo with its transcript, what was filed, errors, a play button, and *Redo all* /
*Re-file* to send it through the worker again. Only this PC can open it; the phone/pendant
can still upload.
Ollama must be running (its app starts with Windows).

### Why a loop, not a scheduled job

Loading Whisper takes seconds and ~1 GB of VRAM. A worker that stays running keeps
it loaded, so a memo is filed within seconds of arriving (spec target: under 60 s).
Ollama unloads the LLM after `keep_alive` (10 min) so the GPU is free otherwise.
`python -m worker --once` exists if you ever prefer a Task Scheduler job.

## What the worker does with a memo

| You say (Hebrew or English) | It writes in `notes\` |
|---|---|
| "Remind me to submit grades Thursday at 8" | `Tasks.md`: `- [ ] Submit grades 📅 2026-10-15 ⏰ 08:00` |
| "Dentist Wednesday at 9" | event in **Outlook** (personal) + `Calendar.md` |
| "Parent meeting Tuesday 18:30 in room 4" | event in the **school Google Calendar** + `Calendar.md` |
| "Draft an email to Dana about the trip" | a **draft** in Outlook / Gmail; you review it and press Send |
| "Lesson idea for 10th grade: …" | `Lesson ideas.md` |
| "Deep work: compare ESP32 batteries" | `Deep work\…md` (queued for the cloud model, phase 1 step 3) |
| anything else | `Inbox\<date> <title>.md` |

Calendars and drafts need a one-time sign-in: see [docs/CONNECT.md](docs/CONNECT.md). Until an
account is connected, events are saved as `.ics` files and drafts as notes, so nothing is lost.
Jar never sends email and never invites anyone.

Every memo is also logged in `Memos\<date>.md` (transcript + what was done), and its
`.json` gets `transcript`, `actions`, timings and `status` (`received → transcribed → done`).
If Ollama is down, memos wait as `transcribed` and finish when it's back.

`notes\` is an Obsidian-compatible vault. To use another folder (OneDrive, an existing
vault), change `[notes] dir` in `config.toml`.

## Settings — `config.toml`

| Key | Default | Notes |
|---|---|---|
| `transcribe.model` | `large-v3-turbo` | Hebrew-tuned alternative: `ivrit-ai/whisper-large-v3-turbo-ct2` |
| `transcribe.vocabulary` | names, places | Words Whisper should spell right |
| `llm.model` | `qwen3.5:9b` | Any Ollama model with tool calling; `qwen3.8:27b` is smarter but slower |
| `notes.dir` | `notes` | Where files are written |

## Files

| Path | What |
|---|---|
| `server\server.py` | Receives memos (`POST /v1/memos`), checks token + SHA-256 |
| `server\fake_device.py` | Upload a WAV (or a test tone) without hardware |
| `worker\` | `transcribe.py` Whisper · `agent.py` Ollama tool loop · `tools.py` endpoints · `memos.py` store |
| `tests\` | `python -m unittest discover -s tests -t .` |
| `firmware\` | PlatformIO project for the XIAO ESP32S3 Sense (step 1 bench capture) |
| `data\logs\worker.log` | What the worker did, memo by memo |

Wiring and the firmware exit test: see `firmware\README.md`.
