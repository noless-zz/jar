package com.noam.jar;

import android.content.Context;
import android.content.SharedPreferences;

import com.noam.jar.core.Task;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The phone's copy of the family task list, so the list, reminders and notification buttons
 * work without reaching the PC. Changes made offline wait in a small queue and are sent on the
 * next sync; the PC's answer then replaces the copy.
 */
public final class TaskCache {
    private static final String FILE = "jar_tasks";
    private final SharedPreferences sp;

    public TaskCache(Context c) {
        sp = c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- who am I

    public void setMe(JSONObject me) {
        sp.edit().putString("me", me.toString()).apply();
    }

    private JSONObject meJson() {
        try {
            return new JSONObject(sp.getString("me", "{}"));
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    /** My family id ("yoni"), or "" before the first sync. */
    public String myId() {
        JSONObject p = meJson().optJSONObject("person");
        return p == null ? "" : p.optString("id");
    }

    public String myName() {
        JSONObject p = meJson().optJSONObject("person");
        return p == null ? "" : p.optString("name");
    }

    public boolean iAmParent() {
        JSONObject p = meJson().optJSONObject("person");
        return p == null || !"child".equals(p.optString("role"));
    }

    public boolean iAmAdmin() {
        JSONObject p = meJson().optJSONObject("person");
        return p != null && p.optBoolean("admin");
    }

    /** id -> name, in the PC's order. */
    public Map<String, String> names() {
        Map<String, String> out = new LinkedHashMap<>();
        JSONArray fam = meJson().optJSONArray("family");
        if (fam != null) {
            for (int i = 0; i < fam.length(); i++) {
                JSONObject p = fam.optJSONObject(i);
                if (p != null) out.put(p.optString("id"), p.optString("name"));
            }
        }
        return out;
    }

    // ---------------------------------------------------------------- tasks

    public synchronized void setTasks(JSONObject snapshot) {
        sp.edit().putString("tasks", snapshot.toString())
                .putLong("synced_at", System.currentTimeMillis()).apply();
    }

    public synchronized List<Task> tasks() {
        try {
            List<Task> list = TaskApi.parseTasks(new JSONObject(sp.getString("tasks", "{}")));
            // Show offline changes right away, before the PC has confirmed them.
            JSONArray pending = pending();
            for (int i = 0; i < pending.length(); i++) {
                JSONObject a = pending.optJSONObject(i);
                if (a == null) continue;
                for (Task t : list) if (t.id.equals(a.optString("id"))) applyLocally(t, a);
            }
            java.util.Iterator<Task> it = list.iterator();
            while (it.hasNext()) if ("deleted".equals(it.next().status)) it.remove();
            return list;
        } catch (JSONException e) {
            return new java.util.ArrayList<>();
        }
    }

    public Task find(String id) {
        for (Task t : tasks()) if (t.id.equals(id)) return t;
        return null;
    }

    public long syncedAt() {
        return sp.getLong("synced_at", 0);
    }

    private static void applyLocally(Task t, JSONObject a) {
        switch (a.optString("action")) {
            case "done":
                t.status = "done";
                t.snoozedUntil = null;
                break;
            case "reopen":
                t.status = "open";
                break;
            case "snooze":
                t.snoozedUntil = a.isNull("until") ? null : a.optString("until", null);
                break;
            case "accept":
                t.status = "open";
                break;
            case "decline":
                t.status = "declined";
                break;
            case "delete":
                t.status = "deleted";
                break;
            default:
                break;
        }
    }

    // ---------------------------------------------------------------- offline queue

    public synchronized void queue(String taskId, String action, String until) {
        JSONArray arr = pending();
        try {
            JSONObject a = new JSONObject().put("id", taskId).put("action", action);
            if (until != null) a.put("until", until);
            arr.put(a);
        } catch (JSONException ignored) {
            return;
        }
        sp.edit().putString("pending", arr.toString()).apply();
    }

    public synchronized JSONArray pending() {
        try {
            return new JSONArray(sp.getString("pending", "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    /** Drop the first n queued actions (they reached the PC, or the PC refused them for good). */
    public synchronized void dropPending(int n) {
        JSONArray arr = pending(), rest = new JSONArray();
        for (int i = n; i < arr.length(); i++) rest.put(arr.opt(i));
        sp.edit().putString("pending", rest.toString()).apply();
    }

    // ---------------------------------------------------------------- notifications bookkeeping

    public Set<String> seen() {
        return new HashSet<>(sp.getStringSet("seen", new HashSet<>()));
    }

    public void setSeen(Set<String> ids) {
        sp.edit().putStringSet("seen", ids).apply();
    }

    public boolean firstSyncDone() {
        return sp.getBoolean("first_sync", false);
    }

    public void setFirstSyncDone() {
        sp.edit().putBoolean("first_sync", true).apply();
    }

    /** task id -> alarm time we scheduled, so a changed time replaces the old alarm. */
    public Map<String, Long> alarms() {
        Map<String, Long> out = new HashMap<>();
        try {
            JSONObject o = new JSONObject(sp.getString("alarms", "{}"));
            java.util.Iterator<String> it = o.keys();
            while (it.hasNext()) {
                String k = it.next();
                out.put(k, o.optLong(k));
            }
        } catch (JSONException ignored) {
            // start over
        }
        return out;
    }

    public void setAlarms(Map<String, Long> alarms) {
        sp.edit().putString("alarms", new JSONObject(alarms).toString()).apply();
    }

    /** Reminders already shown (task id + time), so a re-sync doesn't ring twice. */
    public boolean alreadyRang(String key) {
        return sp.getStringSet("rang", new HashSet<>()).contains(key);
    }

    public void markRang(String key) {
        Set<String> s = new HashSet<>(sp.getStringSet("rang", new HashSet<>()));
        if (s.size() > 300) s.clear();
        s.add(key);
        sp.edit().putStringSet("rang", s).apply();
    }

    public void clearAll() {
        sp.edit().clear().apply();
    }
}
