package com.noam.jar

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs
import kotlin.math.roundToInt

private enum class Filter { MINE, ASKED, QUESTIONS }

class Sections(
    val waiting: List<Task>, val overdue: List<Task>, val today: List<Task>, val later: List<Task>, val anytime: List<Task>,
    val doneToday: List<Task>, val doneWeek: List<Task>, val archived: Int,
) {
    val open get() = waiting.size + overdue.size + today.size + later.size + anytime.size
}

fun sectionsOf(list: List<Task>, waiting: List<Task>): Sections {
    val now = System.currentTimeMillis()
    val today = TaskLists.day(now, TimeZone.getDefault())
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

// ---------------------------------------------------------------- the tab

@Composable
fun TasksTab(data: HomeData, memo: JSONObject?, onOpen: (Task) -> Unit, onSettings: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    var filter by remember { mutableStateOf(Filter.MINE) }
    var showWeek by remember { mutableStateOf(false) }
    val me = data.me
    val mine = remember(data) { TaskLists.mine(data.all, me) }
    val asked = remember(data) { TaskLists.asked(data.all, me) }
    val questions = remember(data) { data.all.filter { it.waitingOn(me) } }
    val waiting = remember(data) { TaskLists.needMyOk(data.all, me, data.parent) }
    val list = when (filter) { Filter.MINE -> mine; Filter.ASKED -> asked; Filter.QUESTIONS -> questions }
    val s = remember(data, filter) { sectionsOf(list, if (filter == Filter.MINE) waiting else emptyList()) }
    val mineSections = remember(data) { sectionsOf(mine, waiting) }
    val recentMemo = memo?.takeIf {
        val at = TaskLists.utcMillis(it.optString("recorded_at"))
        at > 0 && System.currentTimeMillis() - at < 24 * 3600 * 1000L
    }

    Column(Modifier.fillMaxSize()) {
        when (jar.style) {
            JarStyle.NIGHT -> NightHeader(data, mineSections, questions.size, onSettings)
            JarStyle.PLAYFUL -> PlayfulHeader(data, onSettings)
            JarStyle.CALM -> CalmHeader(data, onSettings)
        }
        Row(Modifier.padding(horizontal = 20.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(stringResource(R.string.ui_filter_mine, mineSections.open), filter == Filter.MINE) { filter = Filter.MINE }
            FilterChip(stringResource(R.string.ui_filter_asked, asked.count { it.isOpen || it.isRequested }), filter == Filter.ASKED) { filter = Filter.ASKED }
            if (questions.isNotEmpty() || filter == Filter.QUESTIONS)
                FilterChip(stringResource(R.string.ui_filter_questions, questions.size), filter == Filter.QUESTIONS) { filter = Filter.QUESTIONS }
        }
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth().testTag("task_list"),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 110.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (data.update != null) item(key = "update") { UpdateBanner(data) }
            taskSection("waiting", ctx.getString(R.string.header_need_ok), s.waiting, data, onOpen, c.coin)
            taskSection("overdue", ctx.getString(R.string.ui_sec_overdue), s.overdue, data, onOpen, c.danger)
            taskSection("today", ctx.getString(R.string.ui_sec_today), s.today, data, onOpen)
            taskSection("later", ctx.getString(R.string.ui_sec_later), s.later, data, onOpen)
            taskSection("anytime", ctx.getString(R.string.ui_sec_anytime), s.anytime, data, onOpen)
            if (s.open == 0) item(key = "empty") { EmptyState() }
            taskSection("donetoday", ctx.getString(R.string.header_done_today), s.doneToday, data, onOpen)
            if (s.doneWeek.isNotEmpty()) {
                item(key = "week_toggle") { FoldLine(ctx.getString(R.string.header_done_week) + " · " + s.doneWeek.size) { showWeek = !showWeek } }
                if (showWeek) taskSection("doneweek", null, s.doneWeek, data, onOpen)
            }
            if (s.archived > 0) item(key = "archive") {
                val actions = LocalActions.current
                FoldLine(plain(ctx.getString(R.string.archive_button, s.archived))) { actions.go(Sub.ARCHIVE) }
            }
        }
    }
}

/** A section: Calm puts its rows in one card with dividers; Night and Playful give each task its own card. */
fun LazyListScope.taskSection(key: String, title: String?, tasks: List<Task>, data: HomeData, onOpen: (Task) -> Unit, tone: Color? = null) {
    if (tasks.isEmpty()) return
    if (title != null) item(key = "h_$key") { SectionTitle(title, tone ?: LocalJar.current.colors.muted) }
    item(key = "g_$key") {
        val jar = LocalJar.current
        if (jar.style == JarStyle.CALM) {
            val shape = RoundedCornerShape(jar.shape.card)
            Column(Modifier.fillMaxWidth().clip(shape).background(jar.colors.surface)) {
                tasks.forEachIndexed { i, t ->
                    if (i > 0) HorizontalDivider(color = jar.colors.line, thickness = 1.dp)
                    TaskRow(t, data, onOpen)
                }
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { for (t in tasks) TaskRow(t, data, onOpen) }
        }
    }
}

// ---------------------------------------------------------------- headers

@Composable
private fun AvatarMenu(data: HomeData, onSettings: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var menu by remember { mutableStateOf(false) }
    Box {
        Avatar(data.myName.take(1), data.color(data.me), 44.dp,
            Modifier.clip(CircleShape).clickable(role = Role.Button) { menu = true }.semantics { contentDescription = ctx.getString(R.string.ui_settings) })
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(text = { Text(stringResource(R.string.ui_settings)) }, onClick = { menu = false; onSettings() })
            DropdownMenuItem(text = { Text(stringResource(R.string.ui_menu_look)) }, onClick = { menu = false; actions.open(LookActivity::class.java) })
            DropdownMenuItem(text = { Text(stringResource(R.string.menu_shopping)) }, onClick = { menu = false; actions.open(ShoppingActivity::class.java) })
            DropdownMenuItem(text = { Text(stringResource(R.string.menu_memos)) }, onClick = { menu = false; actions.go(Sub.MEMOS) })
            DropdownMenuItem(text = { Text(stringResource(R.string.ui_menu_classic)) }, onClick = { menu = false; actions.backToClassic() })
        }
    }
}

@Composable
private fun AddButton(onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(if (jar.style == JarStyle.NIGHT) 14.dp else 18.dp)
    Row(
        Modifier.height(44.dp).clip(shape).background(c.surface)
            .border(if (playful) 2.dp else 1.dp, if (playful) c.ink else c.line, shape)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = if (jar.style == JarStyle.NIGHT) 11.dp else 14.dp)
            .testTag("add"),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(JarIcons.Plus, null, tint = c.ink, modifier = Modifier.size(20.dp))
        if (jar.style != JarStyle.NIGHT)
            Text(stringResource(R.string.ui_new_task), color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

private fun greetingRes(): Int = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
    in 5..11 -> R.string.ui_good_morning; in 12..16 -> R.string.ui_good_afternoon; else -> R.string.ui_good_evening
}

/** Calm: the date, a greeting, "+ Task" and your avatar. */
@Composable
private fun CalmHeader(data: HomeData, onSettings: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(longDate(), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            Text(stringResource(greetingRes(), data.myName), color = c.ink, fontSize = 22.sp, fontWeight = FontWeight.Bold,
                fontFamily = jar.display, maxLines = 2, lineHeight = 26.sp, overflow = TextOverflow.Ellipsis)
        }
        AddButton { actions.edit(EditReq(null)) }
        Box(Modifier.width(10.dp))
        AvatarMenu(data, onSettings)
    }
}

/** Night: no greeting; a big count for today and a one-line summary, like a dashboard. */
@Composable
private fun NightHeader(data: HomeData, s: Sections, questions: Int, onSettings: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val today = s.overdue.size + s.today.size + s.waiting.size
    val summary = buildList {
        if (s.overdue.isNotEmpty()) add(stringResource(R.string.ui_sum_overdue, s.overdue.size))
        if (questions > 0) add(stringResource(R.string.ui_sum_questions, questions))
        if (isEmpty()) add(stringResource(R.string.ui_sum_clear))
    }.joinToString(" · ")
    Row(Modifier.fillMaxWidth().padding(start = 22.dp, end = 20.dp, top = 22.dp, bottom = 6.dp), verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(shortDate(), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            Text(stringResource(R.string.ui_today_count, today), color = c.ink, fontSize = 34.sp, fontWeight = FontWeight.Bold,
                fontFamily = jar.display, modifier = Modifier.testTag("night_count"))
            Text(summary, color = if (s.overdue.isNotEmpty()) c.danger else c.muted, fontSize = 14.sp, fontFamily = jar.font)
        }
        AddButton { actions.edit(EditReq(null)) }
        Box(Modifier.width(10.dp))
        AvatarMenu(data, onSettings)
    }
}

/** Playful: a big "Hi!" and your coins for the week in a sticker. */
@Composable
private fun PlayfulHeader(data: HomeData, onSettings: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val week = data.board.people.firstOrNull { it.id == data.me }?.week ?: 0
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.ui_hi, data.myName),
            color = c.ink, fontSize = 28.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.display, modifier = Modifier.weight(1f),
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        CoinSticker(week)
        AddButton { actions.edit(EditReq(null)) }
        AvatarMenu(data, onSettings)
    }
}

@Composable
fun CoinSticker(coins: Int) {
    val jar = LocalJar.current
    val c = jar.colors
    Box {
        Box(Modifier.matchParentSize().offset(3.dp, 3.dp).clip(RoundedCornerShape(20.dp)).background(c.ink))
        Row(Modifier.height(40.dp).clip(RoundedCornerShape(20.dp)).background(c.accent).border(2.dp, c.ink, RoundedCornerShape(20.dp))
            .padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(Modifier.size(18.dp).clip(CircleShape).background(Color(0xFFF2A91B)).border(2.dp, c.ink, CircleShape))
            Text("$coins", color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        }
    }
}

fun longDate(): String = SimpleDateFormat("EEEE, d MMMM", Locale.getDefault()).format(Date())
fun shortDate(): String = SimpleDateFormat("EEE · d.M", Locale.getDefault()).format(Date())

// ---------------------------------------------------------------- shared pieces

@Composable
fun Avatar(letter: String, color: Color, size: Dp, modifier: Modifier = Modifier) {
    val jar = LocalJar.current
    Box(modifier.size(size).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
        Text(letter, color = Color.White, fontSize = (size.value * 0.4f).sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

@Composable
fun FilterChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(if (jar.style == JarStyle.NIGHT) 17.dp else 18.dp)
    val playful = jar.style == JarStyle.PLAYFUL
    Box(
        Modifier.heightIn(min = 36.dp).clip(shape).background(if (selected) c.ink else (if (jar.style == JarStyle.NIGHT) Color.Transparent else c.surface))
            .border(if (selected) 0.dp else if (playful) 2.dp else 1.dp, if (playful) c.ink else c.line, shape)
            .clickable(role = Role.Tab, onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (selected) c.bg else c.ink, fontSize = 14.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
    }
}

@Composable
fun SectionTitle(title: String, tone: Color) {
    val jar = LocalJar.current
    Text(title, color = tone, fontSize = if (jar.style == JarStyle.PLAYFUL) 18.sp else 14.sp,
        fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.Bold else FontWeight.SemiBold,
        fontFamily = jar.display, modifier = Modifier.padding(start = 4.dp, top = 6.dp))
}

@Composable
fun FoldLine(label: String, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(14.dp)
    Box(Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(shape).border(1.dp, c.line, shape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center) {
        Text(label, color = c.muted, fontSize = 14.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
    }
}

@Composable
fun Chip(text: String, bg: Color, fg: Color) {
    val jar = LocalJar.current
    Text(text, color = fg, fontSize = 12.sp, fontFamily = jar.font, maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(bg).padding(horizontal = 8.dp, vertical = 3.dp))
}

/** Calm and Playful: what Jar heard last, and what it filed. */
@Composable
private fun HeardCard(memo: JSONObject) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val shape = RoundedCornerShape(jar.shape.card)
    Column(
        Modifier.fillMaxWidth().clip(shape).background(if (jar.style == JarStyle.PLAYFUL) c.surface else c.accentSoft)
            .then(if (jar.style == JarStyle.PLAYFUL) Modifier.border(2.dp, c.ink, shape) else Modifier)
            .clickable { actions.open(MemosActivity::class.java) }.padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.size(34.dp).clip(CircleShape).background(c.accent), contentAlignment = Alignment.Center) {
                Icon(JarIcons.Mic, null, tint = c.onAccent, modifier = Modifier.size(18.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.ui_jar_heard, TaskFormat.memoTime(memo.optString("recorded_at"))),
                    color = if (jar.style == JarStyle.PLAYFUL) c.muted else c.onAccentSoft, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                Text("״" + memo.optString("transcript") + "״", color = c.ink, fontSize = 15.sp, fontFamily = jar.font, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(if (jar.style == JarStyle.PLAYFUL) c.surface2 else c.surface)
            .padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(memoResult(memo), color = c.ink, fontSize = 14.sp, fontFamily = jar.font, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Night: the same as one quiet line with a status dot. */
@Composable
private fun HeardPill(memo: JSONObject) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val shape = RoundedCornerShape(16.dp)
    Row(Modifier.fillMaxWidth().clip(shape).background(c.accentSoft).border(1.dp, c.accent.copy(alpha = 0.35f), shape)
        .clickable { actions.open(MemosActivity::class.java) }.padding(horizontal = 12.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(c.accent))
        Text("Jar · " + memoResult(memo), color = c.ink, fontSize = 14.sp, fontFamily = jar.font, maxLines = 1,
            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun memoResult(memo: JSONObject): String {
    val acts = memo.optJSONArray("actions")
    return if (memo.optString("status") == "done" && acts != null && acts.length() > 0) acts.optString(0)
    else stringResource(R.string.ui_jar_working)
}

@Composable
fun EmptyState() {
    val jar = LocalJar.current
    val c = jar.colors
    Column(Modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(120.dp).clip(CircleShape).background(c.accentSoft), contentAlignment = Alignment.Center) {
            Icon(JarIcons.Check, null, tint = c.accent, modifier = Modifier.size(56.dp))
        }
        Text(stringResource(R.string.ui_empty), color = c.ink, fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        Text(stringResource(R.string.ui_empty_sub), color = c.muted, fontSize = 15.sp, fontFamily = jar.font, textAlign = TextAlign.Center)
    }
}

// ---------------------------------------------------------------- a task row

/** One task. Swipe toward the reading direction's end to finish it, the other way to snooze an hour; tap for its sheet. */
@Composable
fun TaskRow(t: Task, data: HomeData, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val scope = rememberCoroutineScope()
    val drag = remember(t.id) { Animatable(0f) }
    val finished = TaskLists.doneBucket(t, null, System.currentTimeMillis()) != TaskLists.OPEN
    val open = t.openFor(data.me)
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
                .then(if (!open) Modifier else Modifier.pointerInput(t.id) {
                    detectHorizontalDragGestures(
                        onDragEnd = {
                            val v = drag.value
                            scope.launch {
                                if (v > 160f) actions.act(t, "done")
                                else if (v < -160f) actions.act(t, "snooze", TaskLists.inAnHour(System.currentTimeMillis(), TimeZone.getDefault()))
                                drag.animateTo(0f)
                            }
                        },
                        onHorizontalDrag = { change, amount ->
                            change.consume()
                            scope.launch { drag.snapTo(drag.value + amount) }
                        },
                    )
                }),
        ) {
            when (jar.style) {
                JarStyle.NIGHT -> NightRow(t, data, finished, onOpen)
                JarStyle.PLAYFUL -> PlayfulRow(t, data, finished, onOpen)
                JarStyle.CALM -> CalmRow(t, data, finished, onOpen)
            }
        }
    }
}

/** Calm: a plain line inside its section's card. */
@Composable
private fun CalmRow(t: Task, data: HomeData, finished: Boolean, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    Row(Modifier.fillMaxWidth().background(c.surface).clickable { onOpen(t) }.padding(horizontal = 14.dp, vertical = 12.dp)
        .alpha(if (finished) 0.6f else 1f),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        TickCircle(t, data.me, finished, 24.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(t.title, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font,
                textDecoration = if (finished) TextDecoration.LineThrough else null)
            Chips(t, data)
        }
        if (t.coins > 0 && !t.isMessage)
            Text(ctx.getString(R.string.ui_coins, t.coins), color = c.coin, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

/** Playful: a chunky outlined card with an offset shadow, a big tick and "+coins". */
@Composable
private fun PlayfulRow(t: Task, data: HomeData, finished: Boolean, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(jar.shape.card)
    Box(Modifier.fillMaxWidth()) {
        if (!finished) Box(Modifier.matchParentSize().offset(4.dp, 4.dp).clip(shape).background(c.ink))
        Row(Modifier.fillMaxWidth().clip(shape).background(if (finished) c.accentSoft else c.surface).border(2.dp, c.ink, shape)
            .clickable { onOpen(t) }.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            TickCircle(t, data.me, finished, 36.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(t.title, color = c.ink, fontSize = 17.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font,
                    textDecoration = if (finished) TextDecoration.LineThrough else null)
                Chips(t, data)
            }
            if (t.coins > 0 && !t.isMessage)
                Text("+" + t.coins, color = c.coin, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.display)
        }
    }
}

/** Night: a time column with a line, and an outlined card with the tick on the far side. */
@Composable
private fun NightRow(t: Task, data: HomeData, finished: Boolean, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val overdue = TaskFormat.overdue(t)
    val time = when {
        overdue && t.dueDay() != TaskLists.day(System.currentTimeMillis(), TimeZone.getDefault()) -> TaskFormat.`when`(ctx, t.due)
        t.due != null && t.dueHasTime() -> t.due.substring(11, 16)
        t.due != null -> TaskFormat.`when`(ctx, t.due)
        else -> "·"
    }
    val shape = RoundedCornerShape(jar.shape.card)
    Row(Modifier.fillMaxWidth().alpha(if (finished) 0.5f else 1f).heightIn(min = 64.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.width(50.dp).padding(top = 14.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(time, color = if (overdue) c.danger else c.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font,
                maxLines = 2, textAlign = TextAlign.Center)
            Box(Modifier.width(2.dp).height(24.dp).background(c.line))
        }
        Row(Modifier.weight(1f).clip(shape).background(c.surface).border(1.dp, if (overdue) c.danger.copy(alpha = 0.45f) else c.line, shape)
            .clickable { onOpen(t) }.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(t.title, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font,
                    textDecoration = if (finished) TextDecoration.LineThrough else null)
                if (t.eachMust() && t.isOpen) {
                    val frac = t.doneParts.size.toFloat() / maxOf(1, t.owners().size)
                    Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.surface2)) {
                        Box(Modifier.fillMaxWidth(frac).height(6.dp).clip(RoundedCornerShape(3.dp)).background(c.accent))
                    }
                }
                Chips(t, data)
            }
            TickCircle(t, data.me, finished, 26.dp)
        }
    }
}

/** The round tick: tap to finish (or bring back) without opening the sheet. */
@Composable
fun TickCircle(t: Task, me: String, finished: Boolean, size: Dp) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val playful = jar.style == JarStyle.PLAYFUL
    val ring = when { playful -> c.ink; TaskFormat.overdue(t) -> c.danger; else -> c.accent }
    val ticked = finished || t.doneFor(me)
    val label = ctx.getString(if (ticked) R.string.action_reopen else R.string.action_done)
    Box(
        Modifier.size(size + 12.dp).clip(CircleShape)
            .clickable(enabled = t.isOpen || t.isDone, role = Role.Checkbox) { actions.act(t, if (ticked) "reopen" else "done") }
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(size).clip(CircleShape).background(if (ticked) (if (playful) c.ink else c.accent) else Color.Transparent)
            .border(if (playful) 3.dp else 2.dp, if (ticked) Color.Transparent else ring, CircleShape), contentAlignment = Alignment.Center) {
            if (ticked) Icon(JarIcons.Check, null, tint = if (playful) c.bg else c.onAccent, modifier = Modifier.size(size * 0.6f))
        }
    }
}

/** Up to three small chips: when, who (as faces), and repeat / area / turns / coins. */
@Composable
fun Chips(t: Task, data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val me = data.me
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
                for (id in others.take(3)) Avatar(TaskLists.name(data.names, id).take(1), data.color(id), 22.dp)
            }
        } else if (me != t.createdBy && t.createdBy.isNotEmpty() && t.isFor(me)) {
            Chip(ctx.getString(R.string.ui_from, TaskLists.name(data.names, t.createdBy)), c.surface2, c.ink)
        }
        if (jar.style == JarStyle.NIGHT && t.coins > 0 && !t.isMessage) Chip(ctx.getString(R.string.ui_coins, t.coins), c.coinSoft, c.coin)
        if (t.isRecurring && t.repeat.isNotEmpty()) Chip(t.repeat, c.surface2, c.ink)
        else TaskFormat.area(ctx, t.area)?.let { Chip(it.label(), c.surface2, c.ink) }
    }
}
