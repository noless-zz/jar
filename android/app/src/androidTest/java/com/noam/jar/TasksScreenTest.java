package com.noam.jar;

import static androidx.test.espresso.Espresso.onView;
import static androidx.test.espresso.Espresso.openActionBarOverflowOrOptionsMenu;
import static androidx.test.espresso.action.ViewActions.click;
import static androidx.test.espresso.assertion.ViewAssertions.doesNotExist;
import static androidx.test.espresso.assertion.ViewAssertions.matches;
import static androidx.test.espresso.matcher.RootMatchers.isDialog;
import static androidx.test.espresso.matcher.ViewMatchers.isDisplayed;
import static androidx.test.espresso.matcher.ViewMatchers.withSubstring;
import static androidx.test.espresso.matcher.ViewMatchers.withText;

import android.Manifest;
import android.content.Context;
import android.os.Build;
import android.os.ParcelFileDescriptor;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.GrantPermissionRule;
import androidx.test.uiautomator.UiDevice;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.IOException;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * The task screen on a real emulator, from a stored task list (no PC needed: the sync just fails).
 * Checks the done sections, the archive and the parents-only setting, and that the app starts at all.
 * Screenshots go to /sdcard/Pictures/jar and are uploaded by the GitHub workflow.
 */
@RunWith(AndroidJUnit4.class)
public class TasksScreenTest {

    @Rule
    public GrantPermissionRule permissions = Build.VERSION.SDK_INT >= 33
            ? GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
            : GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO);

    private static final long HOUR = 3600_000L, DAY = 24 * HOUR;
    private Context context;
    private ActivityScenario<TasksActivity> scenario;

    @Before
    public void setUp() {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.getSharedPreferences("jar_prefs", Context.MODE_PRIVATE).edit().clear().commit();
        context.getSharedPreferences("jar_tasks", Context.MODE_PRIVATE).edit().clear().commit();
        LookPrefs.setNewUi(context, false);      // these tests are about the classic screen
        Prefs prefs = new Prefs(context);
        prefs.setServerUrl("http://127.0.0.1:9");   // nothing listens there: the sync fails fast, the stored list stays
        prefs.setToken("emulator-test");
    }

    @After
    public void tearDown() {
        if (scenario != null) scenario.close();
    }

    @Test
    public void parent_seesDoneSectionsAndArchive() throws Exception {
        seed("noam");
        scenario = ActivityScenario.launch(TasksActivity.class);
        onView(withText("Buy milk")).check(matches(isDisplayed()));
        // my part is done, Livne's isn't: it stays with the open tasks
        onView(withText("Clean the room together")).check(matches(isDisplayed()));
        onView(withText(R.string.header_done_today)).check(matches(isDisplayed()));
        onView(withText("Took out the trash")).check(matches(isDisplayed()));
        onView(withText(R.string.header_done_week)).check(matches(isDisplayed()));
        onView(withText("Washed the car")).check(matches(isDisplayed()));
        onView(withText("Fixed the bike")).check(doesNotExist());          // a week old: in the archive
        screenshot("01-mine-done-sections");

        onView(withText("Old declined idea")).check(doesNotExist());       // declined: not on my list at all
        onView(withText(context.getString(R.string.archive_button, 1))).perform(click());
        onView(withSubstring("Fixed the bike")).inRoot(isDialog()).check(matches(isDisplayed()));
        screenshot("02-archive");
        onView(withText(android.R.string.ok)).inRoot(isDialog()).perform(click());

        openActionBarOverflowOrOptionsMenu(context);
        onView(withText(R.string.menu_keep_done)).perform(click());
        onView(withText(R.string.keep_forever)).inRoot(isDialog()).check(matches(isDisplayed()));
        screenshot("03-keep-finished");
    }

    @Test
    public void child_cannotChangeHowLongTasksAreKept() throws Exception {
        seed("livne");
        scenario = ActivityScenario.launch(TasksActivity.class);
        onView(withText("Clean the room together")).check(matches(isDisplayed()));
        openActionBarOverflowOrOptionsMenu(context);
        onView(withText(R.string.menu_areas)).check(matches(isDisplayed()));
        onView(withText(R.string.menu_keep_done)).check(doesNotExist());
        screenshot("04-child-menu");
    }

    @Test
    public void settingsScreen_opens() {
        try (ActivityScenario<MainActivity> s = ActivityScenario.launch(MainActivity.class)) {
            s.onActivity(a -> org.junit.Assert.assertFalse(a.isFinishing()));
            screenshot("05-settings");
        }
    }

    // ---------------------------------------------------------------- the stored task list

    private void seed(String me) throws JSONException {
        TaskCache cache = new TaskCache(context);
        JSONArray family = new JSONArray()
                .put(person("noam", "Noam", "parent", true))
                .put(person("livne", "Livne", "child", false));
        JSONObject who = me.equals("noam") ? family.getJSONObject(0) : family.getJSONObject(1);
        cache.setMe(new JSONObject().put("person", who).put("family", family));

        long now = System.currentTimeMillis();
        JSONArray tasks = new JSONArray()
                .put(task("t1", "Buy milk", me, "open", null, now - HOUR))
                .put(task("t2", "Took out the trash", me, "done", now - 2 * HOUR, now - 2 * HOUR))
                .put(task("t3", "Washed the car", me, "done", now - 3 * DAY, now - 3 * DAY))
                .put(task("t4", "Fixed the bike", me, "done", now - 20 * DAY, now - 20 * DAY))
                .put(task("t5", "Old declined idea", me, "declined", null, now - 30 * DAY));
        JSONObject shared = task("t6", "Clean the room together", "noam", "open", null, now - HOUR)
                .put("assignees", new JSONArray().put("noam").put("livne"))
                .put("mode", "all")
                .put("done_parts", new JSONObject().put("noam", utc(now - HOUR)));
        tasks.put(shared);
        cache.setTasks(new JSONObject().put("rev", 1).put("tasks", tasks)
                .put("series", new JSONArray()).put("areas", new JSONArray())
                .put("settings", new JSONObject().put("keep_done_days", 0)));
    }

    private static JSONObject person(String id, String name, String role, boolean admin) throws JSONException {
        return new JSONObject().put("id", id).put("name", name).put("role", role).put("admin", admin);
    }

    private static JSONObject task(String id, String title, String who, String status, Long doneAt, long updated)
            throws JSONException {
        return new JSONObject().put("id", id).put("title", title).put("assignee", who)
                .put("assignees", new JSONArray().put(who)).put("created_by", who).put("status", status)
                .put("done_at", doneAt == null ? JSONObject.NULL : utc(doneAt))
                .put("done_by", doneAt == null ? JSONObject.NULL : who)
                .put("created_at", utc(updated - DAY)).put("updated_at", utc(updated)).put("kind", "task");
    }

    private static String utc(long millis) {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date(millis));
    }

    // ---------------------------------------------------------------- screenshots

    private static void screenshot(String name) {
        UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).waitForIdle();
        shell("mkdir -p /sdcard/Pictures/jar");
        shell("screencap -p /sdcard/Pictures/jar/" + name + ".png");
    }

    /** Runs a shell command on the emulator and waits for it to finish. */
    private static void shell(String command) {
        ParcelFileDescriptor pfd = InstrumentationRegistry.getInstrumentation()
                .getUiAutomation().executeShellCommand(command);
        try (InputStream in = new ParcelFileDescriptor.AutoCloseInputStream(pfd)) {
            byte[] buffer = new byte[1024];
            while (in.read(buffer) != -1) {
                // drain the output; the command is done when the stream ends
            }
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }
}
