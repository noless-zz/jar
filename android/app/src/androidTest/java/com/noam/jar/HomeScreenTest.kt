package com.noam.jar

import android.Manifest
import android.content.Context
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import androidx.test.uiautomator.UiDevice
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * The new design (Compose) on a real emulator, in all three styles, from a stored task list.
 * It also checks that Calm and Night differ in more than colour: Night has the count header, the timeline,
 * the icon-only bar with the orb and slide-to-finish; Calm has the greeting, grouped cards, a labelled bar and a button grid.
 * Screenshots go to /sdcard/Pictures/jar and are uploaded by the GitHub workflow.
 */
@RunWith(AndroidJUnit4::class)
class HomeScreenTest {

    @get:Rule
    val permissions: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33)
        GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
    else GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)

    @get:Rule
    val compose = createEmptyComposeRule()

    private lateinit var context: Context
    private var scenario: ActivityScenario<*>? = null

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        for (f in listOf("jar_prefs", "jar_tasks", "jar_look")) context.getSharedPreferences(f, Context.MODE_PRIVATE).edit().clear().commit()
        val prefs = Prefs(context)
        prefs.setServerUrl("http://127.0.0.1:9")   // nothing listens there: the sync fails fast, the stored list stays
        prefs.setToken("emulator-test")
    }

    @After
    fun tearDown() {
        scenario?.close()
    }

    private fun s(id: Int, vararg args: Any) = context.getString(id, *args)

    private fun launch(style: JarStyle, mode: JarMode, accent: Int = 0, me: String = "noam") {
        seed(me)
        LookPrefs.save(context, Look(style, mode, accent, 0))
        scenario = ActivityScenario.launch(HomeActivity::class.java)
    }

    @Test
    fun calm_homeSheetDoneAndUndo() {
        launch(JarStyle.CALM, JarMode.LIGHT)
        compose.onNodeWithText("Buy milk").assertExists()
        compose.onNodeWithText(s(R.string.ui_sec_overdue)).assertExists()
        compose.onNodeWithText(s(R.string.ui_sec_later)).assertExists()
        compose.onNodeWithText(s(R.string.header_done_today)).assertExists()
        compose.onNodeWithText("Fixed the bike").assertDoesNotExist()       // a week old: in the archive
        compose.onNodeWithTag("night_count").assertDoesNotExist()            // Calm greets you instead
        compose.onNodeWithText(s(R.string.ui_nav_family)).assertExists()    // a labelled bar, with Family for parents
        shot("10-calm-home")

        compose.onNodeWithText("Buy milk").performClick()
        compose.onNodeWithText(s(R.string.ui_edit)).assertExists()          // Calm's sheet: a grid of big buttons
        compose.onNodeWithTag("slide_done").assertDoesNotExist()
        shot("11-calm-sheet")
        compose.onNodeWithText(s(R.string.action_done)).performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("done_moment").assertExists()                 // the snackbar with Undo
        shot("12-calm-done")
        compose.onNodeWithText(s(R.string.ui_undo)).performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("done_moment").assertDoesNotExist()
    }

    @Test
    fun night_isMoreThanDarkCalm() {
        launch(JarStyle.NIGHT, JarMode.DARK, 1)
        compose.onNodeWithTag("night_count").assertExists()                 // the count header, no greeting
        compose.onNodeWithText("Pay the electricity").assertExists()
        compose.onNodeWithText(s(R.string.ui_nav_family)).assertDoesNotExist()           // icon-only bar…
        compose.onNodeWithContentDescription(s(R.string.ui_nav_family)).assertExists()   // …that still says what it is
        shot("13-night-home")
        compose.onNodeWithText("Buy milk").performClick()
        compose.onNodeWithTag("slide_done").assertExists()                  // slide to finish
        shot("19-night-sheet")
        compose.onNodeWithTag("slide_done").performClick()                  // a tap works too (accessibility)
        compose.waitForIdle()
        compose.onNodeWithTag("done_moment").assertExists()
        shot("20-night-done")
    }

    @Test
    fun night_light_keepsTheNightLayout() {
        launch(JarStyle.NIGHT, JarMode.LIGHT, 4)
        compose.onNodeWithTag("night_count").assertExists()
        shot("21-night-light")
    }

    @Test
    fun calm_dark_violet() {
        launch(JarStyle.CALM, JarMode.DARK, 6)
        compose.onNodeWithText("Buy milk").assertExists()
        compose.onNodeWithTag("night_count").assertDoesNotExist()
        shot("18-calm-dark")
    }

    @Test
    fun playful_isTheDefaultForAChild_andCelebrates() {
        seed("livne")
        scenario = ActivityScenario.launch(HomeActivity::class.java)
        compose.onNodeWithText("Clean the room together").assertExists()
        compose.onNodeWithText(s(R.string.ui_nav_family)).assertDoesNotExist()
        compose.onNodeWithContentDescription(s(R.string.ui_nav_family)).assertDoesNotExist()   // not for kids
        assertEquals(JarStyle.PLAYFUL, LookPrefs.load(context, true).style)
        shot("14-playful-home")
        compose.onNodeWithText("Pay the electricity").performClick()
        compose.onNodeWithText(s(R.string.action_done)).performClick()
        compose.waitForIdle()
        compose.onNodeWithText(s(R.string.ui_yes)).assertExists()           // the full-screen sticker
        shot("22-playful-done")
        compose.onNodeWithText(s(R.string.ui_yes)).performClick()
    }

    @Test
    fun tabs_inEachStyle() {
        for ((style, tag) in listOf(JarStyle.CALM to "calm", JarStyle.NIGHT to "night", JarStyle.PLAYFUL to "playful")) {
            scenario?.close()
            launch(style, if (style == JarStyle.NIGHT) JarMode.DARK else JarMode.LIGHT)
            tapTab(R.string.ui_nav_board)
            compose.onNodeWithTag("board").assertExists()
            shot("30-board-$tag")
            tapTab(R.string.ui_nav_ideas)
            compose.onNodeWithTag("ideas").assertExists()
            compose.onNodeWithText("Night mode").assertExists()
            shot("31-ideas-$tag")
            tapTab(R.string.ui_nav_family)
            compose.onNodeWithTag("family").assertExists()
            compose.onNodeWithText("Tidy your desk").assertExists()
            shot("32-family-$tag")
        }
    }

    /** The bar's items: labelled in Calm, icon-only (described) in Night and Playful. */
    private fun tapTab(res: Int) {
        val label = s(res)
        runCatching { compose.onNodeWithText(label).performClick() }
            .recoverCatching { compose.onNodeWithContentDescription(label).performClick() }.getOrThrow()
        compose.waitForIdle()
    }

    @Test
    fun settings_fromTheAvatar() {
        launch(JarStyle.CALM, JarMode.LIGHT)
        compose.onNodeWithContentDescription(s(R.string.ui_settings)).performClick()
        compose.onNodeWithText(s(R.string.ui_settings)).performClick()
        compose.onNodeWithTag("settings").assertExists()
        compose.onNodeWithText(s(R.string.ui_menu_look)).assertExists()
        shot("33-settings")
    }

    @Test
    fun record_showsTheRecordingScreen() {
        launch(JarStyle.NIGHT, JarMode.DARK)
        compose.onNodeWithTag("record").performClick()
        compose.waitUntil(5_000) { runCatching { compose.onNodeWithTag("record_overlay").assertExists() }.isSuccess }
        Thread.sleep(1500)
        shot("34-recording-night")
        compose.onNodeWithTag("stop").performClick()
        compose.waitUntil(5_000) { runCatching { compose.onNodeWithTag("record_overlay").assertDoesNotExist() }.isSuccess }
    }

    @Test
    fun look_pickNightAndSave() {
        seed("noam")
        scenario = ActivityScenario.launch(LookActivity::class.java)
        shot("15-look-calm")
        compose.onNodeWithTag("style_night").performClick()
        compose.waitForIdle()
        shot("16-look-night")
        compose.onNodeWithTag("style_playful").performClick()
        compose.waitForIdle()
        shot("17-look-playful")
        compose.onNodeWithTag("style_night").performClick()
        compose.onNodeWithTag("save").performClick()
        compose.waitForIdle()
        assertEquals(JarStyle.NIGHT, LookPrefs.load(context, false).style)
    }

    @Test
    fun classic_sendsYouToTheNewDesignWhenItIsOn() {
        seed("noam")
        LookPrefs.setNewUi(context, true)
        scenario = ActivityScenario.launch(TasksActivity::class.java)
        compose.onNodeWithText("Buy milk").assertExists()
    }

    // ---------------------------------------------------------------- the stored task list

    private fun seed(me: String) {
        val cache = TaskCache(context)
        val family = JSONArray().put(person("noam", "Noam", "parent", true)).put(person("livne", "Livne", "child", false))
        cache.setMe(JSONObject().put("person", family.getJSONObject(if (me == "noam") 0 else 1)).put("family", family))
        val now = System.currentTimeMillis()
        val tasks = JSONArray()
            .put(task("t1", "Buy milk", me, "open", null, now - HOUR, null))
            .put(task("t2", "Took out the trash", me, "done", now - 2 * HOUR, now - 2 * HOUR, null))
            .put(task("t3", "Washed the car", me, "done", now - 3 * DAY, now - 3 * DAY, null))
            .put(task("t4", "Fixed the bike", me, "done", now - 20 * DAY, now - 20 * DAY, null))
            .put(task("t7", "Call the vet", me, "open", null, now - HOUR, local(now + DAY, "10:00")))
            .put(task("t8", "Pay the electricity", me, "open", null, now - HOUR, local(now - DAY, "09:00")).put("coins", 6))
            .put(task("t6", "Clean the room together", "noam", "open", null, now - HOUR, null)
                .put("assignees", JSONArray().put("noam").put("livne")).put("mode", "all")
                .put("done_parts", JSONObject().put("noam", utc(now - HOUR))))
            .put(task("t9", "Tidy your desk", "livne", "open", null, now - HOUR, local(now, "18:00")).put("created_by", "noam"))
            .put(task("i1", "Night mode", "noam", "requested", null, now - HOUR, null).put("kind", "idea").put("created_by", "livne"))
        cache.setTasks(JSONObject().put("rev", 1).put("tasks", tasks).put("series", JSONArray()).put("areas", JSONArray())
            .put("settings", JSONObject().put("keep_done_days", 0)))
        cache.setPoints(JSONObject().put("me", me).put("week", JSONObject().put("start", local(now - 3 * DAY, "00:00").take(10)).put("end", local(now + 3 * DAY, "00:00").take(10)))
            .put("people", JSONArray()
                .put(JSONObject().put("id", "livne").put("name", "Livne").put("role", "child").put("week", 142).put("all_time", 1210).put("tasks_week", 11).put("streak", 4))
                .put(JSONObject().put("id", "noam").put("name", "Noam").put("role", "parent").put("week", 96).put("all_time", 900).put("tasks_week", 7).put("streak", 1)))
            .put("ledgers", JSONObject()))
    }

    private fun person(id: String, name: String, role: String, admin: Boolean) =
        JSONObject().put("id", id).put("name", name).put("role", role).put("admin", admin)

    private fun task(id: String, title: String, who: String, status: String, doneAt: Long?, updated: Long, due: String?) =
        JSONObject().put("id", id).put("title", title).put("assignee", who).put("assignees", JSONArray().put(who))
            .put("created_by", who).put("status", status).put("due", due ?: JSONObject.NULL)
            .put("done_at", doneAt?.let { utc(it) } ?: JSONObject.NULL).put("done_by", if (doneAt == null) JSONObject.NULL else who)
            .put("created_at", utc(updated - DAY)).put("updated_at", utc(updated)).put("kind", "task")

    private fun utc(millis: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date(millis))

    private fun local(millis: Long, time: String) = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date(millis)) + "T" + time

    // ---------------------------------------------------------------- screenshots

    private fun shot(name: String) {
        compose.waitForIdle()
        UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).waitForIdle()
        shell("mkdir -p /sdcard/Pictures/jar")
        shell("screencap -p /sdcard/Pictures/jar/$name.png")
    }

    private fun shell(command: String) {
        val pfd = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(pfd).use { input -> val buf = ByteArray(1024); while (input.read(buf) != -1) Unit }
    }

    private companion object {
        const val HOUR = 3_600_000L
        const val DAY = 24 * HOUR
    }
}
