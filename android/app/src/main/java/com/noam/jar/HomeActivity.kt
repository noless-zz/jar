package com.noam.jar

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.ActivityNotFoundException
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import android.widget.Toast
import com.noam.jar.core.Area
import com.noam.jar.core.Series
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import org.json.JSONObject
import java.util.TimeZone
import java.util.concurrent.Executors

/**
 * The new design (Compose): tasks, family, coin board and ideas behind one bottom bar with the record
 * button in the middle, plus settings. Opt-in while it is being built ("New design (beta)" in the classic menu);
 * what isn't rebuilt yet opens the classic screen at the right place.
 */
class HomeActivity : ComponentActivity() {
    private val version = mutableIntStateOf(0)
    private val recording = mutableStateOf(false)
    private val memo = mutableStateOf<JSONObject?>(null)
    val moment = mutableStateOf<DoneMoment?>(null)
    /** Screens on top of the tabs (settings, recurring, areas …), the top one showing. */
    val stack = mutableStateListOf<Sub>()
    /** The add / edit sheet, when open. */
    val editing = mutableStateOf<EditReq?>(null)
    /** The task whose notes [Sub.THREAD] shows. */
    val threadId = mutableStateOf("")
    /** The task whose sheet is open (by id, so it follows the newest copy). */
    val openTask = mutableStateOf<String?>(null)
    /** A sheet that isn't about one task: "invite" or "about". */
    val global = mutableStateOf<String?>(null)
    /** Just paired from the welcome screen: show the "you're in" step before the list. */
    val onboarding = mutableStateOf(false)
    private var pendingApk: java.io.File? = null     // a downloaded update waiting for "allow installs from Jar"
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = refresh()
    }
    private val ticker = object : Runnable {
        override fun run() {
            refresh()
            if (RecorderService.isRecording()) main.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        TaskNotify.channels(this)
        setContent {
            val v by version
            val cache = remember(v) { TaskCache(this) }
            // Children start on Playful; before pairing nobody is known yet, so the welcome screen is Calm.
            val look = remember(v) { LookPrefs.load(this, cache.myId().isNotEmpty() && !cache.iAmParent()) }
            JarThemed(look) {
                SystemBars()
                androidx.compose.runtime.CompositionLocalProvider(LocalActions provides actions) {
                    HomeScreen(cache, v, recording.value, memo.value, moment.value, stack.lastOrNull(), editing.value, threadId.value,
                        openTask.value, global.value, onboarding.value)
                }
            }
        }
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    override fun onResume() {
        super.onResume()
        // Every time the screen comes back: a quiet look at GitHub (at most every few minutes), so a new
        // version's banner is there right away, without going to Settings → About.
        if (Updater.enabled()) io.execute {
            if (runCatching { Updater.checkOnOpen(this) }.getOrDefault(false)) main.post { refresh() }
        }
        // Back from "allow installs from this source": carry on with the update.
        val apk = pendingApk
        if (apk != null && packageManager.canRequestPackageInstalls()) {
            pendingApk = null
            Updater.install(this, apk)
        }
    }

    /** From a notification, the widget or the classic screen: open a task, its notes, a WhatsApp message, an invite, a screen. */
    private fun handle(i: Intent?) {
        if (i == null) return
        val cache = TaskCache(this)
        i.getStringExtra(TasksActivity.EXTRA_OPEN)?.let { id -> i.removeExtra(TasksActivity.EXTRA_OPEN); openTask.value = id }
        i.getStringExtra(EXTRA_THREAD)?.let { id -> i.removeExtra(EXTRA_THREAD); cache.find(id)?.let { actions.thread(it) } }
        i.getStringExtra(TasksActivity.EXTRA_SEND)?.let { id ->
            i.removeExtra(TasksActivity.EXTRA_SEND)
            cache.find(id)?.takeIf { it.isMessage }?.let { actions.sendWhatsApp(it) }
        }
        if (i.getBooleanExtra(TasksActivity.EXTRA_ADD, false)) { i.removeExtra(TasksActivity.EXTRA_ADD); editing.value = EditReq(null) }
        if (i.getBooleanExtra(TasksActivity.EXTRA_INVITE, false)) { i.removeExtra(TasksActivity.EXTRA_INVITE); global.value = "invite" }
        i.getStringExtra(EXTRA_SUB)?.let { name -> i.removeExtra(EXTRA_SUB); runCatching { Sub.valueOf(name) }.getOrNull()?.let { actions.go(it) } }
    }

    /** WhatsApp (or WhatsApp Business) when installed; otherwise the link opens in the browser. */
    private fun whatsapp(url: String): Intent {
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        for (pkg in listOf("com.whatsapp", "com.whatsapp.w4b")) {
            if (runCatching { packageManager.getPackageInfo(pkg, 0) }.isSuccess) { i.setPackage(pkg); break }
        }
        return i
    }

    companion object {
        const val EXTRA_THREAD = "thread_task"
        const val EXTRA_SUB = "sub_screen"
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(this, receiver, IntentFilter(Jar.ACTION_STATE), ContextCompat.RECEIVER_NOT_EXPORTED)
        refresh()
        if (Prefs(this).token().isNotEmpty()) TaskSync.now(this)
        if (RecorderService.isRecording()) main.post(ticker)
    }

    override fun onStop() {
        unregisterReceiver(receiver)
        main.removeCallbacks(ticker)
        super.onStop()
    }

    override fun onDestroy() {
        io.shutdown()
        super.onDestroy()
    }

    private fun refresh() {
        recording.value = RecorderService.isRecording()
        version.intValue++
    }

    /** The newest memo, for the "Jar heard" card (best effort; nothing shown when the PC can't be reached). */
    private fun loadMemo() {
        val prefs = Prefs(this)
        io.execute {
            val newest = runCatching {
                val arr = TaskApi.memos(prefs).optJSONArray("memos")
                var best: JSONObject? = null
                for (i in 0 until (arr?.length() ?: 0)) {
                    val m = arr!!.optJSONObject(i) ?: continue
                    if (best == null || m.optString("recorded_at") > best.optString("recorded_at")) best = m
                }
                best
            }.getOrNull()
            main.post { memo.value = newest }
        }
    }

    val actions = object : HomeActions {
        override fun act(t: Task, action: String, until: String?) {
            val me0 = TaskCache(this@HomeActivity).myId()
            val forOther = action == "done" && !t.isFor(me0)
            TaskReceiver.apply(this@HomeActivity, t.id, action, until)
            if (forOther) {
                val names = TaskCache(this@HomeActivity).names()
                toast(getString(R.string.ui_done_for_toast, t.owners().joinToString(", ") { TaskLists.name(names, it) }))
            } else if (action == "done" && !t.isMessage) {
                val cache = TaskCache(this@HomeActivity)
                val me = cache.myId()
                val left = TaskLists.mine(cache.tasks(), me).count {
                    TaskLists.doneBucket(it, null, System.currentTimeMillis()) == TaskLists.OPEN &&
                        (it.dueDay() == null || it.dueDay()!! <= TaskLists.day(System.currentTimeMillis(), TimeZone.getDefault()))
                }
                val board = cache.board()
                val mine = board.people.firstOrNull { it.id == me }
                moment.value = DoneMoment(t, t.coins, left, mine?.week ?: 0, mine?.streak ?: 0, cache.myName(), System.nanoTime())
            }
        }

        override fun undo(m: DoneMoment) {
            TaskReceiver.apply(this@HomeActivity, m.task.id, "reopen", null)
            moment.value = null
        }

        override fun dismissMoment() {
            moment.value = null
        }

        override fun classic(tab: Int, extras: (Intent) -> Unit) {
            val i = Intent(this@HomeActivity, TasksActivity::class.java).putExtra(TasksActivity.EXTRA_CLASSIC, true)
                .putExtra(TasksActivity.EXTRA_TAB, tab)
            extras(i)
            startActivity(i)
        }

        override fun record() {
            RecorderService.send(this@HomeActivity, RecorderService.ACTION_TOGGLE)
            main.removeCallbacks(ticker)
            main.postDelayed(ticker, 200)
        }

        override fun thread(t: Task) {
            threadId.value = t.id
            go(Sub.THREAD)
            TaskSync.now(this@HomeActivity)     // fetch the newest notes
        }

        override fun open(c: Class<*>) {
            startActivity(Intent(this@HomeActivity, c))
        }

        override fun go(s: Sub) {
            stack.remove(s)
            stack.add(s)
        }

        override fun back() {
            if (stack.isNotEmpty()) stack.removeAt(stack.size - 1)
        }

        override fun edit(req: EditReq?) {
            editing.value = req
        }

        override fun toast(msg: String) {
            Toast.makeText(this@HomeActivity, msg, Toast.LENGTH_LONG).show()
        }

        override fun <T> background(work: () -> T, ok: (T) -> Unit, err: (Exception) -> Unit) {
            io.execute {
                try {
                    val r = work()
                    main.post { ok(r); TaskSync.now(this@HomeActivity) }
                } catch (e: Exception) {
                    main.post { err(e) }
                }
            }
        }

        override fun openTask(id: String?) {
            openTask.value = id
        }

        override fun global(kind: String?) {
            global.value = kind
        }

        override fun onboarding(on: Boolean) {
            onboarding.value = on
            refresh()
        }

        override fun sendWhatsApp(t: Task) {
            try {
                startActivity(whatsapp(t.whatsappUrl()))
                act(t, "done", null)          // ticked as sent; "Not done yet" brings it back
            } catch (e: ActivityNotFoundException) {
                toast(getString(R.string.whatsapp_missing))
            }
        }

        override fun invite(personId: String) {
            toast(getString(R.string.invite_preparing))
            val prefs = Prefs(this@HomeActivity)
            background({ TaskApi.invite(prefs, personId) }, { r ->
                val t = Task().apply { message = r.optString("text"); phone = r.optString("phone") }
                try {
                    startActivity(whatsapp(t.whatsappUrl()))
                } catch (e: ActivityNotFoundException) {
                    startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, t.message),
                        getString(R.string.menu_invite)))
                }
            }, { e -> toast(getString(R.string.invite_failed, e.message)) })
        }

        override fun shareApp() {
            val send = Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, getString(R.string.share_app_text, TasksActivity.downloadPage()))
            startActivity(Intent.createChooser(send, getString(R.string.share_app)))
        }

        override fun openUrl(url: String) {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }

        override fun checkUpdate() {
            if (!Updater.enabled()) { toast(getString(R.string.update_dev_build, BuildConfig.VERSION_NAME)); return }
            background({ Updater.check(this@HomeActivity, true) }, { newer ->
                refresh()
                if (!newer) toast(getString(R.string.update_none, BuildConfig.VERSION_NAME))
            }, { e -> toast(getString(R.string.update_check_failed, e.message)) })
        }

        override fun installUpdate() {
            toast(getString(R.string.update_downloading))
            background({ Updater.download(this@HomeActivity) }, { apk ->
                if (!Updater.install(this@HomeActivity, apk)) {
                    pendingApk = apk
                    toast(getString(R.string.update_allow_installs))
                }
            }, { e -> toast(getString(R.string.update_failed, e.message)) })
        }

        override fun backToClassic() {
            LookPrefs.setNewUi(this@HomeActivity, false)
            classic(0) {}
            finish()
        }
    }
}

/** A task just finished: what the done moment shows (and what Undo brings back). */
data class DoneMoment(val task: Task, val coins: Int, val leftToday: Int, val weekCoins: Int, val streak: Int, val name: String, val id: Long)

interface HomeActions {
    fun act(t: Task, action: String, until: String? = null)
    fun undo(m: DoneMoment)
    fun dismissMoment()
    fun classic(tab: Int, extras: (Intent) -> Unit = {})
    fun record()
    fun thread(t: Task)
    fun open(c: Class<*>)
    fun backToClassic()
    fun go(s: Sub)
    fun back()
    fun edit(req: EditReq?)
    fun toast(msg: String)
    fun openTask(id: String?)
    fun global(kind: String?)
    fun onboarding(on: Boolean)
    fun sendWhatsApp(t: Task)
    fun invite(personId: String)
    fun shareApp()
    fun openUrl(url: String)
    fun checkUpdate()
    fun installUpdate()
    /** Off the main thread (a call to the PC), then [ok] on it and a sync; [err] when it failed. */
    fun <T> background(work: () -> T, ok: (T) -> Unit, err: (Exception) -> Unit)

    /** A call to the PC; on failure a toast from [fail] (a string with one %s for the reason). */
    fun call(fail: Int, ctx: Context, ok: () -> Unit = {}, work: () -> Unit) =
        background(work, { ok() }, { e -> toast(ctx.getString(fail, e.message ?: e.javaClass.simpleName)) })
}

/** The screens that open over the tabs. */
enum class Sub { SETTINGS, RECURRING, AREAS, ARCHIVE, MEMOS, THREAD }

/** Open the add / edit sheet: a new task ([task] null), an edit, or "make it repeat" ([repeat]). */
data class EditReq(val task: Task?, val repeat: Boolean = false)

val LocalActions = staticCompositionLocalOf<HomeActions> { error("no actions") }

enum class Tab { TASKS, FAMILY, BOARD, IDEAS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HomeScreen(cache: TaskCache, version: Int, recording: Boolean, memo: JSONObject?, moment: DoneMoment?, sub: Sub?, editing: EditReq?, threadId: String,
                       openTask: String?, global: String?, onboarding: Boolean) {
    val c = LocalJar.current.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var tab by remember { mutableStateOf(Tab.TASKS) }
    val sheet = { t: Task -> actions.openTask(t.id) }
    val parent = cache.iAmParent()
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok -> if (ok) actions.record() }
    val onRecord = {
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) actions.record()
        else askMic.launch(Manifest.permission.RECORD_AUDIO)
    }
    BackHandler(enabled = sub != null || tab != Tab.TASKS) { if (sub != null) actions.back() else tab = Tab.TASKS }

    val data = remember(version) { HomeData.of(cache, ctx) }
    val paired = remember(version) { Prefs(ctx).token().isNotEmpty() }
    if (!paired || onboarding) {
        Box(Modifier.fillMaxSize().background(c.bg).windowInsetsPadding(WindowInsets.safeDrawing)) { WelcomeScreen(data, paired) }
        return
    }
    Box(Modifier.fillMaxSize().background(c.bg).windowInsetsPadding(WindowInsets.safeDrawing)) {
        if (sub != null) {
            when (sub) {
                Sub.SETTINGS -> SettingsScreen(data, onBack = { actions.back() })
                Sub.RECURRING -> RecurringScreen(data)
                Sub.AREAS -> AreasScreen(data)
                Sub.ARCHIVE -> ArchiveScreen(data, onOpen = sheet)
                Sub.MEMOS -> MemosScreen()
                Sub.THREAD -> ThreadScreen(threadId, data)
            }
        } else {
            when (tab) {
                Tab.TASKS -> TasksTab(data, memo, onOpen = sheet, onSettings = { actions.go(Sub.SETTINGS) })
                Tab.FAMILY -> FamilyTab(data, onOpen = sheet)
                Tab.BOARD -> BoardTab(data)
                Tab.IDEAS -> IdeasTab(data, onOpen = sheet)
            }
            BottomBar(Modifier.align(Alignment.BottomCenter), tab, parent, recording, onTab = { tab = it }, onRecord = onRecord)
        }
        if (moment != null) DoneOverlay(moment, Modifier.align(Alignment.BottomCenter))
        if (recording) RecordOverlay(onStop = onRecord)
    }
    val open = openTask?.let { id -> data.all.firstOrNull { it.id == id } }
    if (open != null) {
        val close = { actions.openTask(null) }
        ModalBottomSheet(onDismissRequest = close, containerColor = c.bg) {
            if (open.isIdea) IdeaSheet(open, data, onClose = close)
            else TaskSheet(open, data, onClose = close)
        }
    }
    if (global != null) {
        val close = { actions.global(null) }
        ModalBottomSheet(onDismissRequest = close, containerColor = c.bg) {
            if (global == "invite") InviteSheet(data, close) else AboutSheet(data, close)
        }
    }
    if (editing != null) {
        ModalBottomSheet(onDismissRequest = { actions.edit(null) }, containerColor = c.bg,
            sheetState = androidx.compose.material3.rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            EditTaskSheet(editing, data, onClose = { actions.edit(null) })
        }
    }
}

/** Everything the tabs show, read once per refresh. */
class HomeData(
    val me: String, val myName: String, val parent: Boolean, val admin: Boolean, val all: List<Task>,
    val names: Map<String, String>, val colors: Map<String, Color>, val board: com.noam.jar.core.Board, val syncedAt: Long,
    val parents: Set<String>, val areas: List<Area> = emptyList(), val series: List<Series> = emptyList(), val keepDone: Int = 0,
    /** A newer Jar on GitHub (its tag) and what's new in it, or null. */
    val update: String? = null, val whatsNew: String = "",
) {
    fun color(id: String): Color = colors[id] ?: PersonColors[0]

    /** May I turn this one-time task into a recurring one? (the PC checks the same) */
    fun canMakeRepeat(t: Task): Boolean {
        if (t.isRecurring || t.isMessage || t.isIdea || t.isLesson || !(t.isOpen || t.isRequested)) return false
        if (me == t.createdBy || admin) return true
        if (!parent) return false
        return t.owners().none { it in parents }
    }

    fun seriesOf(t: Task): Series? = if (t.isRecurring) series.firstOrNull { it.id == t.seriesId } else null

    fun mayChange(s: Series) = s.canChange(me, admin, parent, parents)

    companion object {
        fun of(cache: TaskCache, ctx: Context): HomeData {
            val names = cache.names()
            TaskFormat.setAreas(cache.areas())
            return HomeData(cache.myId(), cache.myName(), cache.iAmParent(), cache.iAmAdmin(), cache.tasks(), names,
                names.keys.mapIndexed { i, id -> id to PersonColors[i % PersonColors.size] }.toMap(), cache.board(),
                cache.syncedAt(), cache.parents(), cache.areas(), cache.series(), cache.keepDoneDays(),
                Updater.availableTag(ctx), Updater.whatsNew(ctx))
        }
    }
}

/** Status and navigation bars in the look's background, with icons that stay readable. */
@Composable
fun SystemBars() {
    val c = LocalJar.current.colors
    val activity = LocalContext.current as? ComponentActivity ?: return
    LaunchedEffect(c.bg, c.dark) {
        val argb = android.graphics.Color.argb(255, (c.bg.red * 255).toInt(), (c.bg.green * 255).toInt(), (c.bg.blue * 255).toInt())
        val style = if (c.dark) SystemBarStyle.dark(argb) else SystemBarStyle.light(argb, argb)
        activity.enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
    }
}
