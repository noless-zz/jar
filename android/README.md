# Jar (Android app)

Your phone stands in for the Jar pendant until the hardware arrives, and later
becomes the base of the BLE relay app. Same build setup as PhotoDream: Java,
classic Views, minSdk 29, target/compile SDK 36.

It speaks exactly the pendant's protocol: 16 kHz mono 16-bit WAV, the same
`POST /v1/memos` request (X- headers + SHA-256), and the same rule that a memo
is deleted from the phone only after the server returns a matching checksum.

## Use it

1. Start the server on the PC (see `jar/server`), e.g.
   `JAR_DEVICE_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8080`
2. Install the APK (or Run from Android Studio). Phone and PC on the same Wi-Fi.
3. In the app: Server address `http://<PC LAN IP>:8080`, the same token → **Test connection**.
4. Record:
   - **Hold** the big button and talk; release saves (push-to-talk, like the pendant).
   - Or **tap** to start and tap again to stop.
   - **Home-screen widget** "Jar record": tap to start, tap to stop. Shows how many memos wait.
5. Memos upload by themselves (WorkManager, retries with back-off). The log shows each step.

The phone buzzes like the pendant: 1 short = started, 2 short = saved,
1 long = too short (under 0.6 s, discarded), 3 long = error.

## Test the step-1 exit criteria without hardware

| Test | How |
|---|---|
| 20 memos, zero lost | Record 20; queue ends at 0; 20 `.wav` + `.json` on the server |
| No Wi-Fi | Turn on **Simulate no Wi-Fi**, record 5, turn it off: all 5 upload |
| Server down | Stop the server, record, start it again: uploads resume (retry back-off up to a few minutes, or tap **Upload now**) |
| Crash mid-memo | Start recording, force-stop the app in Settings, reopen: the cut-off memo is recovered |
| Wrong token | Change the token: the log says the server refused; fix it, tap **Upload now** |

## Code map (`app/src/main/java/com/noam/jar`)

| File | Job |
|---|---|
| `core/MemoQueue`, `core/Wav`, `core/UploadResult` | Plain Java, unit-tested: queue on disk, WAV header, delete/retry rule |
| `RecorderService` | Foreground microphone service: AudioRecord → `<id>.wav.part` → `<id>.wav` |
| `UploadWorker` + `Uploader` | Drains the queue with the pendant's HTTP request |
| `MainActivity` | Hold-to-record button, queue, settings, log |
| `JarWidget` + `RecordActivity` | Home-screen widget; the see-through activity lets Android allow the mic |
| `Prefs`, `Jar` | Settings, haptics, state broadcast |

```bash
./gradlew assembleDebug testDebugUnitTest lintDebug
```

## Limits (step 1)

- Plain HTTP on the LAN (`network_security_config.xml`), like the firmware. HTTPS later.
- Not signed with the PhotoDream key; a debug build is fine for your own phone.
- Not yet tested on a physical phone: check the widget start/stop and the
  notification's Stop button on your device.

## Builds

- **Dev** (`./gradlew assembleDebug`, Android Studio's Run): "Jar dev", package `com.noam.jar.dev`.
  It installs next to the family app.
- **Release**: built and signed by GitHub Actions when a `v*` tag is pushed. See [../docs/RELEASES.md](../docs/RELEASES.md).
  For a signed build on the PC, put `keystore.properties` (storeFile, storePassword, keyAlias, keyPassword) in this folder
  and run `./gradlew assembleRelease -PjarVersion=0.4.0`.
