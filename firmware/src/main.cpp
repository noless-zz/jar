// Jar — phase 1, step 1: bench capture
// Hold the button to record a WAV to microSD; release to save.
// When home Wi-Fi is up, queued memos upload to the server and are deleted
// only after the server confirms the same SHA-256.
//
// Board: Seeed XIAO ESP32S3 Sense (onboard PDM mic + microSD on the expansion board)

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <SD.h>
#include <SPI.h>
#include <ESP_I2S.h>
#include <ArduinoJson.h>
#include <mbedtls/sha256.h>
#include <time.h>
#include <vector>
#include "config.h"

// ---------- pins ----------
// The built-in user LED shares GPIO21 with the SD chip-select, so status uses an external LED.
static const int PIN_BUTTON   = D1;  // GPIO2  — button to GND, internal pull-up
static const int PIN_MOTOR    = D3;  // GPIO4  — transistor driving the vibration motor
static const int PIN_LED      = D4;  // GPIO5  — optional status LED (330 R to GND)
static const int PIN_SD_CS    = 21;  // fixed on the Sense board
static const int PIN_PDM_CLK  = 42;  // fixed on the Sense board
static const int PIN_PDM_DATA = 41;  // fixed on the Sense board

// ---------- audio / behaviour ----------
static const uint32_t SAMPLE_RATE        = 16000;
static const uint32_t MAX_MEMO_MS        = 5UL * 60UL * 1000UL;
static const uint32_t MIN_MEMO_MS        = 600;   // shorter presses are discarded
static const int      GAIN               = 2;     // digital gain; raise if recordings are quiet
static const uint32_t UPLOAD_INTERVAL_MS = 15000;
static const char*    MEMO_DIR           = "/memos";

I2SClass i2s;
volatile bool buttonPressed = false;  // set by ISR; also aborts an upload in progress
uint32_t bootId = 0;
bool ntpStarted = false;
uint32_t lastUploadAttempt = 0;

void IRAM_ATTR onButton() { buttonPressed = true; }

// ---------- feedback ----------
void buzz(int pulses, int onMs = 60, int offMs = 80) {
  for (int i = 0; i < pulses; i++) {
    digitalWrite(PIN_MOTOR, HIGH);
    delay(onMs);
    digitalWrite(PIN_MOTOR, LOW);
    if (i < pulses - 1) delay(offMs);
  }
}

// ---------- helpers ----------
String newMemoId() {
  char b[17];
  snprintf(b, sizeof b, "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
  return String(b);
}

bool clockValid() { return time(nullptr) > 1700000000; }

String isoUtc(time_t t) {
  struct tm tm;
  gmtime_r(&t, &tm);
  char b[25];
  strftime(b, sizeof b, "%Y-%m-%dT%H:%M:%SZ", &tm);
  return String(b);
}

String memoPath(const String& id, const char* ext) { return String(MEMO_DIR) + "/" + id + ext; }

void writeWavHeader(File& f, uint32_t dataBytes) {
  uint8_t h[44];
  auto w32 = [&](int o, uint32_t v) { h[o] = v; h[o + 1] = v >> 8; h[o + 2] = v >> 16; h[o + 3] = v >> 24; };
  auto w16 = [&](int o, uint16_t v) { h[o] = v; h[o + 1] = v >> 8; };
  memcpy(h, "RIFF", 4); w32(4, 36 + dataBytes); memcpy(h + 8, "WAVE", 4);
  memcpy(h + 12, "fmt ", 4); w32(16, 16); w16(20, 1); w16(22, 1);
  w32(24, SAMPLE_RATE); w32(28, SAMPLE_RATE * 2); w16(32, 2); w16(34, 16);
  memcpy(h + 36, "data", 4); w32(40, dataBytes);
  f.seek(0);
  f.write(h, 44);
}

bool writeSidecar(const String& id, uint32_t recMillis, time_t startEpoch, uint32_t durationMs) {
  JsonDocument doc;
  doc["id"] = id;
  doc["device_id"] = DEVICE_ID;
  doc["boot_id"] = bootId;
  doc["rec_millis"] = recMillis;
  doc["recorded_at"] = startEpoch ? isoUtc(startEpoch) : String("");
  doc["duration_ms"] = durationMs;
  doc["codec"] = "wav";
  doc["sample_rate"] = SAMPLE_RATE;
  File j = SD.open(memoPath(id, ".json"), FILE_WRITE);
  if (!j) return false;
  serializeJson(doc, j);
  j.close();
  return true;
}

// A memo interrupted by a reset is left as <id>.wav.part. Fix its header and keep it.
void recoverPartials() {
  std::vector<String> parts;
  File dir = SD.open(MEMO_DIR);
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    String name = f.name();
    if (name.endsWith(".wav.part")) parts.push_back(name);
    f.close();
  }
  dir.close();
  for (auto& name : parts) {
    String id = name.substring(0, name.length() - 9);
    String part = String(MEMO_DIR) + "/" + name;
    File f = SD.open(part, "r+");
    if (!f) continue;
    uint32_t size = f.size();
    if (size <= 44) { f.close(); SD.remove(part); continue; }
    uint32_t dataBytes = size - 44;
    writeWavHeader(f, dataBytes);
    f.close();
    if (!SD.exists(memoPath(id, ".json")))
      writeSidecar(id, 0, 0, dataBytes * 1000UL / (SAMPLE_RATE * 2));
    SD.rename(part, memoPath(id, ".wav"));
    Serial.printf("recovered partial memo %s (%lu bytes)\n", id.c_str(), (unsigned long)dataBytes);
  }
}

// ---------- recording ----------
void recordMemo() {
  String id = newMemoId();
  String part = memoPath(id, ".wav.part");
  File f = SD.open(part, FILE_WRITE);
  if (!f) { Serial.println("SD open failed"); buzz(3, 200, 150); return; }
  writeWavHeader(f, 0);

  static int16_t buf[512];  // 32 ms per chunk
  // Drop stale samples left in the DMA buffers since the last memo.
  for (int i = 0; i < 4; i++) i2s.readBytes((char*)buf, sizeof buf);

  uint32_t startMs = millis();
  time_t startEpoch = clockValid() ? time(nullptr) : 0;
  digitalWrite(PIN_LED, HIGH);
  buzz(1, 40);

  uint32_t dataBytes = 0;
  bool writeError = false;
  while (digitalRead(PIN_BUTTON) == LOW && millis() - startMs < MAX_MEMO_MS) {
    size_t n = i2s.readBytes((char*)buf, sizeof buf);
    if (n == 0) continue;
    for (size_t i = 0; i < n / 2; i++) {
      int32_t v = (int32_t)buf[i] * GAIN;
      buf[i] = v > 32767 ? 32767 : (v < -32768 ? -32768 : v);
    }
    if (f.write((uint8_t*)buf, n) != n) { writeError = true; break; }
    dataBytes += n;
  }
  uint32_t durationMs = millis() - startMs;
  digitalWrite(PIN_LED, LOW);
  writeWavHeader(f, dataBytes);
  f.close();

  if (writeError) Serial.println("SD write failed — keeping what was recorded");
  if (durationMs < MIN_MEMO_MS) {
    SD.remove(part);
    buzz(1, 250);  // one long buzz: too short, discarded
  } else if (writeSidecar(id, startMs, startEpoch, durationMs) && SD.rename(part, memoPath(id, ".wav"))) {
    Serial.printf("saved memo %s, %lu ms\n", id.c_str(), (unsigned long)durationMs);
    buzz(2);       // two short: saved
    lastUploadAttempt = 0;  // try to upload right away
  } else {
    buzz(3, 200, 150);  // three long: error (the .part is recovered on next boot)
  }
  while (digitalRead(PIN_BUTTON) == LOW) delay(10);  // held past the max length
  delay(30);
  buttonPressed = false;
}

// ---------- upload ----------
// Wraps the WAV file so an upload stops as soon as the button is pressed.
class AbortableFileStream : public Stream {
 public:
  explicit AbortableFileStream(File& f) : f_(f) {}
  int available() override { return buttonPressed ? 0 : f_.available(); }
  int read() override { return buttonPressed ? -1 : f_.read(); }
  size_t readBytes(char* b, size_t n) override { return buttonPressed ? 0 : f_.read((uint8_t*)b, n); }
  int peek() override { return f_.peek(); }
  size_t write(uint8_t) override { return 0; }
  void flush() override {}
 private:
  File& f_;
};

String sha256File(const String& path) {
  File f = SD.open(path);
  if (!f) return "";
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  static uint8_t buf[2048];
  int n;
  while ((n = f.read(buf, sizeof buf)) > 0) mbedtls_sha256_update(&ctx, buf, n);
  f.close();
  uint8_t out[32];
  mbedtls_sha256_finish(&ctx, out);
  mbedtls_sha256_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", out[i]);
  return String(hex);
}

bool uploadMemo(const String& id) {
  String wavPath = memoPath(id, ".wav"), jsonPath = memoPath(id, ".json");
  JsonDocument meta;
  File j = SD.open(jsonPath);
  if (!j || deserializeJson(meta, j)) { if (j) j.close(); Serial.printf("bad sidecar for %s\n", id.c_str()); return false; }
  j.close();

  String recordedAt = meta["recorded_at"] | "";
  // Recorded before the clock was set, but still in the same boot: back-date from millis.
  if (recordedAt.isEmpty() && clockValid() && meta["boot_id"].as<uint32_t>() == bootId) {
    uint32_t ageS = (millis() - meta["rec_millis"].as<uint32_t>()) / 1000;
    recordedAt = isoUtc(time(nullptr) - ageS);
  }

  String sha = sha256File(wavPath);
  if (sha.isEmpty()) return false;
  File f = SD.open(wavPath);
  if (!f) return false;
  size_t size = f.size();

  HTTPClient http;
  http.begin(String(SERVER_URL) + "/v1/memos");
  http.setTimeout(15000);
  http.addHeader("Authorization", String("Bearer ") + DEVICE_TOKEN);
  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("X-Memo-Id", id);
  http.addHeader("X-Device-Id", DEVICE_ID);
  http.addHeader("X-Recorded-At", recordedAt);
  http.addHeader("X-Duration-Ms", String(meta["duration_ms"].as<uint32_t>()));
  http.addHeader("X-Sha256", sha);
  AbortableFileStream body(f);
  int code = http.sendRequest("POST", &body, size);
  String resp = code > 0 ? http.getString() : "";
  http.end();
  f.close();

  if (code == 200 || code == 201) {
    JsonDocument r;
    if (!deserializeJson(r, resp) && sha.equals(r["sha256"] | "")) {
      SD.remove(wavPath);
      SD.remove(jsonPath);
      Serial.printf("uploaded %s (%u bytes)\n", id.c_str(), (unsigned)size);
      return true;
    }
  }
  Serial.printf("upload %s failed: %d %s\n", id.c_str(), code, resp.c_str());
  return false;
}

void uploadPending() {
  std::vector<String> ids;
  File dir = SD.open(MEMO_DIR);
  for (File f = dir.openNextFile(); f && ids.size() < 20; f = dir.openNextFile()) {
    String name = f.name();
    if (name.endsWith(".wav")) ids.push_back(name.substring(0, name.length() - 4));
    f.close();
  }
  dir.close();
  for (auto& id : ids) {
    if (buttonPressed || WiFi.status() != WL_CONNECTED) return;
    if (!uploadMemo(id)) return;  // stop on first failure; retry next interval
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_MOTOR, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_MOTOR, LOW);
  attachInterrupt(digitalPinToInterrupt(PIN_BUTTON), onButton, FALLING);
  bootId = esp_random();

  if (!SD.begin(PIN_SD_CS)) {
    Serial.println("SD init failed — check the card is FAT32 and seated");
    while (true) { buzz(3, 200, 150); delay(3000); }
  }
  if (!SD.exists(MEMO_DIR)) SD.mkdir(MEMO_DIR);
  recoverPartials();

  i2s.setPinsPdmRx(PIN_PDM_CLK, PIN_PDM_DATA);
  if (!i2s.begin(I2S_MODE_PDM_RX, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("I2S (PDM mic) init failed");
    while (true) { buzz(3, 200, 150); delay(3000); }
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);  // non-blocking; recording works without Wi-Fi

  Serial.printf("Jar ready, device %s\n", DEVICE_ID);
  buzz(1, 30);
}

void loop() {
  if (buttonPressed || digitalRead(PIN_BUTTON) == LOW) {
    buttonPressed = false;
    delay(20);  // debounce
    if (digitalRead(PIN_BUTTON) == LOW) recordMemo();
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!ntpStarted) { configTime(0, 0, "pool.ntp.org", "time.google.com"); ntpStarted = true; }
    if (lastUploadAttempt == 0 || millis() - lastUploadAttempt > UPLOAD_INTERVAL_MS) {
      lastUploadAttempt = millis();
      uploadPending();
    }
  }
  delay(5);
}
