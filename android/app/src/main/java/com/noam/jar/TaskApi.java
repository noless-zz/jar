package com.noam.jar;

import com.noam.jar.core.Area;
import com.noam.jar.core.Award;
import com.noam.jar.core.Board;
import com.noam.jar.core.Series;
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

    public static JSONObject create(Prefs prefs, String title, List<String> owners, boolean each, String due)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("assignee", owners.get(0))
                    .put("assignees", new JSONArray(owners)).put("mode", each ? "all" : "any");
            if (due != null) body.put("due", due);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks", body);
    }

    /**
     * A recurring task: {@code rule} as the PC reads it ("daily", "weekly:sun,wed", "monthly:15"…), {@code time}
     * "HH:mm" or "". {@code rotate}: the people take turns. The PC returns the first occurrence.
     */
    public static JSONObject createRecurring(Prefs prefs, String title, List<String> owners, boolean each, String rule,
                                             String time, boolean rotate) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("assignee", owners.get(0))
                    .put("assignees", new JSONArray(owners)).put("mode", each ? "all" : "any")
                    .put("repeat", new JSONObject().put("rule", rule).put("time", time == null ? "" : time)
                            .put("rotate", rotate));
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks", body);
    }

    /** Make an existing task repeat; it stays as the first time. */
    public static JSONObject makeRecurring(Prefs prefs, String taskId, String rule, String time, boolean rotate)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("rule", rule).put("time", time == null ? "" : time).put("rotate", rotate);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/repeat", body);
    }

    /** A Jar idea, for the admin to accept or decline. */
    public static JSONObject createIdea(Prefs prefs, String title, String notes) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("kind", "idea").put("title", title).put("notes", notes == null ? "" : notes);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks", body);
    }

    /** The admin declines an idea, with a note for whoever suggested it (may be empty). */
    public static JSONObject declineIdea(Prefs prefs, String taskId, String note) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("note", note == null ? "" : note);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/decline", body);
    }

    /** A recurring task as a whole: "stop", "pause" or "resume". */
    public static JSONObject seriesAct(Prefs prefs, String seriesId, String action) throws IOException {
        return call(prefs, "POST", "/v1/series/" + seriesId + "/" + action, new JSONObject());
    }

    /** Change title / people (and any/each) / time (due null = no time). */
    public static JSONObject edit(Prefs prefs, String taskId, String title, List<String> owners, boolean each,
                                  String due) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("assignee", owners.get(0)).put("assignees", new JSONArray(owners))
                    .put("mode", each ? "all" : "any").put("due", due == null ? JSONObject.NULL : due);
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

    // ---- notes and questions on a task (online only: the reply shows the updated task)

    public static JSONObject addNote(Prefs prefs, String taskId, String text, boolean ask) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("text", text);
            body.put("ask", ask);
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/notes", body);
    }

    /** Change your own note; empty text removes it. */
    public static JSONObject editNote(Prefs prefs, String taskId, int noteId, String text) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("text", text);
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "PATCH", "/v1/tasks/" + taskId + "/notes/" + noteId, body);
    }

    /** A few short replies the PC's AI suggests (nothing is sent). */
    public static List<String> suggest(Prefs prefs, String taskId) throws IOException {
        JSONArray arr = call(prefs, "POST", "/v1/tasks/" + taskId + "/suggest", new JSONObject()).optJSONArray("replies");
        List<String> out = new java.util.ArrayList<>();
        for (int i = 0; arr != null && i < arr.length(); i++) out.add(arr.optString(i));
        return out;
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
    /** Take back one thing a memo made (a task, a note, an event, a draft): its index in the memo's "items". */
    public static JSONObject deleteMemoItem(Prefs prefs, String memoId, int index) throws IOException {
        return call(prefs, "POST", "/v1/memos/" + memoId + "/items/" + index + "/delete", new JSONObject());
    }

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
        return act(prefs, taskId, action, until, 0);
    }

    /** {@code atMillis} > 0: when the change was made on the phone (an offline tick is paid at that time). */
    public static JSONObject act(Prefs prefs, String taskId, String action, String until, long atMillis)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            if (until != null) body.put("until", until);
            if (atMillis > 0) body.put("at", atMillis / 1000.0);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/" + action, body);
    }

    // ---- points

    /** The leaderboard: this week, all time, ledgers, lesson notes, the week's result. */
    public static JSONObject points(Prefs prefs) throws IOException {
        return call(prefs, "GET", "/v1/points", null);
    }

    /** A parent sets what a task is worth: effort 1-10 (0 = leave) and/or no coins (null = leave). */
    public static JSONObject setPoints(Prefs prefs, String taskId, int effort, Boolean noCoins) throws IOException {
        JSONObject body = new JSONObject();
        try {
            if (effort > 0) body.put("effort", effort);
            if (noCoins != null) body.put("no_coins", noCoins);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/tasks/" + taskId + "/points", body);
    }

    /** A child's lesson note. The PC's AI rates it first, so this can take a while. */
    public static JSONObject lesson(Prefs prefs, String title, String learned) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("title", title).put("learned", learned);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/lessons", body, 45000);
    }

    /** A parent logs today's work day. */
    public static JSONObject workDay(Prefs prefs) throws IOException {
        return call(prefs, "POST", "/v1/points/work-day", new JSONObject());
    }

    // ---------------------------------------------------------------- shopping lists (core/Shopping)

    /** Everyone's shopping lists, and who buys when nobody is named ("default_buyer"). */
    public static java.util.List<com.noam.jar.core.Shopping.Item> shopping(Prefs prefs, String[] defaultBuyer)
            throws IOException {
        JSONObject r = call(prefs, "GET", "/v1/shopping", null);
        if (defaultBuyer != null && defaultBuyer.length > 0) defaultBuyer[0] = r.optString("default_buyer", "");
        java.util.List<com.noam.jar.core.Shopping.Item> out = new java.util.ArrayList<>();
        JSONArray a = r.optJSONArray("items");
        if (a == null) return out;
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.optJSONObject(i);
            if (o == null) continue;
            com.noam.jar.core.Shopping.Item it = new com.noam.jar.core.Shopping.Item();
            it.id = o.optString("id");
            it.title = o.optString("title");
            it.notes = o.optString("notes");
            it.buyer = o.optString("buyer");
            it.requestedBy = o.optString("requested_by");
            it.bought = "bought".equals(o.optString("status"));
            it.createdAt = o.optString("created_at");
            out.add(it);
        }
        return out;
    }

    /** Things to buy on someone's list (empty buyer = whoever does the family shopping). */
    public static void shoppingAdd(Prefs prefs, java.util.List<String> titles, String buyer, String notes)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("items", new JSONArray(titles));
            if (buyer != null && !buyer.isEmpty()) body.put("buyer", buyer);
            if (notes != null && !notes.isEmpty()) body.put("notes", notes);
        } catch (JSONException e) {
            throw new IOException(e);
        }
        call(prefs, "POST", "/v1/shopping", body);
    }

    /** bought | unbought | delete. */
    public static void shoppingAct(Prefs prefs, String id, String action) throws IOException {
        call(prefs, "POST", "/v1/shopping/" + id + "/" + action, new JSONObject());
    }

    /** One-time link that logs this phone's browser into the dashboard (admin only). */
    public static String dashboardLink(Prefs prefs) throws IOException {
        JSONObject r = call(prefs, "POST", "/v1/dashboard-login", new JSONObject());
        return prefs.serverUrl() + "/" + r.optString("path", "");
    }

    private static JSONObject call(Prefs prefs, String method, String path, JSONObject body) throws IOException {
        return call(prefs, method, path, body, 10000);
    }

    private static JSONObject call(Prefs prefs, String method, String path, JSONObject body, int readTimeoutMs)
            throws IOException {
        IOException last = new IOException("no server address");
        for (String url : ServerList.ordered(prefs.serverUrls(), prefs.lastGoodUrl())) {
            HttpURLConnection http = null;
            try {
                http = (HttpURLConnection) new URL(url + path).openConnection();
                http.setRequestMethod(method);
                http.setConnectTimeout(4000);
                http.setReadTimeout(readTimeoutMs);
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

    /** The areas of responsibility in a snapshot. */
    public static List<Area> parseAreas(JSONObject snapshot) {
        List<Area> out = new ArrayList<>();
        JSONArray arr = snapshot == null ? null : snapshot.optJSONArray("areas");
        for (int i = 0; arr != null && i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            Area a = new Area();
            a.id = o.optString("id");
            a.name = o.optString("name");
            a.emoji = o.optString("emoji", "");
            a.owner = o.optString("owner");
            a.description = o.optString("description", "");
            JSONArray kw = o.optJSONArray("keywords");
            for (int j = 0; kw != null && j < kw.length(); j++) a.keywords.add(kw.optString(j));
            out.add(a);
        }
        return out;
    }

    /** A parent adds an area (keywords: the words that put a task in it). */
    public static JSONObject addArea(Prefs prefs, String name, String emoji, String owner, List<String> keywords)
            throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("name", name).put("emoji", emoji).put("owner", owner).put("keywords", new JSONArray(keywords));
        } catch (JSONException e) {
            throw new IOException(e);
        }
        return call(prefs, "POST", "/v1/areas", body);
    }

    /** Change an area: any of "name", "emoji", "owner", "keywords" (a JSONArray). */
    public static JSONObject editArea(Prefs prefs, String areaId, JSONObject fields) throws IOException {
        return call(prefs, "POST", "/v1/areas/" + areaId + "/edit", fields);
    }

    /** A parent's family settings: {"keep_done_days": 0 (forever) | 30 | 90 | 180 | 365}. */
    public static JSONObject setSettings(Prefs prefs, JSONObject fields) throws IOException {
        return call(prefs, "POST", "/v1/settings", fields);
    }

    public static JSONObject deleteArea(Prefs prefs, String areaId) throws IOException {
        return call(prefs, "POST", "/v1/areas/" + areaId + "/delete", new JSONObject());
    }

    /** The recurring tasks in a snapshot ("series"), as this person may see them. */
    public static List<Series> parseSeries(JSONObject snapshot) {
        List<Series> out = new ArrayList<>();
        JSONArray arr = snapshot == null ? null : snapshot.optJSONArray("series");
        for (int i = 0; arr != null && i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            Series s = new Series();
            s.id = o.optString("id");
            s.title = o.optString("title");
            s.createdBy = o.optString("created_by");
            JSONArray owners = o.optJSONArray("owners");
            for (int j = 0; owners != null && j < owners.length(); j++) s.owners.add(owners.optString(j));
            s.rule = o.optString("rule");
            s.time = o.isNull("time") ? "" : o.optString("time", "");
            s.label = o.optString("label");
            s.rotate = o.optBoolean("rotate");
            s.status = o.optString("status", "active");
            s.nextDue = o.isNull("next_due") ? "" : o.optString("next_due", "");
            s.nextTurn = o.optString("next_turn", "");
            out.add(s);
        }
        return out;
    }

    public static Task parseTask(JSONObject o) {
        Task t = new Task();
        t.id = o.optString("id");
        t.title = o.optString("title");
        t.notes = o.optString("notes");
        t.assignee = o.optString("assignee");
        JSONArray owners = o.optJSONArray("assignees");
        for (int i = 0; owners != null && i < owners.length(); i++) {
            String id = owners.optString(i, "");
            if (!id.isEmpty() && !t.assignees.contains(id)) t.assignees.add(id);
        }
        t.mode = "all".equals(o.optString("mode")) ? "all" : "any";
        JSONObject parts = o.optJSONObject("done_parts");
        if (parts != null) {
            java.util.Iterator<String> keys = parts.keys();
            while (keys.hasNext()) t.doneParts.add(keys.next());
        }
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
        t.waitingOn = o.isNull("waiting_on") ? "" : o.optString("waiting_on", "");
        t.seriesId = o.isNull("series_id") ? "" : o.optString("series_id", "");
        t.repeat = o.isNull("repeat") ? "" : o.optString("repeat", "");
        t.duplicateOf = o.isNull("duplicate_of") ? "" : o.optString("duplicate_of", "");
        t.area = o.isNull("area") ? "" : o.optString("area", "");
        t.areaSuggest = o.isNull("area_suggest") ? "" : o.optString("area_suggest", "");
        JSONObject ho = o.optJSONObject("handover");
        if (ho != null) {
            t.handoverTo = ho.optString("to", "");
            t.handoverBy = ho.optString("by", "");
        }
        t.coins = o.optInt("coins");
        t.paid = o.optBoolean("paid");
        JSONObject pts = o.optJSONObject("points");
        if (pts != null) {
            t.effort = pts.optInt("effort");
            t.noCoins = pts.optBoolean("no_coins");
            t.ratedBy = pts.optString("rated_by", "");
        }
        JSONArray th = o.optJSONArray("thread");
        for (int i = 0; th != null && i < th.length(); i++) {
            JSONObject n = th.optJSONObject(i);
            if (n == null) continue;
            Task.Note note = new Task.Note();
            note.id = n.optInt("id");
            note.by = n.optString("by");
            note.text = n.optString("text");
            note.at = n.optString("at");
            note.ask = n.optBoolean("ask");
            note.edited = n.has("edited") && !n.isNull("edited");
            t.thread.add(note);
        }
        return t;
    }

    /** What "done" paid: the "award" in the PC's answer, or null when the task earns nothing. */
    public static Award parseAward(JSONObject task) {
        JSONObject a = task == null ? null : task.optJSONObject("award");
        if (a == null) return null;
        Award out = new Award();
        out.fresh = a.optBoolean("new");
        out.coins = a.optInt("coins");
        out.weekTotal = a.optInt("week_total");
        JSONObject b = a.optJSONObject("breakdown");
        if (b != null) {
            out.effort = b.optDouble("E", 1);
            out.repeat = b.optDouble("R", 1);
            out.streak = b.optDouble("S", 1);
            out.timing = b.optDouble("T", 1);
            out.habit = b.optDouble("habit", 1);
            out.fixed = b.optInt("fixed");
        }
        return out;
    }

    public static Board parseBoard(JSONObject o) {
        Board b = new Board();
        if (o == null) return b;
        JSONObject week = o.optJSONObject("week");
        if (week != null) {
            b.weekStart = week.optString("start");
            b.weekEnd = week.optString("end");
        }
        b.me = o.optString("me");
        JSONObject cfg = o.optJSONObject("config");
        if (cfg != null) {
            b.workDayCoins = cfg.optInt("work_day_coins", 30);
            b.announce = cfg.optString("announce", "sat 20:00");
        }
        JSONArray people = o.optJSONArray("people");
        for (int i = 0; people != null && i < people.length(); i++) {
            JSONObject p = people.optJSONObject(i);
            if (p == null) continue;
            Board.Person x = new Board.Person();
            x.id = p.optString("id");
            x.name = p.optString("name");
            x.role = p.optString("role");
            x.week = p.optInt("week");
            x.allTime = p.optInt("all_time");
            x.tasksWeek = p.optInt("tasks_week");
            x.streak = p.optInt("streak");
            JSONObject best = p.optJSONObject("best");
            if (best != null) {
                x.bestCoins = best.optInt("coins");
                x.bestCategory = best.optString("category");
                x.bestTitle = str(best, "title");
            }
            b.people.add(x);
        }
        JSONObject ledgers = o.optJSONObject("ledgers");
        for (int i = 0; ledgers != null && i < b.people.size(); i++) {
            String id = b.people.get(i).id;
            JSONArray lines = ledgers.optJSONArray(id);
            List<Board.Line> list = new ArrayList<>();
            for (int j = 0; lines != null && j < lines.length(); j++) {
                JSONObject l = lines.optJSONObject(j);
                if (l == null) continue;
                Board.Line x = new Board.Line();
                x.id = l.optInt("id");
                x.title = str(l, "title");
                x.kind = l.optString("kind", "task");
                x.category = l.optString("category");
                x.at = l.optString("at");
                x.coins = l.optInt("coins");
                x.reversed = l.optBoolean("reversed");
                x.reversedWhy = l.optString("reversed_why", "");
                x.note = str(l, "note");
                x.ratedBy = l.optString("rated_by", "");
                list.add(x);
            }
            b.ledgers.put(id, list);
        }
        JSONArray lessons = o.optJSONArray("lessons");
        for (int i = 0; lessons != null && i < lessons.length(); i++) {
            JSONObject l = lessons.optJSONObject(i);
            if (l == null) continue;
            Board.Lesson x = new Board.Lesson();
            x.person = l.optString("person");
            x.name = l.optString("name");
            x.title = l.optString("title");
            x.note = l.optString("note");
            x.coins = l.optInt("coins");
            x.at = l.optString("at");
            b.lessons.add(x);
        }
        JSONObject sum = o.optJSONObject("summary");
        if (sum != null) {
            b.summary.weekStart = sum.optString("week_start");
            b.summary.top = sum.optInt("top");
            JSONArray w = sum.optJSONArray("winners");
            for (int i = 0; w != null && i < w.length(); i++) b.summary.winners.add(w.optString(i));
            JSONArray totals = sum.optJSONArray("totals");
            for (int i = 0; totals != null && i < totals.length(); i++) {
                JSONObject t = totals.optJSONObject(i);
                if (t == null) continue;
                Board.Person x = new Board.Person();
                x.id = t.optString("id");
                x.name = t.optString("name");
                x.week = t.optInt("coins");
                b.summary.totals.add(x);
            }
            JSONObject imp = sum.optJSONObject("most_improved");
            if (imp != null) {
                b.summary.improvedId = imp.optString("id");
                b.summary.improvedName = imp.optString("name");
                b.summary.improvedPct = imp.optInt("pct");
            }
        }
        return b;
    }

    private static String str(JSONObject o, String key) {
        return o.isNull(key) ? null : o.optString(key, null);
    }
}
