package com.noam.jar

import android.Manifest
import android.content.Context
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
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
        MemoFeed.fake = null
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
        compose.onNodeWithTag("slide_done").performSemanticsAction(SemanticsActions.OnClick)   // what TalkBack's double-tap does
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
    fun newDesign_isTheDefault() {
        seed("noam")                                    // jar_look cleared: nobody chose anything
        scenario = ActivityScenario.launch(TasksActivity::class.java)
        compose.onNodeWithText("Buy milk").assertExists()
    }

    // ---------------------------------------------------------------- step 4: nothing left on the classic screen

    @Test
    fun notification_opensTheNewThread() {
        seed("livne")
        scenario = ActivityScenario.launch<TaskThreadActivity>(android.content.Intent(context, TaskThreadActivity::class.java)
            .putExtra(TaskThreadActivity.EXTRA_ID, "t9"))
        compose.waitUntil(5_000) { runCatching { compose.onNodeWithTag("thread").assertExists() }.isSuccess }
        compose.onNodeWithText("Yes, after my homework").assertExists()
    }

    @Test
    fun widget_opensTheTaskSheet() {
        seed("noam")
        scenario = ActivityScenario.launch<TasksActivity>(android.content.Intent(context, TasksActivity::class.java)
            .putExtra(TasksActivity.EXTRA_OPEN, "t1"))
        compose.waitUntil(5_000) { runCatching { compose.onNodeWithTag("all_actions").assertExists() }.isSuccess }
        compose.onNodeWithText(s(R.string.action_done)).assertExists()
    }

    @Test
    fun whatsappMessage_inTheSheet() {
        for ((style, mode, tag) in styles) {
            scenario?.close()
            launch(style, mode)
            compose.onNodeWithTag("task_list").performScrollToNode(hasText("Message to Grandma"))
            compose.onNodeWithText("Message to Grandma").performClick()
            compose.onNodeWithTag("message").assertExists()
            compose.onNodeWithTag("send_whatsapp").assertExists()
            compose.onNodeWithText("Hi Grandma, we'll come on Friday at five").assertExists()
            shot("51-message-$tag")
        }
    }

    @Test
    fun settings_inviteAndAbout() {
        launch(JarStyle.NIGHT, JarMode.DARK)
        openFromSettings(s(R.string.ui_set_invite))
        compose.onNodeWithTag("invite").assertExists()
        compose.onNodeWithText("Livne").assertExists()
        shot("52-invite")
        back()
        compose.onNodeWithTag("settings").performScrollToNode(hasText(s(R.string.ui_set_about)))
        compose.onNodeWithText(s(R.string.ui_set_about)).performClick()
        compose.onNodeWithTag("about").assertExists()
        compose.onNodeWithText(s(R.string.update_open_page)).assertExists()
        shot("53-about")
    }

    @Test
    fun welcome_firstRun_inEachStyle() {
        for ((style, mode, tag) in styles) {
            scenario?.close()
            for (f in listOf("jar_prefs", "jar_tasks")) context.getSharedPreferences(f, Context.MODE_PRIVATE).edit().clear().commit()
            LookPrefs.save(context, Look(style, mode, 0, 0))
            scenario = ActivityScenario.launch(HomeActivity::class.java)
            compose.onNodeWithTag("welcome").assertExists()
            compose.onNodeWithTag("scan").assertExists()
            shot("60-welcome-$tag")
        }
        // A copied invitation link: paired, then the "you're in" step (the PC isn't there, so the check fails quietly).
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            context.getSystemService(android.content.ClipboardManager::class.java)
                .setPrimaryClip(android.content.ClipData.newPlainText("Jar", "Join us: jar://pair?v=1&t=welcome-test&u=http%3A%2F%2F127.0.0.1%3A9"))
        }
        compose.onNodeWithTag("paste").performClick()
        compose.waitUntil(5_000) { runCatching { compose.onNodeWithTag("start").assertExists() }.isSuccess }
        assertEquals("welcome-test", Prefs(context).token())
        shot("61-welcome-paired")
        compose.onNodeWithTag("start").performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("welcome").assertDoesNotExist()
    }

    // ---------------------------------------------------------------- step 3: the screens that were still classic

    private val styles = listOf(Triple(JarStyle.CALM, JarMode.LIGHT, "calm"), Triple(JarStyle.NIGHT, JarMode.DARK, "night"),
        Triple(JarStyle.PLAYFUL, JarMode.LIGHT, "playful"))

    private fun back() {
        UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).pressBack()
        compose.waitForIdle()
    }

    @Test
    fun add_newTaskSheet_inEachStyle() {
        for ((style, mode, tag) in styles) {
            scenario?.close()
            launch(style, mode)
            compose.onNodeWithTag("add").performClick()
            compose.onNodeWithTag("edit_sheet").assertExists()
            compose.onNodeWithTag("add_title").performTextInput("Water the garden")
            compose.onNodeWithTag("person_livne").performClick()                         // two people: who has to do it?
            compose.onNodeWithText(s(R.string.add_mode_all)).assertExists()
            compose.onNodeWithText(s(R.string.add_mode_turns)).assertDoesNotExist()   // only for repeating tasks
            compose.onNodeWithText(s(R.string.repeat_daily)).performClick()
            compose.onNodeWithText(s(R.string.add_mode_turns)).assertExists()
            compose.onNodeWithText(s(R.string.add_when)).assertDoesNotExist()      // a repeating task has its own time
            shot("40-add-$tag")
        }
        compose.onNodeWithTag("add_save").performScrollTo().performClick()                           // no PC here: a toast, and the sheet closes
        compose.waitForIdle()
        compose.onNodeWithTag("edit_sheet").assertDoesNotExist()
    }

    @Test
    fun edit_andAllActions_fromTheSheet() {
        launch(JarStyle.CALM, JarMode.LIGHT)
        compose.onNodeWithText("Buy milk").performClick()
        compose.onNodeWithTag("all_actions").performClick()
        compose.onNodeWithTag("more_actions").assertExists()
        compose.onNodeWithTag("delete").assertExists()
        compose.onNodeWithText(plain(s(R.string.snooze_pick))).assertExists()
        shot("41-all-actions")
        compose.onNodeWithText(s(R.string.ui_edit)).performClick()
        compose.onNodeWithTag("edit_sheet").assertExists()
        compose.onNodeWithTag("add_title").assertTextContains("Buy milk")
        shot("41-edit")
    }

    private fun openFromSettings(label: String) {
        compose.onNodeWithContentDescription(s(R.string.ui_settings)).performClick()
        compose.onNodeWithText(s(R.string.ui_settings)).performClick()
        compose.onNodeWithTag("settings").performScrollToNode(hasText(label))
        compose.onNodeWithText(label).performClick()
        compose.waitForIdle()
    }

    @Test
    fun screens_inEachStyle() {
        MemoFeed.fake = listOf(
            JSONObject().put("id", "m1").put("recorded_at", utc(System.currentTimeMillis() - 2 * HOUR)).put("status", "done")
                .put("transcript", "Buy bread and milk tomorrow, and remind Livne about the desk")
                .put("actions", JSONArray().put("Added: Buy bread and milk").put("Reminder for Livne: Tidy your desk")),
            JSONObject().put("id", "m2").put("recorded_at", utc(System.currentTimeMillis() - DAY)).put("status", "done")
                .put("transcript", "Pay the electricity bill").put("actions", JSONArray().put("Added: Pay the electricity")),
        )
        for ((style, mode, tag) in styles) {
            scenario?.close()
            launch(style, mode)
            openFromSettings(plain(s(R.string.menu_recurring)))
            compose.onNodeWithTag("recurring").assertExists()
            compose.onNodeWithText("Water the plants").assertExists()
            shot("42-recurring-$tag")
            compose.onNodeWithText("Water the plants").performClick()
            compose.onNodeWithTag("series_sheet").assertExists()
            back()
            compose.onNodeWithTag("back").performClick()

            compose.onNodeWithTag("settings").performScrollToNode(hasText(plain(s(R.string.menu_areas))))
            compose.onNodeWithText(plain(s(R.string.menu_areas))).performClick()
            compose.onNodeWithTag("areas").assertExists()
            compose.onNodeWithText("Kitchen").assertExists()
            shot("43-areas-$tag")
            compose.onNodeWithText("Kitchen").performClick()
            compose.onNodeWithTag("area_sheet").assertExists()
            shot("44-area-$tag")
            back()
            compose.onNodeWithTag("back").performClick()

            compose.onNodeWithTag("settings").performScrollToNode(hasText(s(R.string.ui_archive_title)))
            compose.onNodeWithText(s(R.string.ui_archive_title)).performClick()
            compose.onNodeWithTag("archive").assertExists()
            compose.onNodeWithText("Fixed the bike").assertExists()
            shot("45-archive-$tag")
            compose.onNodeWithTag("back").performClick()

            compose.onNodeWithTag("settings").performScrollToNode(hasText(s(R.string.menu_memos)))
            compose.onNodeWithText(s(R.string.menu_memos)).performClick()
            compose.onNodeWithTag("memos").assertExists()
            compose.onNodeWithText("Pay the electricity bill").assertExists()
            shot("46-memos-$tag")
            compose.onNodeWithText("Pay the electricity bill").performClick()
            compose.onNodeWithTag("refile").assertExists()
            back()
        }
    }

    @Test
    fun archive_fromTheTaskList() {
        launch(JarStyle.NIGHT, JarMode.DARK)
        compose.onNodeWithTag("task_list").performScrollToNode(hasText(plain(s(R.string.archive_button, 1))))
        compose.onNodeWithText(plain(s(R.string.archive_button, 1))).performClick()
        compose.onNodeWithTag("archive").assertExists()
        compose.onNodeWithText("Fixed the bike").performClick()
        compose.onNodeWithText(s(R.string.action_reopen)).assertExists()     // an archived task can come back
    }

    @Test
    fun ideas_newAndDecide() {
        launch(JarStyle.NIGHT, JarMode.DARK)
        tapTab(R.string.ui_nav_ideas)
        compose.onNodeWithText(s(R.string.ui_new_idea)).performClick()
        compose.onNodeWithTag("idea_new").assertExists()
        shot("47-idea-new")
        back()
        compose.onNodeWithText("Night mode").performClick()
        compose.onNodeWithTag("idea_sheet").assertExists()
        compose.onNodeWithText(plain(s(R.string.idea_accept))).assertExists()   // the admin decides
        shot("48-idea-sheet")
    }

    @Test
    fun thread_inEachStyle() {
        for ((style, mode, tag) in styles) {
            scenario?.close()
            launch(style, mode, me = "livne")
            compose.onNodeWithText("Tidy your desk").performClick()
            compose.onNodeWithText(s(R.string.ui_reply)).performClick()
            compose.onNodeWithTag("thread").assertExists()
            compose.onNodeWithText("Yes, after my homework").assertExists()
            compose.onNodeWithText(s(R.string.thread_ask_name, "Noam")).assertExists()   // ask whoever gave it to you
            shot("50-thread-$tag")
            compose.onNodeWithTag("back").performClick()
            compose.onNodeWithTag("thread").assertDoesNotExist()
        }
    }

    @Test
    fun board_lessonForAChild() {
        seed("livne")
        scenario = ActivityScenario.launch(HomeActivity::class.java)
        tapTab(R.string.ui_nav_board)
        compose.onNodeWithText(s(R.string.ui_learned)).performClick()
        compose.onNodeWithTag("lesson").assertExists()
        shot("49-lesson-playful")
    }

    // ---------------------------------------------------------------- the home-screen widget

    /** The widget at three sizes on a wallpaper, drawn exactly as the launcher would (RemoteViews.apply). */
    private fun showWidgets(name: String): android.widget.LinearLayout {
        var column: android.widget.LinearLayout? = null
        scenario!!.onActivity { a ->
            val d = a.resources.displayMetrics.density
            val col = android.widget.LinearLayout(a).apply {
                orientation = android.widget.LinearLayout.VERTICAL
                setPadding((16 * d).toInt(), (40 * d).toInt(), (16 * d).toInt(), 0)
                background = android.graphics.drawable.GradientDrawable(android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                    intArrayOf(0xFF7C93B8.toInt(), 0xFF35465F.toInt()))
            }
            for ((w, h) in listOf(340 to 330, 340 to 190, 230 to 110)) {
                val view = WidgetBuilder.build(a, w, h).apply(a, col)
                col.addView(view, android.widget.LinearLayout.LayoutParams((w * d).toInt(), (h * d).toInt()).apply { bottomMargin = (14 * d).toInt() })
            }
            a.addContentView(col, android.view.ViewGroup.LayoutParams(-1, -1))
            column = col
        }
        shot("70-widget-$name")
        return column!!
    }

    @Test
    fun widget_inEachStyle() {
        for ((look, name) in listOf(Look(JarStyle.CALM, JarMode.LIGHT, 0, 0) to "calm", Look(JarStyle.CALM, JarMode.DARK, 6, 0) to "calm-dark",
            Look(JarStyle.NIGHT, JarMode.DARK, 1, 0) to "night", Look(JarStyle.NIGHT, JarMode.LIGHT, 4, 0) to "night-light",
            Look(JarStyle.PLAYFUL, JarMode.LIGHT, 0, 1) to "playful")) {
            scenario?.close()
            seed(if (look.style == JarStyle.PLAYFUL) "livne" else "noam")
            LookPrefs.save(context, look)
            scenario = ActivityScenario.launch(HomeActivity::class.java)
            compose.waitForIdle()
            showWidgets(name)
        }
    }

    @Test
    fun widget_tickFinishesTheTask() {
        launch(JarStyle.CALM, JarMode.LIGHT)
        compose.waitForIdle()
        val col = showWidgets("tick")
        val cache = TaskCache(context)
        val items = com.noam.jar.core.TaskLists.forWidget(cache.tasks(), "noam", true, 10)
        val i = items.indexOfFirst { !it.isMessage && !it.isRequested && !it.waitingOn("noam") }
        val id = items[i].id
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val rows = col.getChildAt(0).findViewById<android.view.ViewGroup>(R.id.w_rows)
            rows.getChildAt(i).findViewById<android.view.View>(R.id.r_tick).performClick()
        }
        val deadline = System.currentTimeMillis() + 8_000
        while (System.currentTimeMillis() < deadline && TaskCache(context).find(id)?.doneFor("noam") != true) Thread.sleep(200)
        assertEquals(true, TaskCache(context).find(id)?.doneFor("noam"))
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
            .put(task("t9", "Tidy your desk", "livne", "open", null, now - HOUR, local(now, "18:00")).put("created_by", "noam")
                .put("thread", JSONArray()
                    .put(JSONObject().put("id", 1).put("by", "noam").put("text", "Can you do it before dinner?").put("at", utc(now - 3 * HOUR)).put("ask", true))
                    .put(JSONObject().put("id", 2).put("by", "livne").put("text", "Yes, after my homework").put("at", utc(now - 2 * HOUR)))))
            .put(task("i1", "Night mode", "noam", "requested", null, now - HOUR, null).put("kind", "idea").put("created_by", "livne"))
            .put(task("t10", "Message to Grandma", me, "open", null, now - HOUR, null).put("kind", "message")
                .put("message", "Hi Grandma, we'll come on Friday at five").put("to", "Grandma"))
        val series = JSONArray()
            .put(JSONObject().put("id", "s1").put("title", "Water the plants").put("created_by", "noam").put("owners", JSONArray().put("noam").put("livne"))
                .put("rule", "weekly:sun,wed").put("time", "18:00").put("label", "Every Sunday and Wednesday at 18:00").put("rotate", true)
                .put("status", "active").put("next_turn", "livne"))
            .put(JSONObject().put("id", "s2").put("title", "Take out the recycling").put("created_by", "noam").put("owners", JSONArray().put("noam"))
                .put("rule", "weekly").put("label", "Every week").put("status", "paused"))
        val areas = JSONArray()
            .put(JSONObject().put("id", "a1").put("name", "Kitchen").put("emoji", "🍳").put("owner", "noam").put("keywords", JSONArray().put("dishes").put("fridge")))
            .put(JSONObject().put("id", "a2").put("name", "Floors").put("emoji", "🧹").put("owner", "livne").put("keywords", JSONArray().put("floor")))
            .put(JSONObject().put("id", "a3").put("name", "Garden").put("emoji", "🌿").put("owner", "noam").put("keywords", JSONArray()))
        cache.setTasks(JSONObject().put("rev", 1).put("tasks", tasks).put("series", series).put("areas", areas)
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
