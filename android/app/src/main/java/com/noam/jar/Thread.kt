package com.noam.jar

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists

/**
 * Notes and questions on a task. "Ask X" sends a question that stays on their list until they answer;
 * ✨ asks the PC for a few short replies to pick from; long-press your own note to change or remove it.
 * Calm: soft bubbles. Night: outlined bubbles with the time in the margin. Playful: ink bubbles with a shadow.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ThreadScreen(taskId: String, data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val t = data.all.firstOrNull { it.id == taskId }
    if (t == null) {
        LaunchedEffect(Unit) { actions.toast(ctx.getString(R.string.thread_gone)); actions.back() }
        return
    }
    val me = data.me
    val other = t.counterpart(me)
    var text by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var suggesting by remember { mutableStateOf(false) }
    var replies by remember { mutableStateOf(emptyList<String>()) }
    var editing by remember { mutableStateOf<Task.Note?>(null) }
    val list = rememberLazyListState()
    LaunchedEffect(t.thread.size) { if (t.thread.isNotEmpty()) list.scrollToItem(t.thread.size - 1) }
    val prefs = remember { Prefs(ctx) }
    val send = { ask: Boolean ->
        val body = text.trim()
        if (body.isEmpty()) actions.toast(ctx.getString(R.string.thread_write_first))
        else {
            busy = true
            actions.background({ TaskApi.addNote(prefs, t.id, body, ask) }, { json ->
                TaskCache(ctx).upsert(json); Jar.notifyState(ctx)
                text = ""; replies = emptyList(); busy = false
                if (ask) actions.toast(ctx.getString(R.string.thread_asked))
            }, { e -> busy = false; actions.toast(ctx.getString(R.string.thread_failed, e.message)) })
        }
    }

    Column(Modifier.fillMaxSize().testTag("thread")) {
        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BackButton { actions.back() }
            Column(Modifier.weight(1f)) {
                Text(t.title, color = c.ink, fontSize = if (jar.style == JarStyle.NIGHT) 22.sp else 20.sp, fontWeight = FontWeight.Bold,
                    fontFamily = jar.display, maxLines = 2)
                Text(stringResource(R.string.thread_title), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            }
        }
        val banner = when {
            t.waitingOn(me) -> ctx.getString(R.string.thread_waiting_on_you, TaskLists.name(data.names, t.lastNote()?.by ?: t.createdBy))
            t.waitingOn.isNotEmpty() -> ctx.getString(R.string.thread_waiting_on, TaskLists.name(data.names, t.waitingOn))
            else -> null
        }
        if (banner != null) Text(banner, color = c.coin, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font,
            modifier = Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.coinSoft).padding(12.dp))
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = list, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (t.thread.isEmpty()) item { Muted(stringResource(if (other.isEmpty()) R.string.thread_empty_own else R.string.thread_empty), Modifier.padding(top = 24.dp)) }
            items(t.thread, key = { it.id }) { n ->
                Bubble(n, n.by == me, data, Modifier.combinedClickable(onClick = {}, onLongClick = { if (n.by == me) editing = n }))
            }
        }
        if (replies.isNotEmpty()) Row(Modifier.padding(horizontal = 16.dp)) {
            ChipRow { for (r in replies) ChoiceChip(r, false) { text = r } }
        }
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            JarField(text, { text = it }, stringResource(R.string.thread_hint), Modifier.testTag("thread_input"), minLines = 1)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                ChoiceChip(plain(stringResource(if (suggesting) R.string.thread_suggesting else R.string.thread_suggest)), false) {
                    if (suggesting) return@ChoiceChip
                    suggesting = true
                    actions.background({ TaskApi.suggest(prefs, t.id) }, { r -> replies = r; suggesting = false },
                        { e -> suggesting = false; actions.toast(ctx.getString(R.string.thread_failed, e.message)) })
                }
                Box(Modifier.weight(1f))
                if (other.isNotEmpty()) SideButton(ctx.getString(R.string.thread_ask_name, TaskLists.name(data.names, other)), Modifier.widthIn(max = 150.dp)) {
                    if (!busy) send(true)
                }
                MainButton(stringResource(if (t.waitingOn(me)) R.string.thread_answer_button else R.string.thread_add_note), Modifier.widthIn(max = 150.dp),
                    enabled = !busy) { send(false) }
            }
        }
    }
    val n = editing
    if (n != null) {
        var edit by remember(n.id) { mutableStateOf(n.text) }
        val save = { body: String ->
            editing = null
            actions.background({ TaskApi.editNote(prefs, t.id, n.id, body) }, { json -> TaskCache(ctx).upsert(json); Jar.notifyState(ctx) },
                { e -> actions.toast(ctx.getString(R.string.thread_failed, e.message)) })
        }
        AlertDialog(onDismissRequest = { editing = null }, title = { Text(stringResource(R.string.thread_edit_title)) },
            text = { JarField(edit, { edit = it }, stringResource(R.string.thread_hint), minLines = 2) },
            confirmButton = { TextButton(onClick = { save(edit.trim()) }) { Text(stringResource(R.string.save)) } },
            dismissButton = {
                Row {
                    TextButton(onClick = { save("") }) { Text(stringResource(R.string.action_delete), color = c.danger) }
                    TextButton(onClick = { editing = null }) { Text(stringResource(android.R.string.cancel)) }
                }
            })
    }
}

@Composable
private fun Bubble(n: Task.Note, mine: Boolean, data: HomeData, modifier: Modifier) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = if (mine) 18.dp else 4.dp, bottomEnd = if (mine) 4.dp else 18.dp)
    val bg = when {
        n.ask -> c.coinSoft
        jar.style == JarStyle.NIGHT -> if (mine) c.accentSoft else c.surface
        mine -> if (jar.style == JarStyle.PLAYFUL) c.accent else c.accentSoft
        else -> c.surface
    }
    val head = buildList {
        add(if (mine) ctx.getString(R.string.thread_me) else TaskLists.name(data.names, n.by))
        if (jar.style != JarStyle.NIGHT) add(TaskFormat.memoTime(n.at))
        if (n.ask) add(ctx.getString(R.string.thread_question))
        if (n.edited) add(ctx.getString(R.string.memo_edited))
    }.joinToString(" · ")
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start, verticalAlignment = Alignment.Bottom) {
        if (jar.style == JarStyle.NIGHT && mine) Text(TaskFormat.memoTime(n.at), color = c.muted, fontSize = 11.sp, fontFamily = jar.font,
            modifier = Modifier.padding(end = 8.dp))
        Box(Modifier.widthIn(max = 290.dp)) {
            if (jar.style == JarStyle.PLAYFUL) Box(Modifier.matchParentSize().offset(3.dp, 3.dp).clip(shape).background(c.ink))
            Column(modifier.clip(shape).background(bg)
                .then(when (jar.style) {
                    JarStyle.PLAYFUL -> Modifier.border(2.dp, c.ink, shape)
                    JarStyle.NIGHT -> Modifier.border(1.dp, if (mine) c.accent.copy(alpha = 0.5f) else c.line, shape)
                    JarStyle.CALM -> Modifier
                }).padding(horizontal = 12.dp, vertical = 9.dp)) {
                Text(head, color = c.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                Text(n.text, color = c.ink, fontSize = 16.sp, fontFamily = jar.font)
            }
        }
        if (jar.style == JarStyle.NIGHT && !mine) Text(TaskFormat.memoTime(n.at), color = c.muted, fontSize = 11.sp, fontFamily = jar.font,
            modifier = Modifier.padding(start = 8.dp))
    }
}
