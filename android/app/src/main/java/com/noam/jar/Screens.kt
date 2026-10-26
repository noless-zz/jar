package com.noam.jar

import androidx.annotation.VisibleForTesting
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Area
import com.noam.jar.core.Series
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale

// ---------------------------------------------------------------- recurring tasks

/** Every recurring task I can see: its rule in words, who, whose turn, paused. Tap to pause, resume or stop. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecurringScreen(data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var open by remember { mutableStateOf<Series?>(null) }
    SubScreen(plain(stringResource(R.string.menu_recurring)), "recurring", stringResource(R.string.ui_recurring_sub)) {
        item(key = "new") { ActionPill(stringResource(R.string.ui_new_recurring)) { actions.edit(EditReq(null, repeat = true)) } }
        if (data.series.isEmpty()) item(key = "none") { Muted(stringResource(R.string.recurring_none), Modifier.padding(8.dp)) }
        rows("series", data.series, { it.id }) { s ->
            Row(Modifier.fillMaxWidth().heightIn(min = 64.dp).clickable {
                if (data.mayChange(s)) { open = s } else { actions.toast(ctx.getString(R.string.recurring_not_yours)) }
            }.padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                when (jar.style) {
                    // Night: the time sits in its own column, like the timeline on the task list.
                    JarStyle.NIGHT -> Text(s.time.ifEmpty { "··" }, color = if (s.isPaused) c.muted else c.accent, fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold, fontFamily = jar.font, modifier = Modifier.width(48.dp))
                    JarStyle.PLAYFUL -> Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(c.accent).border(2.dp, c.ink, RoundedCornerShape(12.dp)),
                        contentAlignment = Alignment.Center) { Icon(JarIcons.Repeat, null, tint = c.ink, modifier = Modifier.size(20.dp)) }
                    JarStyle.CALM -> Box(Modifier.size(40.dp).clip(CircleShape).background(c.accentSoft), contentAlignment = Alignment.Center) {
                        Icon(JarIcons.Repeat, null, tint = c.onAccentSoft, modifier = Modifier.size(20.dp))
                    }
                }
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(s.title, color = if (s.isPaused) c.muted else c.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                    val sub = buildList {
                        add(s.label)
                        if (s.rotate && s.nextTurn.isNotEmpty()) add(ctx.getString(R.string.recurring_turn, TaskLists.name(data.names, s.nextTurn)))
                    }.joinToString(" · ")
                    Text(sub, color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
                }
                if (s.isPaused) Chip(plain(ctx.getString(R.string.recurring_paused)), c.surface2, c.muted)
                People(s.owners, data)
            }
        }
    }
    val s = open
    if (s != null) ModalBottomSheet(onDismissRequest = { open = null }, containerColor = c.bg) {
        var stop by remember { mutableStateOf(false) }
        SheetColumn("series_sheet") {
            SheetTitle(s.title, s.label)
            MainButton(plain(stringResource(if (s.isPaused) R.string.recurring_resume else R.string.recurring_pause))) {
                seriesAct(actions, ctx, s, if (s.isPaused) "resume" else "pause"); open = null
            }
            SideButton(stringResource(R.string.recurring_stop), danger = true) { stop = true }
        }
        if (stop) StopSeriesDialog(s, onDismiss = { stop = false }) { stop = false; open = null }
    }
}

/** Up to three overlapping avatars. */
@Composable
fun People(ids: List<String>, data: HomeData) {
    val jar = LocalJar.current
    Row(horizontalArrangement = Arrangement.spacedBy((-8).dp)) {
        for (id in ids.take(3)) Avatar(TaskLists.name(data.names, id).take(1), data.color(id), 28.dp,
            Modifier.border(2.dp, if (jar.style == JarStyle.PLAYFUL) jar.colors.ink else jar.colors.surface, CircleShape))
    }
}

// ---------------------------------------------------------------- areas of responsibility

/** Who is in charge of what. Calm and Playful: a grid of tiles; Night: a list. Parents change, add and delete. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AreasScreen(data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    var open by remember { mutableStateOf<Area?>(null) }
    var adding by remember { mutableStateOf(false) }
    val tap = { a: Area -> if (data.parent) { open = a } }
    SubScreen(plain(stringResource(R.string.menu_areas)), "areas", stringResource(R.string.ui_areas_sub)) {
        if (data.parent) item(key = "new") { ActionPill(plain(stringResource(R.string.areas_add))) { adding = true } }
        if (data.areas.isEmpty()) item(key = "none") { Muted(stringResource(R.string.areas_none), Modifier.padding(8.dp)) }
        if (jar.style == JarStyle.NIGHT) {
            rows("areas", data.areas, { it.id }) { a ->
                Row(Modifier.fillMaxWidth().clickable { tap(a) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)).border(1.dp, c.line, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
                        Text(a.emoji.ifEmpty { "📌" }, fontSize = 22.sp)
                    }
                    Column(Modifier.weight(1f)) {
                        Text(a.name, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                        if (a.keywords.isNotEmpty()) Text(a.keywords.joinToString(", "), color = c.muted, fontSize = 13.sp, fontFamily = jar.font,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text(TaskLists.name(data.names, a.owner), color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
                    Avatar(TaskLists.name(data.names, a.owner).take(1), data.color(a.owner), 30.dp)
                }
            }
        } else {
            items(data.areas.chunked(2), key = { p -> p.joinToString { it.id } }) { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    for (a in pair) Block(Modifier.weight(1f).clickable { tap(a) }) {
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(a.emoji.ifEmpty { "📌" }, fontSize = if (jar.style == JarStyle.PLAYFUL) 34.sp else 28.sp)
                            Text(a.name, color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Avatar(TaskLists.name(data.names, a.owner).take(1), data.color(a.owner), 22.dp)
                                Text(TaskLists.name(data.names, a.owner), color = c.muted, fontSize = 13.sp, fontFamily = jar.font, maxLines = 1)
                            }
                        }
                    }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
    }
    val a = open
    if (a != null || adding) ModalBottomSheet(onDismissRequest = { open = null; adding = false }, containerColor = c.bg) {
        AreaSheet(a, data) { open = null; adding = false }
    }
}

/** An area: who is in charge (tap to change), its words, edit, delete. With [a] null: a new area. */
@Composable
private fun AreaSheet(a: Area?, data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var editing by remember { mutableStateOf(a == null) }
    var name by remember { mutableStateOf(a?.name ?: "") }
    var emoji by remember { mutableStateOf(a?.emoji ?: "") }
    var words by remember { mutableStateOf(a?.keywords?.joinToString(", ") ?: "") }
    var owner by remember { mutableStateOf(a?.owner ?: data.me) }
    var delete by remember { mutableStateOf(false) }
    val prefs = remember { Prefs(ctx) }
    SheetColumn("area_sheet") {
        SheetTitle(if (a == null) plain(stringResource(R.string.areas_add)) else a.label())
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FormLabel(stringResource(R.string.areas_owner))
            ChipRow {
                for ((id, n) in data.names) ChoiceChip(n, id == owner) {
                    owner = id
                    if (a != null && !editing) {
                        actions.call(R.string.edit_failed, ctx) { TaskApi.editArea(prefs, a.id, JSONObject().put("owner", id)) }
                        onClose()
                    }
                }
            }
        }
        if (editing) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                JarField(emoji, { emoji = it.take(4) }, stringResource(R.string.area_emoji), Modifier.width(96.dp), singleLine = true)
                JarField(name, { name = it }, stringResource(R.string.area_name), Modifier.weight(1f).testTag("area_name"), singleLine = true)
            }
            JarField(words, { words = it }, stringResource(R.string.area_keywords), minLines = 2)
            Muted(stringResource(R.string.area_keywords_hint))
            MainButton(stringResource(if (a == null) R.string.add_save else R.string.ui_save), enabled = name.isNotBlank()) {
                val n = name.trim(); val e = emoji.trim(); val o = owner
                val kw = words.split(Regex("[,،\\n]+")).map { it.trim() }.filter { it.isNotEmpty() }
                actions.call(R.string.edit_failed, ctx) {
                    if (a == null) TaskApi.addArea(prefs, n, e.ifEmpty { "📌" }, o, kw)
                    else TaskApi.editArea(prefs, a.id, JSONObject().put("name", n).put("emoji", e.ifEmpty { a.emoji })
                        .put("keywords", org.json.JSONArray(kw)))
                }
                onClose()
            }
        } else if (a != null) {
            if (a.keywords.isNotEmpty()) Muted(a.keywords.joinToString(", "))
            SideButton(stringResource(R.string.areas_edit)) { editing = true }
            SideButton(stringResource(R.string.areas_delete), danger = true) { delete = true }
        }
    }
    if (delete && a != null) Confirm(ctx.getString(R.string.areas_delete_confirm, a.label()), ctx.getString(R.string.areas_delete), { delete = false }) {
        actions.call(R.string.edit_failed, ctx) { TaskApi.deleteArea(prefs, a.id) }
        onClose()
    }
}

// ---------------------------------------------------------------- archive

/** Done more than a week ago, by month, newest first. Tap one to reopen it or read its notes. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArchiveScreen(data: HomeData, onOpen: (Task) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    var keep by remember { mutableStateOf(false) }
    val now = System.currentTimeMillis()
    val old = remember(data) {
        data.all.filter { !it.isIdea && !it.isMessage && (it.isFor(data.me) || it.createdBy == data.me || data.parent) &&
            TaskLists.doneBucket(it, null, now) == TaskLists.ARCHIVED }.sortedWith(TaskLists.NEWEST_DONE)
    }
    val months = remember(old) {
        val fmt = SimpleDateFormat("LLLL yyyy", Locale.getDefault())
        old.groupBy { val at = TaskLists.utcMillis(TaskLists.doneWhen(it)); if (at < 0) "" else fmt.format(java.util.Date(at)) }
    }
    SubScreen(stringResource(R.string.ui_archive_title), "archive", ctx.getString(R.string.ui_archive_sub, old.size)) {
        if (data.parent) item(key = "keep") {
            Block(Modifier.clickable { keep = true }) {
                Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(JarIcons.Clock, null, tint = c.muted, modifier = Modifier.size(20.dp))
                    Text(stringResource(R.string.menu_keep_done), color = c.ink, fontSize = 15.sp, fontFamily = jar.font, modifier = Modifier.weight(1f))
                    Text(if (data.keepDone == 0) ctx.getString(R.string.keep_forever) else ctx.resources.getQuantityString(R.plurals.keep_days, data.keepDone, data.keepDone),
                        color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
                    Icon(JarIcons.Chevron, null, tint = c.muted, modifier = Modifier.size(18.dp))
                }
            }
        }
        if (old.isEmpty()) item(key = "none") { Muted(stringResource(R.string.ui_archive_empty), Modifier.padding(8.dp)) }
        for ((month, list) in months) taskSection("m_$month", month.ifEmpty { null }, list, data, onOpen)
    }
    if (keep) ModalBottomSheet(onDismissRequest = { keep = false }, containerColor = c.bg) { KeepDoneSheet(data.keepDone) { keep = false } }
}

// ---------------------------------------------------------------- memos

/** Tests put memos here instead of asking the PC. */
@VisibleForTesting
object MemoFeed {
    @Volatile var fake: List<JSONObject>? = null
}

/**
 * What Jar heard and what it did with it. Calm: cards. Night: a timeline with the time in its own column.
 * Playful: speech bubbles. Tap one to fix what was misheard and file it again.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemosScreen() {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    var gen by remember { mutableIntStateOf(0) }
    var memos by remember { mutableStateOf<List<JSONObject>?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<JSONObject?>(null) }
    var deleting by remember { mutableStateOf<Triple<JSONObject, Int, JSONObject>?>(null) }
    val actions = LocalActions.current
    LaunchedEffect(gen) {
        problem = null
        val fake = MemoFeed.fake
        if (fake != null) { memos = fake.map { JSONObject(it.toString()) }; return@LaunchedEffect }
        val prefs = Prefs(ctx)
        if (prefs.token().isEmpty()) { problem = ctx.getString(R.string.tasks_not_paired); return@LaunchedEffect }
        try {
            memos = withContext(Dispatchers.IO) {
                val arr = TaskApi.memos(prefs).optJSONArray("memos")
                (0 until (arr?.length() ?: 0)).mapNotNull { arr!!.optJSONObject(it) }
            }
        } catch (e: Exception) {
            problem = ctx.getString(R.string.memos_failed, e.message)
        }
    }
    SubScreen(stringResource(R.string.memos_title), "memos", stringResource(R.string.ui_memos_sub)) {
        val list = memos
        when {
            problem != null -> item(key = "problem") { Muted(problem!!, Modifier.padding(8.dp)) }
            list == null -> item(key = "loading") { Muted(stringResource(R.string.syncing), Modifier.padding(8.dp)) }
            list.isEmpty() -> item(key = "none") { Muted(stringResource(R.string.memos_empty), Modifier.padding(8.dp)) }
            else -> items(list, key = { it.optString("id") }) { m ->
                MemoCard(m, onDelete = { i, item -> deleting = Triple(m, i, item) }) { open = m }
            }
        }
    }
    val m = open
    if (m != null) ModalBottomSheet(onDismissRequest = { open = null }, containerColor = c.bg) {
        RefileSheet(m) { open = null; gen++ }
    }
    deleting?.let { (memo, i, item) ->
        val what = ctx.getString(when (item.optString("tool")) {
            "add_task", "draft_whatsapp", "suggest_idea" -> R.string.ui_memo_del_task
            "family_event", "create_event" -> R.string.ui_memo_del_event
            "draft_email" -> R.string.ui_memo_del_draft
            else -> R.string.ui_memo_del_note
        })
        Confirm(ctx.getString(R.string.ui_memo_del_confirm, item.optString("summary"), what), ctx.getString(R.string.action_delete),
            onDismiss = { deleting = null }) {
            deleting = null
            val prefs = Prefs(ctx); val id = memo.optString("id")
            if (MemoFeed.fake != null) {            // tests: no PC, mark it on the stored copy
                MemoFeed.fake?.firstOrNull { it.optString("id") == id }?.optJSONArray("items")?.optJSONObject(i)
                    ?.put("removed", true)?.put("deletable", false)
                gen++
            } else actions.background({ TaskApi.deleteMemoItem(prefs, id, i) }, { gen++ },
                { e -> actions.toast(ctx.getString(R.string.memos_failed, e.message)) })
        }
    }
}

private fun transcript(m: JSONObject): String = m.optString("transcript").takeIf { it != "null" } ?: ""

@Composable
private fun MemoCard(m: JSONObject, onDelete: (Int, JSONObject) -> Unit, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val text = transcript(m)
    val did = m.optJSONArray("actions")
    val filing = m.optString("status") != "done"
    val time = TaskFormat.memoTime(m.optString("recorded_at"))
    val body: @Composable () -> Unit = {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (jar.style != JarStyle.NIGHT) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(JarIcons.Mic, null, tint = c.muted, modifier = Modifier.size(16.dp))
                Text(time, color = c.muted, fontSize = 13.sp, fontFamily = jar.font, modifier = Modifier.weight(1f))
                if (filing) Chip(ctx.getString(R.string.memo_in_progress), c.coinSoft, c.coin)
                if (m.optBoolean("edited")) Chip(ctx.getString(R.string.memo_edited), c.surface2, c.muted)
            }
            Text(text.ifEmpty { ctx.getString(R.string.memo_no_text) }, color = if (text.isEmpty()) c.muted else c.ink, fontSize = 16.sp, fontFamily = jar.font)
            // What Jar did: each thing it made can be taken back from here (the newer PC sends "items").
            val items = m.optJSONArray("items")
            val n = items?.length() ?: did?.length() ?: 0
            if (n > 0) {
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.accentSoft).padding(start = 10.dp, top = 10.dp, bottom = 6.dp, end = 2.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(stringResource(R.string.ui_jar_did), color = c.onAccentSoft, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                    for (i in 0 until n) {
                        val item = items?.optJSONObject(i)
                        val summary = item?.optString("summary") ?: did?.optString(i) ?: ""
                        val removed = item?.optBoolean("removed") == true
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.heightIn(min = 40.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text(summary, color = if (removed) c.muted else c.ink, fontSize = 14.sp, fontFamily = jar.font,
                                    textDecoration = if (removed) androidx.compose.ui.text.style.TextDecoration.LineThrough else null)
                                when {
                                    removed -> Text(stringResource(R.string.ui_memo_removed), color = c.muted, fontSize = 12.sp, fontFamily = jar.font)
                                    item?.optBoolean("removing") == true -> Text(stringResource(R.string.ui_memo_removing), color = c.coin, fontSize = 12.sp, fontFamily = jar.font)
                                    item?.optString("failed").orEmpty().isNotEmpty() -> Text(ctx.getString(R.string.ui_memo_remove_failed, item!!.optString("failed")),
                                        color = c.danger, fontSize = 12.sp, fontFamily = jar.font)
                                }
                            }
                            if (item?.optBoolean("deletable") == true) {
                                val label = ctx.getString(R.string.action_delete) + ": " + summary
                                Box(Modifier.size(40.dp).clip(CircleShape).clickable(role = Role.Button) { onDelete(i, item) }
                                    .semantics { contentDescription = label }.testTag("memo_item_delete"), contentAlignment = Alignment.Center) {
                                    Icon(JarIcons.Trash, null, tint = c.muted, modifier = Modifier.size(18.dp))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if (jar.style == JarStyle.NIGHT) {
        Row(Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onClick), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(Modifier.width(54.dp).padding(top = 14.dp), horizontalAlignment = Alignment.End) {
                Text(time.substringAfterLast(' '), color = if (filing) c.coin else c.accent, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                Text(time.substringBeforeLast(' ', ""), color = c.muted, fontSize = 11.sp, fontFamily = jar.font, maxLines = 1)
            }
            Block(Modifier.weight(1f)) { body() }
        }
    } else Block(Modifier.clickable(role = Role.Button, onClick = onClick)) { body() }
}

@Composable
private fun RefileSheet(m: JSONObject, onDone: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var text by remember { mutableStateOf(transcript(m)) }
    var confirm by remember { mutableStateOf(false) }
    val refile = { t: String? ->
        val prefs = Prefs(ctx); val id = m.optString("id")
        actions.call(R.string.memos_failed, ctx, ok = { actions.toast(ctx.getString(R.string.memo_refiled)) }) { TaskApi.refile(prefs, id, t) }
        onDone()
    }
    SheetColumn("refile") {
        if (transcript(m).isNotEmpty()) {
            SheetTitle(stringResource(R.string.memo_edit_title), stringResource(R.string.memo_edit_message))
            JarField(text, { text = it }, stringResource(R.string.memo_edit_hint), Modifier.testTag("memo_text"), minLines = 3)
            MainButton(stringResource(R.string.memo_save_refile), enabled = text.isNotBlank()) { refile(text.trim()) }
            SideButton(stringResource(R.string.memo_refile_as_is)) { refile(null) }
        } else SheetTitle(stringResource(R.string.memo_no_text), TaskFormat.memoTime(m.optString("recorded_at")))
        SideButton(stringResource(R.string.ui_memo_delete_all), Modifier.testTag("delete_memo"), danger = true) { confirm = true }
    }
    if (confirm) Confirm(ctx.getString(R.string.ui_memo_delete_all_confirm), ctx.getString(R.string.action_delete), { confirm = false }) {
        confirm = false
        val prefs = Prefs(ctx); val id = m.optString("id")
        if (MemoFeed.fake != null) {                  // tests: no PC
            MemoFeed.fake = MemoFeed.fake!!.filter { it.optString("id") != id }
        } else actions.call(R.string.memos_failed, ctx, ok = { actions.toast(ctx.getString(R.string.ui_memo_deleted)) }) { TaskApi.deleteMemo(prefs, id) }
        onDone()
    }
}
