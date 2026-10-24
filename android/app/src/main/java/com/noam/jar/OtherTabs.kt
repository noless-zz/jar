package com.noam.jar

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Board
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists

@Composable
fun TabTitle(title: String, sub: String? = null) {
    val jar = LocalJar.current
    val c = jar.colors
    Column(Modifier.fillMaxWidth().padding(start = 22.dp, end = 20.dp, top = 22.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, color = c.ink, fontSize = if (jar.style == JarStyle.NIGHT) 32.sp else 26.sp,
            fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.ExtraBold else FontWeight.Bold, fontFamily = jar.display)
        if (sub != null) Text(sub, color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
    }
}

/** The surface a block sits on: soft in Calm, outlined in Night, ink-outlined with a shadow in Playful. */
@Composable
fun Block(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(jar.shape.card)
    Box(modifier) {
        if (jar.style == JarStyle.PLAYFUL) Box(Modifier.matchParentSize().offset(4.dp, 4.dp).clip(shape).background(c.ink))
        Box(Modifier.fillMaxWidth().clip(shape).background(c.surface)
            .then(when (jar.style) {
                JarStyle.PLAYFUL -> Modifier.border(2.dp, c.ink, shape)
                JarStyle.NIGHT -> Modifier.border(1.dp, c.line, shape)
                JarStyle.CALM -> Modifier
            })) { content() }
    }
}

// ---------------------------------------------------------------- family

/** Parents: each child's tasks, with how much of today is done. */
@Composable
fun FamilyTab(data: HomeData, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    // Every child's tasks, also the ones I gave them (the classic "Family" tab left those under "I asked").
    val byKid = remember(data) {
        data.all.filter { !it.isIdea && !it.isMessage && it.status != "declined" }
            .flatMap { t -> t.owners().filter { it != data.me && it !in data.parents }.map { it to t } }
            .groupBy({ it.first }, { it.second })
    }
    val now = System.currentTimeMillis()
    LazyColumn(Modifier.fillMaxSize().testTag("family"), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 110.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { TabTitle(stringResource(R.string.ui_family_title)) }
        if (byKid.isEmpty()) item { Text(stringResource(R.string.ui_family_none), color = c.muted, fontSize = 15.sp, fontFamily = jar.font,
            modifier = Modifier.padding(16.dp)) }
        for ((kid, tasks) in byKid) {
            val open = tasks.filter { TaskLists.doneBucket(it, null, now) == TaskLists.OPEN }
            val doneToday = tasks.filter { TaskLists.doneBucket(it, null, now) == TaskLists.DONE_TODAY }
            val total = open.size + doneToday.size
            item(key = "kid_$kid") {
                Block {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            val frac = if (total == 0) 0f else doneToday.size.toFloat() / total
                            Box(Modifier.size(52.dp).clip(CircleShape).background(Brush.sweepGradient(
                                0f to c.accent, frac to c.accent, frac to c.line, 1f to c.line)), contentAlignment = Alignment.Center) {
                                Box(Modifier.size(44.dp).clip(CircleShape).background(c.surface), contentAlignment = Alignment.Center) {
                                    Avatar(TaskLists.name(data.names, kid).take(1), data.color(kid), 38.dp)
                                }
                            }
                            Column(Modifier.weight(1f)) {
                                Text(TaskLists.name(data.names, kid), color = c.ink, fontSize = 17.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                                Text(ctx.getString(R.string.ui_family_today, doneToday.size, total), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
                            }
                        }
                        for (t in (open + doneToday).take(6)) {
                            HorizontalDivider(color = c.line)
                            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable { onOpen(t) }.padding(vertical = 4.dp),
                                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                val done = doneToday.contains(t)
                                Box(Modifier.size(18.dp).clip(CircleShape).then(if (done) Modifier.background(c.accent) else Modifier.border(2.dp, c.muted, CircleShape)))
                                Text(t.title, color = if (done) c.muted else c.ink, fontSize = 15.sp, fontFamily = jar.font, modifier = Modifier.weight(1f),
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                                if (t.due != null) Text(TaskFormat.`when`(ctx, t.due), color = c.muted, fontSize = 12.sp, fontFamily = jar.font)
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- the coin board

/** Calm: your week, then a ranked list with bars. Night: a glowing bar chart and stat cards. Playful: a podium. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BoardTab(data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val b = data.board
    var ledger by remember { mutableStateOf<Board.Person?>(null) }
    var lesson by remember { mutableStateOf(false) }
    val people = b.people
    val me = people.firstOrNull { it.id == data.me }
    val rank = people.indexOfFirst { it.id == data.me } + 1
    LazyColumn(Modifier.fillMaxSize().testTag("board"), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 110.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            val sub = if (b.weekStart.isNotEmpty()) ctx.getString(R.string.board_week, TaskFormat.shortDay(b.weekStart), TaskFormat.shortDay(b.weekEnd)) else null
            if (jar.style == JarStyle.NIGHT && people.isNotEmpty() && people[0].week > 0)
                TabTitle(ctx.getString(R.string.ui_leader, people[0].name), sub)
            else TabTitle(stringResource(R.string.ui_board_title), sub)
        }
        if (people.isEmpty()) {
            item { Text(stringResource(R.string.board_empty), color = c.muted, fontSize = 15.sp, fontFamily = jar.font, modifier = Modifier.padding(16.dp)) }
        } else when (jar.style) {
            JarStyle.PLAYFUL -> item { Podium(people, data) { ledger = it } }
            JarStyle.NIGHT -> item { NightChart(people, data) }
            JarStyle.CALM -> if (me != null) item {
                Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(jar.shape.card)).background(c.accent).padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(R.string.ui_your_week), color = c.onAccent.copy(alpha = 0.8f), fontSize = 13.sp, fontFamily = jar.font)
                            Text(ctx.getString(R.string.ui_coins, me.week), color = c.onAccent, fontSize = 28.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.display)
                            Text(ctx.getString(R.string.ui_place, rank), color = c.onAccent.copy(alpha = 0.8f), fontSize = 13.sp, fontFamily = jar.font)
                        }
                    }
                }
            }
        }
        if (people.isNotEmpty()) item {
            Block {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                    val max = maxOf(1, people.maxOf { it.week })
                    people.forEachIndexed { i, p ->
                        if (i > 0) HorizontalDivider(color = c.line)
                        Row(Modifier.fillMaxWidth().clickable { ledger = p }.padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text("${i + 1}", color = c.muted, fontSize = 15.sp, fontWeight = FontWeight.Bold, fontFamily = jar.font, modifier = Modifier.width(18.dp))
                            Avatar(p.name.take(1), data.color(p.id), 38.dp)
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Row { Text(p.name, color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font, modifier = Modifier.weight(1f))
                                    Text("${p.week}", color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.Bold, fontFamily = jar.font) }
                                Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(c.surface2)) {
                                    Box(Modifier.fillMaxWidth(p.week.toFloat() / max).height(8.dp).clip(RoundedCornerShape(4.dp))
                                        .background(if (i == 0) c.coin else c.accent))
                                }
                                val sub = buildList {
                                    add(ctx.resources.getQuantityString(R.plurals.board_tasks, p.tasksWeek, p.tasksWeek))
                                    if (p.streak >= 2) add(ctx.getString(R.string.board_streak, p.streak))
                                }.joinToString(" · ")
                                Text(sub, color = c.muted, fontSize = 12.sp, fontFamily = jar.font)
                            }
                        }
                    }
                }
            }
        }
        item {
            val parent = data.parent
            ActionPill(if (parent) stringResource(R.string.ui_work_day) else stringResource(R.string.ui_learned)) {
                if (parent) logWorkDay(actions, ctx) else lesson = true
            }
        }
        if (b.lessons.isNotEmpty()) {
            item { SectionTitle(stringResource(R.string.board_lessons), c.muted) }
            items(b.lessons) { l ->
                Block { Column(Modifier.padding(14.dp)) {
                    Text(if (l.title.isEmpty()) l.name else l.name + " · " + l.title, color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                    if (l.note.isNotEmpty()) Text(l.note, color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
                } }
            }
        }
    }
    val p = ledger
    if (p != null) {
        ModalBottomSheet(onDismissRequest = { ledger = null }, containerColor = c.bg) { Ledger(p, b, data) }
    }
    if (lesson) ModalBottomSheet(onDismissRequest = { lesson = false }, containerColor = c.bg) { LessonSheet { lesson = false } }
}

@Composable
fun ActionPill(label: String, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(if (playful) 18.dp else 26.dp)
    Box(Modifier.fillMaxWidth().height(54.dp).clip(shape).background(if (playful) c.accent else c.surface)
        .border(if (playful) 2.dp else 1.dp, if (playful) c.ink else c.line, shape).clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center) {
        Text(label, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.display)
    }
}

@Composable
private fun Podium(people: List<Board.Person>, data: HomeData, onPick: (Board.Person) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val top = people.take(3)
    val order = listOfNotNull(top.getOrNull(1), top.getOrNull(0), top.getOrNull(2))
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.Bottom) {
        for (p in order) {
            val place = people.indexOf(p) + 1
            val h = when (place) { 1 -> 132.dp; 2 -> 96.dp; else -> 72.dp }
            Column(Modifier.width(96.dp).clickable { onPick(p) }, horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.size(if (place == 1) 60.dp else 52.dp).clip(CircleShape).background(data.color(p.id)).border(3.dp, c.ink, CircleShape),
                    contentAlignment = Alignment.Center) {
                    Text(p.name.take(1), color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                }
                Column(Modifier.fillMaxWidth().height(h).clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp))
                    .background(if (place == 1) c.accent else c.surface2).border(2.dp, c.ink, RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp)),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                    Text("$place", color = c.ink, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.display)
                    Text("${p.week}", color = c.ink, fontSize = 14.sp, fontFamily = jar.font)
                }
            }
        }
    }
}

@Composable
private fun NightChart(people: List<Board.Person>, data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val max = maxOf(1, people.maxOf { it.week })
    Box(Modifier.fillMaxWidth().height(240.dp).clip(RoundedCornerShape(22.dp)).background(c.surface).border(1.dp, c.line, RoundedCornerShape(22.dp))
        .padding(16.dp)) {
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.SpaceAround, verticalAlignment = Alignment.Bottom) {
            people.take(5).forEachIndexed { i, p ->
                Column(Modifier.weight(1f).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Bottom) {
                    Text("${p.week}", color = c.ink, fontSize = 15.sp, fontWeight = FontWeight.Bold, fontFamily = jar.font)
                    Box(Modifier.padding(horizontal = 8.dp, vertical = 8.dp).fillMaxWidth().height((130f * p.week / max).dp + 4.dp)
                        .then(if (i == 0) Modifier.shadow(16.dp, RoundedCornerShape(12.dp), ambientColor = c.accent, spotColor = c.accent) else Modifier)
                        .clip(RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp, bottomStart = 4.dp, bottomEnd = 4.dp))
                        .background(if (i == 0) Brush.verticalGradient(listOf(c.accent.copy(alpha = 0.6f), c.accent)) else Brush.verticalGradient(listOf(c.line, c.line))))
                    Avatar(p.name.take(1), data.color(p.id), 28.dp)
                }
            }
        }
    }
}

@Composable
private fun Ledger(p: Board.Person, b: Board, data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val lines = b.ledgers[p.id].orEmpty()
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Avatar(p.name.take(1), data.color(p.id), 44.dp)
            Column {
                Text(ctx.getString(R.string.ui_ledger_title, p.name), color = c.ink, fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                Text(ctx.getString(R.string.ui_week_coins, p.week) + " · " + ctx.getString(R.string.ui_all_time, p.allTime), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            }
        }
        for (l in lines.take(12)) {
            Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(l.title ?: "·", color = if (l.reversed) c.muted else c.ink, fontSize = 15.sp, fontFamily = jar.font, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(TaskFormat.memoTime(l.at), color = c.muted, fontSize = 12.sp, fontFamily = jar.font)
                }
                Text((if (l.coins >= 0) "+" else "") + l.coins, color = if (l.reversed) c.muted else c.coin, fontSize = 16.sp, fontWeight = FontWeight.Bold, fontFamily = jar.font)
            }
        }
    }
}

// ---------------------------------------------------------------- ideas

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IdeasTab(data: HomeData, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val ideas = remember(data) { TaskLists.ideas(data.all) }
    var adding by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().testTag("ideas"), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 110.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { TabTitle(stringResource(R.string.ui_ideas_title), stringResource(R.string.ui_ideas_sub)) }
        item { ActionPill(stringResource(R.string.ui_new_idea)) { adding = true } }
        items(ideas, key = { it.id }) { t ->
            val (label, bg, fg) = when {
                t.isRequested -> Triple(R.string.idea_status_new, c.coinSoft, c.coin)
                t.isOpen -> Triple(R.string.idea_status_accepted, c.accentSoft, c.onAccentSoft)
                t.isDone -> Triple(R.string.idea_status_shipped, c.accent, c.onAccent)
                else -> Triple(R.string.idea_status_declined, c.surface2, c.muted)
            }
            Block(Modifier.clickable { onOpen(t) }) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Avatar(TaskLists.name(data.names, t.createdBy).take(1), data.color(t.createdBy), 30.dp)
                        Text(t.title, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font, modifier = Modifier.weight(1f))
                        Chip(ctx.getString(label).replace(Regex("^\\P{L}+"), ""), bg, fg)
                    }
                    if (t.notes.isNotEmpty()) Text(t.notes, color = c.muted, fontSize = 14.sp, fontFamily = jar.font, maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
    if (adding) ModalBottomSheet(onDismissRequest = { adding = false }, containerColor = c.bg) { NewIdeaSheet { adding = false } }
}

// ---------------------------------------------------------------- settings

/** Settings, opened from the avatar: everyday things first, the technical ones at the bottom. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(data: HomeData, onBack: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val keep = data.keepDone
    var keepSheet by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().testTag("settings"), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Row(Modifier.padding(top = 16.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.size(44.dp).clip(CircleShape).background(c.surface).clickable(role = Role.Button, onClick = onBack), contentAlignment = Alignment.Center) {
                    Icon(JarIcons.Back, null, tint = c.ink, modifier = Modifier.size(20.dp))
                }
                Text(stringResource(R.string.ui_settings), color = c.ink, fontSize = 24.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
            }
        }
        item {
            Block { Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Avatar(data.myName.take(1), data.color(data.me), 48.dp)
                Column(Modifier.weight(1f)) {
                    Text(data.myName, color = c.ink, fontSize = 17.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                    Text(TaskFormat.syncedAgo(ctx, data.syncedAt), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
                }
            } }
        }
        item { SettingsGroup(stringResource(R.string.ui_sec_personal), listOf(
            SettingsRow(JarIcons.Palette, ctx.getString(R.string.ui_menu_look), styleName(ctx, jar.style)) { actions.open(LookActivity::class.java) },
            SettingsRow(JarIcons.Mic, ctx.getString(R.string.menu_memos), "") { actions.go(Sub.MEMOS) },
        )) }
        item { SettingsGroup(stringResource(R.string.ui_sec_family_s), buildList {
            if (data.admin) add(SettingsRow(JarIcons.Family, ctx.getString(R.string.ui_set_invite), "") { actions.classic(0) { it.putExtra(TasksActivity.EXTRA_ACTION, "invite") } })
            add(SettingsRow(JarIcons.Tasks, plain(ctx.getString(R.string.menu_areas)), "${data.areas.size}") { actions.go(Sub.AREAS) })
            add(SettingsRow(JarIcons.Repeat, plain(ctx.getString(R.string.menu_recurring)), "${data.series.size}") { actions.go(Sub.RECURRING) })
            add(SettingsRow(JarIcons.Undo, ctx.getString(R.string.ui_archive_title), "") { actions.go(Sub.ARCHIVE) })
            if (data.parent) add(SettingsRow(JarIcons.Clock, ctx.getString(R.string.menu_keep_done),
                if (keep == 0) ctx.getString(R.string.keep_forever) else ctx.resources.getQuantityString(R.plurals.keep_days, keep, keep)) {
                keepSheet = true })
        }) }
        item { SettingsGroup(stringResource(R.string.ui_sec_device), listOf(
            SettingsRow(JarIcons.Gear, ctx.getString(R.string.menu_settings), "") { actions.open(MainActivity::class.java) },
            SettingsRow(JarIcons.Undo, ctx.getString(R.string.ui_set_about), ctx.getString(R.string.ui_version, BuildConfig.VERSION_NAME)) {
                actions.classic(0) { it.putExtra(TasksActivity.EXTRA_ACTION, "update") } },
            SettingsRow(JarIcons.Chat, ctx.getString(R.string.share_app), "") { actions.classic(0) { it.putExtra(TasksActivity.EXTRA_ACTION, "share") } },
            SettingsRow(JarIcons.Back, ctx.getString(R.string.ui_menu_classic), "") { actions.backToClassic() },
        )) }
    }
    if (keepSheet) ModalBottomSheet(onDismissRequest = { keepSheet = false }, containerColor = c.bg) { KeepDoneSheet(keep) { keepSheet = false } }
}

private fun styleName(ctx: android.content.Context, s: JarStyle) = ctx.getString(when (s) {
    JarStyle.CALM -> R.string.ui_style_calm; JarStyle.NIGHT -> R.string.ui_style_night; JarStyle.PLAYFUL -> R.string.ui_style_playful
})

private class SettingsRow(val icon: ImageVector, val label: String, val value: String, val onClick: () -> Unit)

@Composable
private fun SettingsGroup(title: String, rows: List<SettingsRow>) {
    val jar = LocalJar.current
    val c = jar.colors
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, color = c.muted, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font, modifier = Modifier.padding(start = 6.dp))
        Block {
            Column {
                rows.forEachIndexed { i, r ->
                    if (i > 0) HorizontalDivider(color = c.line)
                    Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(role = Role.Button, onClick = r.onClick).padding(horizontal = 14.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Box(Modifier.size(34.dp).clip(RoundedCornerShape(10.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
                            Icon(r.icon, null, tint = c.onAccentSoft, modifier = Modifier.size(18.dp))
                        }
                        Text(r.label, color = c.ink, fontSize = 16.sp, fontFamily = jar.font, modifier = Modifier.weight(1f))
                        if (r.value.isNotEmpty()) Text(r.value, color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
                        Icon(JarIcons.Chevron, null, tint = c.muted, modifier = Modifier.size(18.dp))
                    }
                }
            }
        }
    }
}
