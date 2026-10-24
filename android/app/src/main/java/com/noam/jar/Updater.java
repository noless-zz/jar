package com.noam.jar;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import com.noam.jar.core.Version;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Updates from the repo's GitHub Releases: checks the latest release, downloads its APK and
 * hands it to Android's installer (the family taps Install once). Release builds only; the
 * "Jar dev" build from Android Studio is updated from Android Studio.
 */
public final class Updater {
    private static final String FILE = "jar_update";
    private static final long CHECK_EVERY_MS = 6 * 3600 * 1000L;

    private Updater() {}

    /** Emulator tests turn the update banner on in the debug build (which never updates itself). */
    @androidx.annotation.VisibleForTesting
    public static volatile boolean testEnabled = false;

    public static boolean enabled() {
        return !BuildConfig.DEBUG || testEnabled;
    }

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** The newer release we know about ("v0.4.0"), or null. */
    public static String availableTag(Context c) {
        String tag = sp(c).getString("tag", null);
        return enabled() && tag != null && Version.newer(tag, BuildConfig.VERSION_CODE)
                && sp(c).getString("apk", null) != null ? tag : null;
    }

    public static String releaseNotes(Context c) {
        return sp(c).getString("notes", "");
    }

    /** "What's new" since the installed version, one line, in the phone's language ("" if unknown). */
    public static String whatsNew(Context c) {
        String lang = java.util.Locale.getDefault().getLanguage();
        return com.noam.jar.core.Changes.oneLine(releaseNotes(c), BuildConfig.VERSION_CODE,
                "iw".equals(lang) || "he".equals(lang), 4);
    }

    /**
     * Asks GitHub for the latest release (at most every 6 hours unless forced).
     * Returns true when a newer version is available. Background threads only.
     */
    public static boolean check(Context c, boolean force) throws IOException {
        return check(c, force ? 0 : CHECK_EVERY_MS);
    }

    /**
     * Opening the app asks GitHub again after an hour (the background check waits 6), so a release from
     * this evening shows on the task list the next time someone opens Jar.
     */
    public static boolean checkOnOpen(Context c) throws IOException {
        return check(c, 3600 * 1000L);
    }

    private static boolean check(Context c, long olderThanMs) throws IOException {
        if (!enabled()) return false;
        SharedPreferences sp = sp(c);
        long last = sp.getLong("checked_at", 0);
        if (System.currentTimeMillis() - last < olderThanMs) return availableTag(c) != null;
        JSONObject rel = getJson("https://api.github.com/repos/" + BuildConfig.UPDATE_REPO + "/releases/latest");
        String tag = rel.optString("tag_name", "");
        String apk = null;
        JSONArray assets = rel.optJSONArray("assets");
        if (assets != null) {
            for (int i = 0; i < assets.length(); i++) {
                JSONObject a = assets.optJSONObject(i);
                if (a != null && a.optString("name").endsWith(".apk")) {
                    apk = a.optString("browser_download_url");
                    break;
                }
            }
        }
        String notes = rel.optString("body", "");
        sp.edit().putLong("checked_at", System.currentTimeMillis()).putString("tag", tag)
                .putString("apk", apk).putString("notes", notes.length() > 6000 ? notes.substring(0, 6000) : notes)
                .apply();
        return availableTag(c) != null;
    }

    /** Downloads the release APK into the app's cache. Background threads only. */
    public static File download(Context c) throws IOException {
        String url = sp(c).getString("apk", null);
        String tag = sp(c).getString("tag", "latest");
        if (url == null) throw new IOException("no APK in the latest release");
        File dir = new File(c.getCacheDir(), "updates");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("can't create " + dir);
        File[] old = dir.listFiles();
        if (old != null) for (File f : old) //noinspection ResultOfMethodCallIgnored
            f.delete();
        File out = new File(dir, "jar-" + tag.replaceAll("[^A-Za-z0-9._-]", "") + ".apk");
        HttpURLConnection http = open(url);
        try {
            int code = http.getResponseCode();
            if (code != 200) throw new IOException("download failed: HTTP " + code);
            try (InputStream in = http.getInputStream(); OutputStream os = new FileOutputStream(out)) {
                byte[] buf = new byte[32768];
                int n;
                while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            }
        } finally {
            http.disconnect();
        }
        if (out.length() < 100_000) throw new IOException("the downloaded file is too small to be the app");
        return out;
    }

    /** Opens Android's installer for the APK; first asks to allow installs from Jar if needed. */
    public static boolean install(Activity a, File apk) {
        if (!a.getPackageManager().canRequestPackageInstalls()) {
            a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + a.getPackageName())));
            return false;   // the screen calls install() again when the user comes back
        }
        Uri uri = FileProvider.getUriForFile(a, a.getPackageName() + ".files", apk);
        a.startActivity(new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
        return true;
    }

    private static HttpURLConnection open(String url) throws IOException {
        HttpURLConnection http = (HttpURLConnection) new URL(url).openConnection();
        http.setConnectTimeout(10000);
        http.setReadTimeout(30000);
        http.setInstanceFollowRedirects(true);     // GitHub sends downloads to its CDN
        http.setRequestProperty("User-Agent", "Jar-Android/" + BuildConfig.VERSION_NAME);
        http.setRequestProperty("Accept", "application/vnd.github+json");
        return http;
    }

    private static JSONObject getJson(String url) throws IOException {
        HttpURLConnection http = open(url);
        try {
            int code = http.getResponseCode();
            if (code == 404) throw new IOException("no release published yet");
            if (code != 200) throw new IOException("GitHub answered HTTP " + code);
            try (InputStream in = http.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                return new JSONObject(out.toString(StandardCharsets.UTF_8.name()));
            } catch (JSONException e) {
                throw new IOException("unexpected answer from GitHub", e);
            }
        } finally {
            http.disconnect();
        }
    }
}
