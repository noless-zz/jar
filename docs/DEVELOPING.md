# Developing Jar — state and workflow (as of app 1.1.0, 2026-10-13)

## Layout
| Path | What |
|---|---|
| `server/server.py` | FastAPI: `/v1/memos` upload, `/v1/me`, `/v1/tasks*` (+ notes, suggest), `/v1/invite`, `/v1/join`, `/v1/admin/*`, dashboard router |
| `server/dashboard.py`, `dashboard.html` | local web dashboard (PC + admin phone via login link) |
| `server/pairing.py` | LAN/Tailscale/Funnel address discovery, `jar://pair` links, QR |
| `server/supervise.py` | supervisor: runs server + worker, restarts on code/config change, pulls GitHub (git ff, or zip when no clone), phone commands, watchdog takeover |
| `worker/__main__.py` | memo loop: Whisper → agent → tools; heartbeat; runs AI test when `data/eval/run` exists |
| `worker/agent.py` | prompts (SYSTEM for admin, GUEST for family), tool loop, think/no-think retry, num_ctx |
| `worker/tools.py` | tools: add_task, update_task, find_tasks, note_on_task, draft_whatsapp, draft_join_instructions, draft_email (+ send task), create_event, save_note, lesson idea, search_notes |
| `worker/taskstore.py` | family task store (`data/tasks.json`): visibility, requests, actions, thread/waiting_on |
| `worker/effort.py`, `points.py`, `filelock.py` | points game: AI effort rating + rules, coin ledger (`data/points.json`), shared file lock — see POINTS.md |
| `worker/family.py`, `config.py`, `join.py`, `replies.py`, `evaluate.py` | family/tokens, config, invite text + join page, ✨ quick replies, AI test |
| `worker/home.py`, `custom_components/jar/` | Home Assistant: memos switch the house via Assist; the HA integration (to-do per person, coins, `jar.add_task`) — see HOME_ASSISTANT.md |
| `android/` | app (Java, minSdk 29): tasks, thread screen, settings pages, 2 widgets, updater; version in `android/VERSION` |
| `android/CHANGES.md` | one line per version `x.y.z \| עברית \| English` — shown in the app's update bar |
| `tests/` | Python unittest suite (`python -m unittest discover -s tests -t .`) |

## Release and deploy
- **Server/worker:** push to `main`. The PC is a git clone; its supervisor pulls within 10 min and restarts.
  Immediate: phone → Settings → PC → *Update the PC's code from GitHub* (or `POST /v1/admin/command {"cmd":"update"}`).
- **App:** bump `android/VERSION`, add a line to `android/CHANGES.md`, push. CI builds, signs and publishes
  the GitHub release; phones update in-app. Tag pushes are not used.
- **Before pushing:** `python -m unittest discover -s tests -t .` and, for the app,
  `./gradlew testDebugUnitTest assembleDebug lintDebug` (needs `local.properties` with sdk.dir).
- **AI changes:** run the AI test on the PC: Settings → PC → *Run AI test* (or write `data/eval/run` with
  repeats 1–3). Report in `data/eval/report.md`; last result 46/46 (13 memo + 10 rating cases, 2 repeats).

- **Status board:** `GET /v1/monitor` (header `X-Monitor-Key`, key from `config.toml` `[monitor] key`) gives a
  read-only health summary for a screen elsewhere in the house. Off without a key; no memo text, names or URLs.

## Speech-model bench (`worker/asr_bench.py`)
- Compares local Whisper models on the family's real memos. Trigger: write `data/eval/asr-run` (optional JSON,
  e.g. `{"limit": 80}`), or `python -m worker.asr_bench '{"limit": 80}'`. Report: `data/eval/asr/report.md` (private).
- References, best first: a transcript a family member corrected in My memos → **Gemini** (if set up) → the slow
  ivrit large-v3 model. The report also scores Gemini against the corrected memos, so you can see how far to trust it.
- **Gemini reference (optional, bench only):** put a Gemini API key in `data/secrets/gemini_key.txt`. Use a key from a
  Google Cloud project **with billing linked**: on the free tier Google may use the audio to improve its products.
  Each memo is sent once (inline, no file upload) and cached in `data/eval/asr/cloud/`; the whole set costs a few
  cents. `"cloud": false` in the trigger skips it; `"cloud_model": "…"` picks another model. Production never calls it.
- **Parakeet (`parakeet-he`):** Parakeet TDT 0.6B v3 Hebrew runs in its own environment `data/asr-envs/tf5`
  (`worker/asr_extra.py`, created on the bench's first run with CUDA torch, ~5 GB) through `worker/asr_runner.py`; the
  model (~2.5 GB) downloads from Hugging Face on first load. Logs: `data/asr-envs/tf5-install.log`,
  `data/eval/asr/parakeet-he.log`. Tried on 11-09 and dropped: Caspi-1.7B, qwen-asr-0.6b-he, LLM-combined transcripts,
  denoise/trim cleanup.
- **Shadow transcript** (`worker/shadow.py`): `[transcribe] shadow = "parakeet-he"` also transcribes every memo with
  Parakeet (CPU by default) after filing and saves it as `shadow` in the memo; filing still uses Whisper. The bench
  report's "Real use" line compares both on memos people fixed by hand. Log: `data/logs/shadow.log`.

## Hard-won lessons
- Prompt + tool schemas must stay well under `num_ctx` (12288): past it Ollama silently drops the memo.
  `tests/test_worker.py::ContextBudget` guards this. Never quote AI-test memos as prompt examples — the 9B
  model copies them.
- The PC reads Tailscale output as UTF-8; address discovery must never fail as a whole.
- Device id goes in an HTTP header: ASCII only (`ServerList.cleanDeviceId`).
- WorkManager APPEND waits behind retry back-off: "Upload now" uses REPLACE (`UploadWorker.now`).
- Supervisor heartbeat is written from a thread; commands carry `at` so a file that can't be deleted runs once.
- Funnel exposes only `/v1`; non-`/v1` requests with `Tailscale-Funnel-Request` get 404. Wrong tokens are
  throttled per real client IP (last X-Forwarded-For entry).

## Next: points phase 1
See [POINTS.md](POINTS.md). Suggested order: rating module + eval cases → store/ledger + API → app coins on
rows + leaderboard tab + slider → jobs & lessons → Saturday announcement → widget footer → release 1.1.0.
