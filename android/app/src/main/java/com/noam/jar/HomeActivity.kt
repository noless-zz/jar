package com.noam.jar

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Calendar
import java.util.TimeZone
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * The new task home (Compose), opt-in while it is being built: "New design (beta)" in the classic menu.
 * Screens that aren't rebuilt yet open the classic screen at the right place.
 */
class HomeActivity : ComponentActivity() {
    private val version = mutableIntStateOf(0)
    private val recording = mutableStateOf(false)
    private val memo = mutableStateOf<JSONObject?>(null)
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
            val look = remember(v) { LookPrefs.load(this, !cache.iAmParent()) }
            JarThemed(look) {
                HomeScreen(
                    cache = cache, version = v, recording = recording.value, memo = memo.value,
                    onToggleRecord = ::toggleRecording,
                    onClassic = { tab, extras -> openClassic(tab, extras) },
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(this, receiver, IntentFilter(Jar.ACTION_STATE), ContextCompat.RECEIVER_NOT_EXPORTED)
        refresh()
        if (Prefs(this).token().isNotEmpty()) {
            TaskSync.now(this)
            loadMemo()
        }
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

    fun toggleRecording() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        RecorderService.send(this, RecorderService.ACTION_TOGGLE)
        main.removeCallbacks(ticker)
        main.postDelayed(ticker, 200)
    }

    private fun openClassic(tab: Int, extras: (Intent) -> Unit) {
        val i = Intent(this, TasksActivity::class.java).putExtra(TasksActivity.EXTRA_CLASSIC, true)
            .putExtra(TasksActivity.EXTRA_TAB, tab)
        extras(i)
        startActivity(i)
    }
}

// ---------------------------------------------------------------- the screen

private enum class Filter { MINE, ASKED, QUESTIONS }

private data class Sections(
    val waiting: List<Task>, val overdue: List<Task>, val today: List<Task>, val later: List<Task>, val anytime: List<Task>,
    val doneToday: List<Task>, val doneWeek: List<Task>, val archived: Int,
)

private fun sectionsOf(list: List<Task>, waiting: List<Task>): Sections {
    val now = System.currentTimeMillis()
    val tz = TimeZone.getDefault()
    val today = TaskLists.day(now, tz)
    val o = mutableListOf<Task>(); val t = mutableListOf<Task>(); val l = mutableListOf<Task>(); val a = mutableListOf<Task>()
    val dt = mutableListOf<Task>(); val dw = mutableListOf<Task>(); var arch = 0
    for (task in list) {
        if (waiting.contains(task)) continue
        when (TaskLists.doneBucket(task, null, now)) {
            TaskLists.OPEN -> when {
                TaskFormat.overdue(task) -> o.add(task)
                task.dueDay() == null -> a.add(task)
                task.dueDay() == today -> t.add(task)
                task.dueDay()!! < today -> o.add(task)
                else -> l.add(task)
            }
            TaskLists.DONE_TODAY -> dt.add(task)
            TaskLists.DONE_WEEK -> dw.add(task)
            else -> arch++
        }
    }
    val byDue = compareBy<Task> { it.due ?: "9999" }
    return Sections(waiting, o.sortedWith(byDue), t.sortedWith(byDue), l.sortedWith(byDue), a,
        dt.sortedWith(TaskLists.NEWEST_DONE), dw.sortedWith(TaskLists.NEWEST_DONE), arch)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HomeScreen(
    cache: TaskCache, version: Int, recording: Boolean, memo: JSONObject?,
    onToggleRecord: () -> Unit, onClassic: (Int, (Intent) -> Unit) -> Unit,
) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val me = cache.myId()
    val parent = cache.iAmParent()
    val names = remember(version) { cache.names() }
    val all = remember(version) { cache.tasks() }
    var filter by remember { mutableStateOf(Filter.MINE) }
    var sheet by remember { mutableStateOf<Task?>(null) }
    var showDoneWeek by remember { mutableStateOf(false) }
    val askPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) onToggleRecord()
    }

    val mine = remember(version) { TaskLists.mine(all, me) }
    val asked = remember(version) { TaskLists.asked(all, me) }
    val questions = remember(version) { all.filter { it.waitingOn(me) } }
    val waiting = remember(version) { TaskLists.needMyOk(all, me, parent) }
    val list = when (filter) { Filter.MINE -> mine; Filter.ASKED -> asked; Filter.QUESTIONS -> questions }
    val s = remember(version, filter) { sectionsOf(list, if (filter == Filter.MINE) waiting else emptyList()) }
    val nothingOpen = s.waiting.isEmpty() && s.overdue.isEmpty() && s.today.isEmpty() && s.later.isEmpty() && s.anytime.isEmpty()
    val colorOf = remember(version) { personColors(names.keys.toList()) }
    remember(version) { TaskFormat.setAreas(cache.areas()); 0 }
    val recentMemo = memo?.takeIf {
        val at = TaskLists.utcMillis(it.optString("recorded_at"))
        at > 0 && System.currentTimeMillis() - at < 24 * 3600 * 1000L
    }

    Box(Modifier.fillMaxSize().background(c.bg).windowInsetsPadding(WindowInsets.safeDrawing)) {
        Column(Modifier.fillMaxSize()) {
            Header(cache, colorOf[me] ?: c.accent, onClassic)
            Row(Modifier.padding(horizontal = 20.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(stringResource(R.string.ui_filter_mine, mine.count { TaskLists.doneBucket(it, null, System.currentTimeMillis()) == TaskLists.OPEN }),
                    filter == Filter.MINE) { filter = Filter.MINE }
                FilterChip(stringResource(R.string.ui_filter_asked, asked.count { it.isOpen || it.isRequested }), filter == Filter.ASKED) { filter = Filter.ASKED }
                if (questions.isNotEmpty() || filter == Filter.QUESTIONS)
                    FilterChip(stringResource(R.string.ui_filter_questions, questions.size), filter == Filter.QUESTIONS) { filter = Filter.QUESTIONS }
            }
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth().testTag("task_list"),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 96.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (recentMemo != null && filter == Filter.MINE) item(key = "memo") { JarHeard(recentMemo) { ctx.startActivity(Intent(ctx, MemosActivity::class.java)) } }
                fun section(title: String, tasks: List<Task>, tone: Color = c.muted) {
                    if (tasks.isEmpty()) return
                    item(key = "h_$title") { SectionTitle(title, tone) }
                    items(tasks, key = { it.id }) { t ->
                        TaskRow(t, me, names, colorOf, onOpen = { sheet = t })
                    }
                }
                section(ctx.getString(R.string.header_need_ok), s.waiting, c.coin)
                section(ctx.getString(R.string.ui_sec_overdue), s.overdue, c.danger)
                section(ctx.getString(R.string.ui_sec_today), s.today)
                section(ctx.getString(R.string.ui_sec_later), s.later)
                section(ctx.getString(R.string.ui_sec_anytime), s.anytime)
                if (nothingOpen) item(key = "empty") { EmptyState() }
                section(ctx.getString(R.string.header_done_today), s.doneToday)
                if (s.doneWeek.isNotEmpty()) {
                    item(key = "week_toggle") {
                        FoldLine(ctx.getString(R.string.header_done_week) + " · " + s.doneWeek.size) { showDoneWeek = !showDoneWeek }
                    }
                    if (showDoneWeek) items(s.doneWeek, key = { "w" + it.id }) { t -> TaskRow(t, me, names, colorOf, onOpen = { sheet = t }) }
                }
                if (s.archived > 0) item(key = "archive") {
                    FoldLine(ctx.getString(R.string.archive_button, s.archived)) { onClassic(0) {} }
                }
            }
        }
        AddButton(Modifier.align(Alignment.BottomStart).padding(start = 20.dp, bottom = 100.dp)) {
            onClassic(0) { it.putExtra(TasksActivity.EXTRA_ADD, true) }
        }
        BottomBar(Modifier.align(Alignment.BottomCenter), parent, recording,
            onRecord = {
                if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) onToggleRecord()
                else askPermission.launch(Manifest.permission.RECORD_AUDIO)
            },
            onFamily = { onClassic(2) {} }, onBoard = { onClassic(3) {} }, onIdeas = { onClassic(4) {} })
    }

    val open = sheet
    if (open != null) {
        ModalBottomSheet(onDismissRequest = { sheet = null }, containerColor = c.bg) {
            TaskSheet(open, me, names, colorOf,
                onAction = { action, until -> TaskReceiver.apply(ctx, open.id, action, until); sheet = null },
                onMore = { sheet = null; onClassic(0) { it.putExtra(TasksActivity.EXTRA_OPEN, open.id) } })
        }
    }
}

/** A stable colour per family member, in the PC's order. */
private fun personColors(ids: List<String>): Map<String, Color> =
    ids.mapIndexed { i, id -> id to PersonColors[i % PersonColors.size] }.toMap()

@Composable
private fun Header(cache: TaskCache, myColor: Color, onClassic: (Int, (Intent) -> Unit) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val name = cache.myName()
    val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    val greet = stringResource(
        when (hour) { in 5..11 -> R.string.ui_good_morning; in 12..16 -> R.string.ui_good_afternoon; else -> R.string.ui_good_evening },
        name.ifEmpty { "" }).trimEnd(',', ' ')
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(TaskFormat.syncedAgo(ctx, cache.syncedAt()), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            Text(greet, color = c.ink, fontSize = 26.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        }
        Box {
            Avatar(name.take(1), myColor, 44.dp, Modifier.clickable(role = Role.Button) { menu = true }
                .semantics { contentDescription = ctx.getString(R.string.ui_menu_look) })
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text(stringResource(R.string.ui_menu_look)) },
                    onClick = { menu = false; ctx.startActivity(Intent(ctx, LookActivity::class.java)) })
                DropdownMenuItem(text = { Text(stringResource(R.string.menu_memos)) },
                    onClick = { menu = false; ctx.startActivity(Intent(ctx, MemosActivity::class.java)) })
                DropdownMenuItem(text = { Text(stringResource(R.string.menu_settings)) },
                    onClick = { menu = false; ctx.startActivity(Intent(ctx, MainActivity::class.java)) })
                DropdownMenuItem(text = { Text(stringResource(R.string.ui_menu_classic)) }, onClick = {
                    menu = false
                    LookPrefs.setNewUi(ctx, false)
                    onClassic(0) {}
                    (ctx as? HomeActivity)?.finish()
                })
            }
        }
    }
}

@Composable
fun Avatar(letter: String, color: Color, size: androidx.compose.ui.unit.Dp, modifier: Modifier = Modifier) {
    val jar = LocalJar.current
    Box(modifier.size(size).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
        Text(letter, color = Color.White, fontSize = (size.value * 0.4f).sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

@Composable
private fun FilterChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Box(
        Modifier.heightIn(min = 36.dp).clip(shape)
            .background(if (selected) c.ink else c.surface)
            .border(if (selected) 0.dp else 1.dp, c.line, shape)
            .clickable(role = Role.Tab, onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (selected) c.bg else c.ink, fontSize = 14.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
    }
}

@Composable
private fun SectionTitle(title: String, tone: Color) {
    val jar = LocalJar.current
    Text(title, color = tone, fontSize = if (jar.style == JarStyle.PLAYFUL) 18.sp else 14.sp,
        fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.Bold else FontWeight.SemiBold,
        fontFamily = jar.display, modifier = Modifier.padding(start = 4.dp, top = 6.dp))
}

@Composable
private fun FoldLine(label: String, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(14.dp)
    Box(Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(shape).border(1.dp, c.line, shape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center) {
        Text(label, color = c.muted, fontSize = 14.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
    }
}

@Composable
private fun JarHeard(memo: JSONObject, onOpen: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val done = memo.optString("status") == "done"
    val acts = memo.optJSONArray("actions")
    val result = if (done && acts != null && acts.length() > 0) acts.optString(0) else stringResource(R.string.ui_jar_working)
    val shape = RoundedCornerShape(jar.shape.card)
    Column(
        Modifier.fillMaxWidth().clip(shape).background(c.accentSoft).clickable(onClick = onOpen).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.size(34.dp).clip(CircleShape).background(c.accent), contentAlignment = Alignment.Center) {
                Icon(JarIcons.Mic, null, tint = c.onAccent, modifier = Modifier.size(18.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.ui_jar_heard, TaskFormat.memoTime(memo.optString("recorded_at"))),
                    color = c.onAccentSoft, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                Text("״" + memo.optString("transcript") + "״", color = c.ink, fontSize = 15.sp, fontFamily = jar.font,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.surface).padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(result, color = c.ink, fontSize = 14.sp, fontFamily = jar.font, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun EmptyState() {
    val jar = LocalJar.current
    val c = jar.colors
    Column(Modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(120.dp).clip(CircleShape).background(c.accentSoft), contentAlignment = Alignment.Center) {
            Icon(JarIcons.Check, null, tint = c.accent, modifier = Modifier.size(56.dp))
        }
        Text(stringResource(R.string.ui_empty), color = c.ink, fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        Text(stringResource(R.string.ui_empty_sub), color = c.muted, fontSize = 15.sp, fontFamily = jar.font,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

// ---------------------------------------------------------------- a task

/** One task. Swipe toward the reading direction's end to finish it, the other way to snooze an hour; tap for its sheet. */
@Composable
private fun TaskRow(t: Task, me: String, names: Map<String, String>, colorOf: Map<String, Color>, onOpen: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val drag = remember(t.id) { Animatable(0f) }
    val finished = TaskLists.doneBucket(t, null, System.currentTimeMillis()) != TaskLists.OPEN
    val open = t.openFor(me)
    val threshold = 160f
    Box(Modifier.fillMaxWidth()) {
        if (abs(drag.value) > 8f) {
            val done = drag.value > 0
            Box(Modifier.matchParentSize().clip(RoundedCornerShape(jar.shape.card)).background(if (done) c.accent else c.coinSoft)
                .padding(horizontal = 20.dp), contentAlignment = if (done) Alignment.CenterStart else Alignment.CenterEnd) {
                Icon(if (done) JarIcons.Check else JarIcons.Clock, null, tint = if (done) c.onAccent else c.coin, modifier = Modifier.size(24.dp))
            }
        }
        Box(
            Modifier.offset { IntOffset(drag.value.roundToInt(), 0) }
                .pointerInputIf(open) {
                    detectHorizontalDragGestures(
                        onDragEnd = {
                            val v = drag.value
                            scope.launch {
                                if (v > threshold) TaskReceiver.apply(ctx, t.id, "done", null)
                                else if (v < -threshold) TaskReceiver.apply(ctx, t.id, "snooze",
                                    TaskLists.inAnHour(System.currentTimeMillis(), TimeZone.getDefault()))
                                drag.animateTo(0f)
                            }
                        },
                        onHorizontalDrag = { change, amount ->
                            change.consume()
                            scope.launch { drag.snapTo(drag.value + amount) }
                        },
                    )
                },
        ) {
            when (jar.style) {
                JarStyle.NIGHT -> NightRow(t, me, names, colorOf, finished, onOpen)
                else -> CardRow(t, me, names, colorOf, finished, onOpen)
            }
        }
    }
}

private fun Modifier.pointerInputIf(on: Boolean, block: suspend PointerInputScope.() -> Unit): Modifier =
    if (on) this.pointerInput(Unit, block) else this

/** Calm and Playful: a card with a tick circle, the title, chips and the coins. */
@Composable
private fun CardRow(t: Task, me: String, names: Map<String, String>, colorOf: Map<String, Color>, finished: Boolean, onOpen: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(jar.shape.card)
    Box(Modifier.fillMaxWidth()) {
        if (playful && !finished) Box(Modifier.matchParentSize().offset(4.dp, 4.dp).clip(shape).background(c.ink))
        Row(
            Modifier.fillMaxWidth().clip(shape)
                .background(if (finished && playful) c.accentSoft else c.surface)
                .then(if (jar.shape.outline > 0.dp) Modifier.border(jar.shape.outline, jar.shape.outlineColor, shape) else Modifier)
                .clickable(onClick = onOpen).padding(14.dp)
                .alpha(if (finished && !playful) 0.6f else 1f),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            TickCircle(t, me, finished, if (playful) 36.dp else 26.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title(t), color = c.ink, fontSize = if (playful) 17.sp else 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font,
                    textDecoration = if (finished) TextDecoration.LineThrough else null)
                Chips(t, me, names, colorOf)
            }
            if (t.coins > 0 && !t.isMessage) {
                Text(if (playful) "+" + t.coins else ctx.getString(R.string.ui_coins, t.coins), color = c.coin,
                    fontSize = if (playful) 18.sp else 13.sp, fontWeight = if (playful) FontWeight.ExtraBold else FontWeight.SemiBold,
                    fontFamily = jar.display)
            }
        }
    }
}

/** Night: a time column with a line, and an outlined card. */
@Composable
private fun NightRow(t: Task, me: String, names: Map<String, String>, colorOf: Map<String, Color>, finished: Boolean, onOpen: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val overdue = TaskFormat.overdue(t)
    val time = when {
        overdue && t.dueDay() != TaskLists.day(System.currentTimeMillis(), TimeZone.getDefault()) -> TaskFormat.`when`(ctx, t.due)
        t.due != null && t.dueHasTime() -> t.due.substring(11, 16)
        else -> ""
    }
    val shape = RoundedCornerShape(jar.shape.card)
    Row(Modifier.fillMaxWidth().alpha(if (finished) 0.55f else 1f), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.width(48.dp).padding(top = 14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(time, color = if (overdue) c.danger else c.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font,
                maxLines = 2)
        }
        Row(
            Modifier.weight(1f).clip(shape).background(c.surface).border(1.dp, if (overdue) c.dangerSoft else c.line, shape)
                .clickable(onClick = onOpen).padding(14.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(title(t), color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font,
                    textDecoration = if (finished) TextDecoration.LineThrough else null)
                if (t.eachMust() && t.isOpen) {
                    val frac = t.doneParts.size.toFloat() / maxOf(1, t.owners().size)
                    Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.surface2)) {
                        Box(Modifier.fillMaxWidth(frac).height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.accent))
                    }
                }
                Chips(t, me, names, colorOf)
            }
            TickCircle(t, me, finished, 26.dp)
        }
    }
}

private fun title(t: Task): String = t.title

/** The round tick: tap to finish (or bring back) without opening the sheet. */
@Composable
private fun TickCircle(t: Task, me: String, finished: Boolean, size: androidx.compose.ui.unit.Dp) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val playful = jar.style == JarStyle.PLAYFUL
    val ring = when { playful -> c.ink; TaskFormat.overdue(t) -> c.danger; else -> c.accent }
    val ticked = finished || t.doneFor(me)
    val enabled = t.isOpen || t.isDone
    val label = ctx.getString(if (ticked) R.string.action_reopen else R.string.action_done)
    Box(
        Modifier.size(size + 12.dp).clip(CircleShape)
            .clickable(enabled = enabled, role = Role.Checkbox) { TaskReceiver.apply(ctx, t.id, if (ticked) "reopen" else "done", null) }
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.size(size).clip(CircleShape).background(if (ticked) (if (playful) c.ink else c.accent) else Color.Transparent)
                .border(if (playful) 3.dp else 2.dp, if (ticked) Color.Transparent else ring, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (ticked) Icon(JarIcons.Check, null, tint = if (playful) c.bg else c.onAccent, modifier = Modifier.size(size * 0.6f))
        }
    }
}

/** Up to three small chips: when, who (as a face), and repeat / area / turns. */
@Composable
private fun Chips(t: Task, me: String, names: Map<String, String>, colorOf: Map<String, Color>) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        if (t.due != null && jar.style != JarStyle.NIGHT) {
            val overdue = TaskFormat.overdue(t)
            Chip(TaskFormat.`when`(ctx, t.due), if (overdue) c.dangerSoft else c.surface2, if (overdue) c.danger else c.ink)
        }
        val others = t.owners().filter { it != me }
        if (t.isShared && t.eachMust() && t.isOpen) {
            Chip(ctx.getString(R.string.meta_parts, t.doneParts.size, t.owners().size), c.surface2, c.ink)
        } else if (!t.isFor(me) && others.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                for (id in others.take(3)) Avatar(TaskLists.name(names, id).take(1), colorOf[id] ?: c.muted, 22.dp)
            }
        } else if (me != t.createdBy && t.createdBy.isNotEmpty() && t.isFor(me)) {
            Chip(ctx.getString(R.string.ui_from, TaskLists.name(names, t.createdBy)), c.surface2, c.ink)
        }
        if (t.isRecurring && t.repeat.isNotEmpty()) Chip(t.repeat, c.surface2, c.ink)
        else TaskFormat.area(ctx, t.area)?.let { Chip(it.label(), c.surface2, c.ink) }
    }
}

@Composable
private fun Chip(text: String, bg: Color, fg: Color) {
    val jar = LocalJar.current
    Text(text, color = fg, fontSize = 12.sp, fontFamily = jar.font, maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(bg).padding(horizontal = 8.dp, vertical = 3.dp))
}

// ---------------------------------------------------------------- the sheet

@Composable
private fun TaskSheet(
    t: Task, me: String, names: Map<String, String>, colorOf: Map<String, Color>,
    onAction: (String, String?) -> Unit, onMore: () -> Unit,
) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val now = System.currentTimeMillis()
    val tz = TimeZone.getDefault()
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(t.title, color = c.ink, fontSize = 24.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
            Chips(t, me, names, colorOf)
            if (t.notes.isNotEmpty()) Text(t.notes, color = c.muted, fontSize = 15.sp, fontFamily = jar.font)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (t.openFor(me)) {
                BigAction(JarIcons.Check, ctx.getString(R.string.action_done), primary = true, Modifier.weight(1f)) { onAction("done", null) }
                BigAction(JarIcons.Clock, ctx.getString(R.string.ui_action_later), primary = false, Modifier.weight(1f)) {
                    onAction("snooze", TaskLists.inAnHour(now, tz))
                }
            } else if (t.isDone || t.doneFor(me)) {
                BigAction(JarIcons.Undo, ctx.getString(R.string.action_reopen), primary = true, Modifier.weight(1f)) { onAction("reopen", null) }
            }
            BigAction(JarIcons.More, ctx.getString(R.string.ui_open_in_classic), primary = false, Modifier.weight(1f), onMore)
        }
        if (t.openFor(me)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SheetChip(ctx.getString(R.string.snooze_hour)) { onAction("snooze", TaskLists.inAnHour(now, tz)) }
                TaskLists.tonight(now, tz)?.let { tonight -> SheetChip(ctx.getString(R.string.snooze_tonight)) { onAction("snooze", tonight) } }
                SheetChip(ctx.getString(R.string.snooze_tomorrow)) { onAction("snooze", TaskLists.tomorrowMorning(now, tz)) }
            }
        }
        Spacer(Modifier.height(4.dp))
    }
}

@Composable
private fun BigAction(icon: ImageVector, label: String, primary: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(20.dp)
    Column(
        modifier.height(76.dp).clip(shape).background(if (primary) c.accent else c.surface)
            .then(if (!primary) Modifier.border(1.dp, c.line, shape) else Modifier)
            .clickable(role = Role.Button, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(icon, null, tint = if (primary) c.onAccent else c.ink, modifier = Modifier.size(22.dp))
        Spacer(Modifier.height(6.dp))
        Text(label, color = if (primary) c.onAccent else c.ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun SheetChip(label: String, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Text(label, color = c.ink, fontSize = 13.sp, fontFamily = jar.font, maxLines = 1,
        modifier = Modifier.clip(shape).border(1.dp, c.line, shape).clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 9.dp))
}

// ---------------------------------------------------------------- bottom bar

@Composable
private fun AddButton(modifier: Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Row(
        modifier.height(52.dp).clip(shape).background(c.surface)
            .border(if (jar.style == JarStyle.PLAYFUL) 2.dp else 1.dp, if (jar.style == JarStyle.PLAYFUL) c.ink else c.line, shape)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(JarIcons.Plus, null, tint = c.ink, modifier = Modifier.size(20.dp))
        Text(stringResource(R.string.ui_new_task), color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

@Composable
private fun BottomBar(
    modifier: Modifier, parent: Boolean, recording: Boolean,
    onRecord: () -> Unit, onFamily: () -> Unit, onBoard: () -> Unit, onIdeas: () -> Unit,
) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val barBg = if (playful) c.ink else c.surface
    val fg = if (playful) c.bg else c.muted
    val shape = if (playful) RoundedCornerShape(26.dp) else RoundedCornerShape(topStart = 0.dp, topEnd = 0.dp)
    Box(modifier.fillMaxWidth().padding(if (playful) 14.dp else 0.dp), contentAlignment = Alignment.BottomCenter) {
        Row(
            Modifier.fillMaxWidth().height(76.dp).clip(shape).background(barBg)
                .then(if (!playful) Modifier.border(1.dp, c.line, shape) else Modifier),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceAround,
        ) {
            NavItem(JarIcons.Tasks, stringResource(R.string.ui_nav_tasks), selected = true, fg) {}
            if (parent) NavItem(JarIcons.Family, stringResource(R.string.ui_nav_family), selected = false, fg, onFamily)
            Spacer(Modifier.width(72.dp))
            NavItem(JarIcons.Trophy, stringResource(R.string.ui_nav_board), selected = false, fg, onBoard)
            NavItem(JarIcons.Idea, stringResource(R.string.ui_nav_ideas), selected = false, fg, onIdeas)
        }
        val ctx = LocalContext.current
        val label = ctx.getString(if (recording) R.string.ui_nav_stop else R.string.ui_nav_record)
        val recBg = if (recording) Color(0xFFC2402E) else c.record
        Box(
            Modifier.padding(bottom = 30.dp).size(68.dp).clip(CircleShape).background(recBg)
                .then(if (playful) Modifier.border(3.dp, c.bg, CircleShape) else Modifier)
                .clickable(role = Role.Button, onClick = onRecord).semantics { contentDescription = label }.testTag("record"),
            contentAlignment = Alignment.Center,
        ) {
            Icon(if (recording) JarIcons.Stop else JarIcons.Mic, null, tint = if (recording) Color.White else c.onRecord,
                modifier = Modifier.size(28.dp))
        }
    }
}

@Composable
private fun NavItem(icon: ImageVector, label: String, selected: Boolean, fg: Color, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val tint = when { selected && playful -> c.ink; selected -> c.onAccentSoft; else -> fg }
    Column(
        Modifier.clip(RoundedCornerShape(16.dp)).clickable(role = Role.Tab, onClick = onClick).padding(horizontal = 6.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.width(52.dp).height(30.dp).clip(RoundedCornerShape(15.dp))
            .background(if (selected) (if (playful) c.accent else c.accentSoft) else Color.Transparent),
            contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = tint, modifier = Modifier.size(20.dp))
        }
        Text(label, color = if (selected && playful) c.bg else tint, fontSize = 12.sp, fontFamily = jar.font,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}
