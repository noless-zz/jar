package com.noam.jar;

import com.noam.jar.core.ServerList;
import com.noam.jar.core.Task;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * The family task API on the PC (/v1/me, /v1/tasks…), tried over every saved address
 * like uploads are. Background threads only.
 */
public final class TaskApi {
    private TaskApi() {}

    /** The server answered with an error (bad token, not allowed, no such task…). */
    public static final class HttpError extends IOException {
        public final int code;

        HttpError(int code, String body) {
            super("HTTP " + code + (body.isEmpty() ? "" : ": " + detail(body)));
            this.code = code;
        }

        private static String detail(String body) {
            try {
                return new JSONObject(body).optString("detail", body);
            } catch (JSONException e) {
                return body.length() > 120 ? body.substring(0, 120) : body;
            }
        }
    }

    public static JSONObject me(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/me", null);
    }

    public static JSONObject tasks(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/tasks", null);
    }

    public static JSONObject create(Prefs prefs, String title, String assignee, String due) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("assignee", assignee);
            if (due != null) body.put("due", due);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks", body);
    }

    /** Change title / person / time (due null = no time). */
    public static JSONObject edit(Prefs prefs, String taskId, String title, String assignee, String due)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("assignee", assignee).put("due", due == null ? JSONObject.NULL : due);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/edit", body);
    }

    /** Change a prepared WhatsApp message's text. */
    public static JSONObject editMessage(Prefs prefs, String taskId, String message) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("message", message);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/edit", body);
    }

    /** My recent memos: transcript and what Jar did with each. */
    /** Admin only: the personal "install Jar and join" message for one family member. */
    public static JSONObject invite(Prefs prefs, String personId) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("person", personId);
            body.put("language", java.util.Locale.getDefault().getLanguage().matches("iw|he") ? "he" : "en");
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/invite", body);
    }

    public static JSONObject memos(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/memos?limit=40", null);
    }

    /** The newest memo only: for the tasks widget's "last memo" line. */
    public static JSONObject lastMemo(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/memos?limit=1", null);
    }

    // ---- admin: look after the PC from the phone

    public static JSONObject adminStatus(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/admin/status", null);
    }

    /** "update" (pull from GitHub now), "restart" or "eval" (run the AI test). */
    public static JSONObject adminCommand(Prefs prefs, String cmd) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("cmd", cmd);
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/admin/command", body);
    }

    public static JSONObject adminLog(Prefs prefs, String name) throws IOException {
        return call(prefs, "GET", "/v1/admin/log?lines=200&name=" + name, null);
    }

    /** File a memo again; with transcript != null, that corrected text is filed. */
    public static JSONObject refile(Prefs prefs, String memoId, String transcript) throws IOException {
        JSONObject body = new JSONObject();
        try {
            if (transcript != null) body.put("transcript", transcript);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/memos/" + memoId + "/refile", body);
    }

    public static JSONObject act(Prefs prefs, String taskId, String action, String until) throws IOException {
        JSONObject body = new JSONObject();
        try {
            if (until != null) body.put("until", until);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/" + action, body);
    }

    /** One-time link that logs this phone's browser into the dashboard (admin only). */
    public static String dashboardLink(Prefs prefs) throws IOException {
        JSONObject r = call(prefs, "POST", "/v1/dashboard-login", new JSONObject());
        return prefs.serverUrl() + "/" + r.optString("path", "");
    }

    private static JSONObject call(Prefs prefs, String method, String path, JSONObject body) throws IOException {
        IOException last = new IOException("no server address");
        for (String url : ServerList.ordered(prefs.serverUrls(), prefs.lastGoodUrl())) {
            HttpURLConnection http = null;
            try {
                http = (HttpURLConnection) new URL(url + path).openConnection();
                http.setRequestMethod(method);
                http.setConnectTimeout(4000);
                http.setReadTimeout(10000);
                http.setRequestProperty("Authorization", "Bearer " + prefs.token());
                http.setRequestProperty("X-Device-Id", prefs.deviceId());
                byte[] out = null;
                if (body != null) {
                    out = body.toString().getBytes(StandardCharsets.UTF_8);
                    http.setDoOutput(true);
                    http.setFixedLengthStreamingMode(out.length);
                    http.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                }
                try {
                    http.connect();
                } catch (IOException e) {
                    last = e;            // this address can't be reached: try the next one
                    continue;
                }
                if (out != null) {
                    try (OutputStream os = http.getOutputStream()) {
                        os.write(out);
                    }
                }
                int code = http.getResponseCode();
                String text = read(code >= 400 ? http.getErrorStream() : http.getInputStream());
                prefs.setLastGoodUrl(url);
                if (code >= 400) throw new HttpError(code, text);
                try {
                    return text.isEmpty() ? new JSONObject() : new JSONObject(text);
                } catch (JSONException e) {
                    throw new IOException("bad reply from the PC", e);
                }
            } finally {
                if (http != null) http.disconnect();
            }
        }
        throw last;
    }

    private static String read(InputStream in) throws IOException {
        if (in == null) return "";
        try (InputStream s = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = s.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }

    // ---------------------------------------------------------------- JSON <-> Task

    public static List<Task> parseTasks(JSONObject snapshot) {
        List<Task> out = new ArrayList<>();
        JSONArray arr = snapshot == null ? null : snapshot.optJSONArray("tasks");
        if (arr == null) return out;
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null) out.add(parseTask(o));
        }
        return out;
    }

    public static Task parseTask(JSONObject o) {
        Task t = new Task();
        t.id = o.optString("id");
        t.title = o.optString("title");
        t.notes = o.optString("notes");
        t.assignee = o.optString("assignee");
        t.createdBy = o.optString("created_by");
        t.status = o.optString("status", "open");
        t.due = str(o, "due");
        t.snoozedUntil = str(o, "snoozed_until");
        t.doneAt = str(o, "done_at");
        t.doneBy = str(o, "done_by");
        t.updatedAt = o.optString("updated_at");
        t.kind = o.optString("kind", "task");
        t.message = o.optString("message", "");
        t.to = o.optString("to", "");
        t.phone = o.optString("phone", "");
        return t;
    }

    private static String str(JSONObject o, String key) {
        return o.isNull(key) ? null : o.optString(key, null);
    }
}
