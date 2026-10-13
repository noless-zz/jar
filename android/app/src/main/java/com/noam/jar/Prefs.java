package com.noam.jar;

import android.content.Context;
import android.content.SharedPreferences;

import com.noam.jar.core.ServerList;

import java.util.List;

/** Settings for the companion app (same style as PhotoDream's Prefs). */
public final class Prefs {
    private static final String FILE = "jar_prefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_SERVER_URLS = "server_urls";   // from pairing, one per line
    private static final String KEY_LAST_GOOD = "last_good_url";
    private static final String KEY_TOKEN = "token";
    private static final String KEY_DEVICE_ID = "device_id";
    private static final String KEY_OFFLINE_SIM = "offline_sim";
    private static final String KEY_HISTORY = "history";
    private static final int HISTORY_LINES = 40;

    private final SharedPreferences sp;

    public Prefs(Context context) {
        sp = context.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /**
     * Every address the PC can be reached at (home network, Tailscale…), from pairing.
     * Uploads try the last one that worked first. Without pairing it's the one typed by hand.
     */
    public List<String> serverUrls() {
        List<String> urls = ServerList.split(sp.getString(KEY_SERVER_URLS, ""));
        if (urls.isEmpty()) urls.add(sp.getString(KEY_SERVER_URL, "http://192.168.1.50:8080"));
        return urls;
    }

    /** The address to show: the one that worked last, else the first. */
    public String serverUrl() {
        List<String> ordered = ServerList.ordered(serverUrls(), lastGoodUrl());
        return ordered.get(0);
    }

    /** Typed by hand: replaces any paired list with this single address. */
    public void setServerUrl(String v) {
        String url = trimSlash(v);
        if (url.equals(serverUrl())) return;    // unchanged: keep the paired list
        sp.edit().putString(KEY_SERVER_URL, url).remove(KEY_SERVER_URLS).remove(KEY_LAST_GOOD).apply();
    }

    public void setServerUrls(List<String> urls) {
        sp.edit().putString(KEY_SERVER_URLS, ServerList.join(urls))
                .putString(KEY_SERVER_URL, urls.get(0)).remove(KEY_LAST_GOOD).apply();
    }

    /** Addresses the PC reports on each sync (e.g. a new public one). Keeps the last one that worked. */
    public void mergeServerUrls(List<String> fromPc) {
        if (fromPc.isEmpty()) return;
        List<String> merged = ServerList.merge(serverUrls(), fromPc);
        if (merged.equals(serverUrls())) return;
        sp.edit().putString(KEY_SERVER_URLS, ServerList.join(merged)).putString(KEY_SERVER_URL, merged.get(0)).apply();
    }

    public String lastGoodUrl() {
        return sp.getString(KEY_LAST_GOOD, "");
    }

    public void setLastGoodUrl(String url) {
        if (!url.equals(lastGoodUrl())) sp.edit().putString(KEY_LAST_GOOD, url).apply();
    }

    /** Must match JAR_DEVICE_TOKEN on the server. */
    public String token() {
        return sp.getString(KEY_TOKEN, "");
    }

    public void setToken(String v) {
        sp.edit().putString(KEY_TOKEN, v.trim()).apply();
    }

    /** Shows up in the server's metadata so phone memos are easy to tell from the pendant's. */
    public String deviceId() {
        return com.noam.jar.core.ServerList.cleanDeviceId(sp.getString(KEY_DEVICE_ID, "phone-01"));
    }

    public void setDeviceId(String v) {
        sp.edit().putString(KEY_DEVICE_ID, com.noam.jar.core.ServerList.cleanDeviceId(v)).apply();
    }

    /** Pretend there is no Wi-Fi: memos stay queued, like the pendant away from home. */
    public boolean offlineSim() {
        return sp.getBoolean(KEY_OFFLINE_SIM, false);
    }

    public void setOfflineSim(boolean v) {
        sp.edit().putBoolean(KEY_OFFLINE_SIM, v).apply();
    }

    /** Newest line first. Kept short: it's a log for testing, not an archive. */
    public String history() {
        return sp.getString(KEY_HISTORY, "");
    }

    public synchronized void addHistory(String line) {
        String old = history();
        String[] lines = old.isEmpty() ? new String[0] : old.split("\n");
        StringBuilder sb = new StringBuilder(line);
        for (int i = 0; i < lines.length && i < HISTORY_LINES - 1; i++) sb.append('\n').append(lines[i]);
        sp.edit().putString(KEY_HISTORY, sb.toString()).apply();
    }

    public void clearHistory() {
        sp.edit().remove(KEY_HISTORY).apply();
    }

    /** Last problem syncing tasks ("" = fine), shown above the task list. */
    public String taskProblem() {
        return sp.getString("task_problem", "");
    }

    public void setTaskProblem(String v) {
        if (!v.equals(taskProblem())) sp.edit().putString("task_problem", v).apply();
    }

    private static String trimSlash(String v) {
        String s = v.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
