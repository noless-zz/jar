package com.noam.jar;

import com.noam.jar.core.Memo;
import com.noam.jar.core.MemoQueue;
import com.noam.jar.core.ServerList;
import com.noam.jar.core.UploadResult;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Sends one memo to the Jar server with exactly the same request the pendant
 * firmware makes: raw WAV body, metadata in X- headers, bearer token.
 * Runs on a background thread only (WorkManager or the "Test" button's thread).
 */
public final class Uploader {

    public static final class Outcome {
        public final UploadResult result;
        public final String detail;
        /** False when no connection could be made at all: worth trying the PC's next address. */
        public final boolean reachable;

        Outcome(UploadResult result, String detail) {
            this(result, detail, true);
        }

        Outcome(UploadResult result, String detail, boolean reachable) {
            this.result = result;
            this.detail = detail;
            this.reachable = reachable;
        }
    }

    /** Short connect timeout per address, so the home address fails fast when you're away. */
    private static final int CONNECT_TIMEOUT_MS = 4000;

    private Uploader() {}

    /**
     * Tries the PC's addresses (home network, Tailscale…) in order, last-working first.
     * Moves on only when an address can't be reached; any answer from the server is final.
     */
    public static Outcome upload(Prefs prefs, Memo memo) {
        Outcome last = null;
        for (String url : ServerList.ordered(prefs.serverUrls(), prefs.lastGoodUrl())) {
            last = upload(url, prefs.token(), prefs.deviceId(), memo);
            if (last.reachable) {
                prefs.setLastGoodUrl(url);
                return last;
            }
        }
        return last != null ? last : new Outcome(UploadResult.RETRY, "no server address", false);
    }

    /** Plain-value version, so the request can be tested against a real server on the JVM. */
    public static Outcome upload(String serverUrl, String token, String deviceId, Memo memo) {
        HttpURLConnection http = null;
        try {
            String sha = MemoQueue.sha256(memo.wav);
            http = (HttpURLConnection) new URL(serverUrl + "/v1/memos").openConnection();
            http.setRequestMethod("POST");
            http.setConnectTimeout(CONNECT_TIMEOUT_MS);
            http.setReadTimeout(20000);
            http.setDoOutput(true);
            // Stream the file instead of buffering a 5-minute recording in memory.
            http.setFixedLengthStreamingMode(memo.wav.length());
            http.setRequestProperty("Authorization", "Bearer " + token);
            http.setRequestProperty("Content-Type", "audio/wav");
            http.setRequestProperty("X-Memo-Id", memo.id);
            http.setRequestProperty("X-Device-Id", deviceId);
            http.setRequestProperty("X-Recorded-At", memo.recordedAt);
            http.setRequestProperty("X-Duration-Ms", Long.toString(memo.durationMs));
            http.setRequestProperty("X-Sha256", sha);
            try {
                http.connect();
            } catch (IOException e) {
                return new Outcome(UploadResult.RETRY, "unreachable: " + e.getClass().getSimpleName(), false);
            }
            try (InputStream in = new FileInputStream(memo.wav); OutputStream out = http.getOutputStream()) {
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            int code = http.getResponseCode();
            String body = readBody(http, code);
            String serverSha = "";
            try {
                serverSha = new JSONObject(body).optString("sha256", "");
            } catch (JSONException ignored) {
                // Error pages aren't JSON; the HTTP code below is enough to decide.
            }
            return new Outcome(UploadResult.decide(code, sha, serverSha), "HTTP " + code);
        } catch (IOException | RuntimeException e) {
            return new Outcome(UploadResult.RETRY, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (http != null) http.disconnect();
        }
    }

    /** Returned by testConnection when the server is reachable but refuses the token. */
    public static final String BAD_TOKEN = "bad-token";

    /** What "Test connection" found: the address that answered (or null) and a problem (or null). */
    public static final class Check {
        public final String url;
        public final String problem;

        Check(String url, String problem) {
            this.url = url;
            this.problem = problem;
        }
    }

    /**
     * Checks every address until one answers, and that it accepts our token (GET /v1/auth).
     * problem == null: all good via url. BAD_TOKEN: reached url but the token is wrong.
     */
    public static Check testConnection(Prefs prefs) {
        String lastProblem = "no server address";
        for (String url : ServerList.ordered(prefs.serverUrls(), prefs.lastGoodUrl())) {
            String r = testConnection(url, prefs.token(), prefs.deviceId());
            if (r == null || BAD_TOKEN.equals(r) || r.startsWith("HTTP ")) {
                if (r == null) prefs.setLastGoodUrl(url);
                return new Check(url, r);
            }
            lastProblem = r;   // not reachable this way: try the next address
        }
        return new Check(null, lastProblem);
    }

    /** One address. null = OK, BAD_TOKEN, "HTTP nnn" (reached, other problem), else unreachable. */
    public static String testConnection(String serverUrl, String token, String deviceId) {
        HttpURLConnection http = null;
        try {
            http = (HttpURLConnection) new URL(serverUrl + "/v1/auth").openConnection();
            http.setConnectTimeout(CONNECT_TIMEOUT_MS);
            http.setReadTimeout(5000);
            http.setRequestProperty("Authorization", "Bearer " + token);
            http.setRequestProperty("X-Device-Id", deviceId);
            int code = http.getResponseCode();
            if (code == 200) return null;
            if (code == 401) return BAD_TOKEN;
            return "HTTP " + code;
        } catch (IOException | RuntimeException e) {
            String m = e.getMessage();
            return e.getClass().getSimpleName() + (m == null ? "" : ": " + m);
        } finally {
            if (http != null) http.disconnect();
        }
    }

    private static String readBody(HttpURLConnection http, int code) throws IOException {
        InputStream in = code >= 400 ? http.getErrorStream() : http.getInputStream();
        if (in == null) return "";
        try (InputStream s = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = s.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }
}
