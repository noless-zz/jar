package com.noam.jar

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import kotlinx.coroutines.launch
import java.util.TimeZone
import kotlin.math.roundToInt

/** A task's sheet. Calm and Playful: a grid of big buttons. Night: slide to finish and three outlined buttons. */
@Composable
fun TaskSheet(t: Task, data: HomeData, onClose: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val now = System.currentTimeMillis()
    val tz = TimeZone.getDefault()
    // My own task: Done. Someone else's: only the admin (Noam) can tick it for them, e.g. Sveta did it and
    // forgot; the coins are theirs. (openFor() alone doesn't look at whose task it is.)
    val own = t.isFor(data.me)
    val open = own && t.openFor(data.me)
    val forOther = !own && data.admin && t.isOpen && !t.isIdea && !t.isMessage
    val otherNames = t.owners().joinToString(", ") { TaskLists.name(data.names, it) }
    var more by remember { mutableStateOf(false) }
    val editable = t.status != "declined" && !t.isMessage
    val repeatable = data.canMakeRepeat(t)
    val edit = { onClose(); actions.edit(EditReq(t)) }
    val repeat = { onClose(); actions.edit(EditReq(t, repeat = true)) }
    val act = { a: String, until: String? -> actions.act(t, a, until); onClose() }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (jar.style == JarStyle.NIGHT && t.createdBy.isNotEmpty())
                Text(ctx.getString(R.string.ui_from, TaskLists.name(data.names, t.createdBy)), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            Text(t.title, color = c.ink, fontSize = if (jar.style == JarStyle.NIGHT) 26.sp else 24.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
            SheetChips(t, data)
        }
        if (t.isMessage) {
            MessageActions(t, onClose)
            if (t.isDone) SideButton(ctx.getString(R.string.action_reopen)) { act("reopen", null) }
            return@Column
        }
        if (jar.style == JarStyle.NIGHT) {
            if (open) SlideToFinish(onDone = { act("done", null) })
            if (forOther) SlideToFinish(ctx.getString(R.string.ui_done_for, otherNames), onDone = { act("done", null) })
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (!open && (t.isDone || t.doneFor(data.me)))
                    OutlineAction(JarIcons.Undo, ctx.getString(R.string.action_reopen), Modifier.weight(1f)) { act("reopen", null) }
                if (open) OutlineAction(JarIcons.Clock, ctx.getString(R.string.ui_action_later), Modifier.weight(1f)) {
                    act("snooze", TaskLists.inAnHour(now, tz))
                }
                if (repeatable) OutlineAction(JarIcons.Repeat, ctx.getString(R.string.ui_repeat), Modifier.weight(1f), repeat)
                else if (editable) OutlineAction(JarIcons.Edit, ctx.getString(R.string.ui_edit), Modifier.weight(1f), edit)
                OutlineAction(JarIcons.Chat, ctx.getString(R.string.ui_ask), Modifier.weight(1f)) { onClose(); actions.thread(t) }
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (open) {
                    BigAction(JarIcons.Check, ctx.getString(R.string.action_done), true, Modifier.weight(1f)) { act("done", null) }
                    BigAction(JarIcons.Clock, ctx.getString(R.string.ui_action_later), false, Modifier.weight(1f)) { act("snooze", TaskLists.inAnHour(now, tz)) }
                } else if (forOther) {
                    BigAction(JarIcons.Check, ctx.getString(R.string.ui_done_for, otherNames), true, Modifier.weight(2f)) { act("done", null) }
                } else if (t.isDone || t.doneFor(data.me)) {
                    BigAction(JarIcons.Undo, ctx.getString(R.string.action_reopen), true, Modifier.weight(1f)) { act("reopen", null) }
                }
                if (repeatable) BigAction(JarIcons.Repeat, ctx.getString(R.string.ui_repeat), false, Modifier.weight(1f), repeat)
                if (editable) BigAction(JarIcons.Edit, ctx.getString(R.string.ui_edit), false, Modifier.weight(1f), edit)
            }
        }
        if (open) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SheetChip(ctx.getString(R.string.snooze_hour)) { act("snooze", TaskLists.inAnHour(now, tz)) }
                TaskLists.tonight(now, tz)?.let { tonight -> SheetChip(ctx.getString(R.string.snooze_tonight)) { act("snooze", tonight) } }
                SheetChip(ctx.getString(R.string.snooze_tomorrow)) { act("snooze", TaskLists.tomorrowMorning(now, tz)) }
            }
        }
        Notes(t, data) { onClose(); actions.thread(t) }
        if (more) MoreActions(t, data, onClose)
        else Text(stringResource(R.string.ui_open_in_classic), color = c.muted, fontSize = 14.sp, fontFamily = jar.font,
            modifier = Modifier.clip(RoundedCornerShape(10.dp)).clickable(role = Role.Button) { more = true }
                .padding(vertical = 8.dp).testTag("all_actions"))
    }
}

@Composable
fun SheetChips(t: Task, data: HomeData) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        val owner = t.owners().firstOrNull()
        if (owner != null) {
            Row(Modifier.clip(RoundedCornerShape(14.dp)).background(c.surface).border(1.dp, c.line, RoundedCornerShape(14.dp))
                .padding(start = 4.dp, end = 10.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Avatar(TaskLists.name(data.names, owner).take(1), data.color(owner), 22.dp)
                Text(TaskLists.name(data.names, owner) + if (t.owners().size > 1) " +" + (t.owners().size - 1) else "",
                    color = c.ink, fontSize = 13.sp, fontFamily = jar.font)
            }
        }
        if (t.due != null) Chip(TaskFormat.`when`(ctx, t.due), c.surface, c.ink)
        if (t.coins > 0 && !t.isMessage) Chip(ctx.getString(R.string.ui_coins, t.coins), c.coinSoft, c.coin)
    }
}

/** The task's notes: the last two, and a way into the full thread. */
@Composable
fun Notes(t: Task, data: HomeData, onThread: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (t.notes.isNotEmpty() || t.thread.isNotEmpty())
            Text(stringResource(R.string.ui_notes), color = c.muted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
        if (t.notes.isNotEmpty())
            Text(t.notes, color = c.ink, fontSize = 15.sp, fontFamily = jar.font,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(c.surface).padding(12.dp))
        for (n in t.thread.takeLast(2)) {
            val mine = n.by == data.me
            Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
                Column(Modifier.widthIn(max = 280.dp).clip(RoundedCornerShape(16.dp)).background(if (mine) c.accentSoft else c.surface).padding(10.dp)) {
                    if (!mine) Text(TaskLists.name(data.names, n.by), color = c.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
                    Text(n.text, color = c.ink, fontSize = 15.sp, fontFamily = jar.font)
                }
            }
        }
        Row(Modifier.fillMaxWidth().height(48.dp).clip(RoundedCornerShape(24.dp)).background(c.surface).border(1.dp, c.line, RoundedCornerShape(24.dp))
            .clickable(role = Role.Button, onClick = onThread).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.ui_reply), color = c.muted, fontSize = 15.sp, fontFamily = jar.font, modifier = Modifier.weight(1f))
            Icon(JarIcons.Chat, null, tint = c.accent, modifier = Modifier.size(20.dp))
        }
    }
}

/** Night: drag the glowing thumb across to finish (a tap on the bar does it too, for accessibility). */
@Composable
private fun SlideToFinish(text: String? = null, onDone: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val scope = rememberCoroutineScope()
    val x = remember { Animatable(0f) }
    val label = text ?: stringResource(R.string.ui_slide_done)
    val density = LocalDensity.current
    BoxWithConstraints(
        Modifier.fillMaxWidth().height(64.dp).clip(RoundedCornerShape(32.dp)).background(c.accentSoft)
            .border(1.dp, c.accent.copy(alpha = 0.4f), RoundedCornerShape(32.dp))
            .semantics { contentDescription = label; onClick { onDone(); true } }.testTag("slide_done"),
    ) {
        val max = with(density) { (maxWidth - 64.dp).toPx() }
        Text(label, color = c.onAccentSoft, fontSize = 16.sp, fontFamily = jar.font, modifier = Modifier.align(Alignment.Center))
        Box(
            Modifier.offset { IntOffset(x.value.roundToInt(), 0) }.padding(6.dp).size(52.dp).clip(CircleShape)
                .background(Brush.radialGradient(listOf(c.accent.copy(alpha = 0.7f), c.accent)))
                .pointerInput(Unit) {
                    detectHorizontalDragGestures(
                        onDragEnd = { scope.launch { if (x.value > max * 0.8f || x.value < -max * 0.8f) onDone() else x.animateTo(0f) } },
                        onHorizontalDrag = { ch, d -> ch.consume(); scope.launch { x.snapTo((x.value + d).coerceIn(-max, max)) } },
                    )
                },
            contentAlignment = Alignment.Center,
        ) {
            Icon(JarIcons.Check, null, tint = c.onAccent, modifier = Modifier.size(24.dp))
        }
    }
}

@Composable
private fun BigAction(icon: ImageVector, label: String, primary: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(20.dp)
    val bg = if (primary) (if (playful) c.record else c.accent) else c.surface
    val fg = if (primary) (if (playful) c.onRecord else c.onAccent) else c.ink
    Column(
        modifier.height(76.dp).clip(shape).background(bg)
            .then(if (playful) Modifier.border(2.dp, c.ink, shape) else if (!primary) Modifier.border(1.dp, c.line, shape) else Modifier)
            .clickable(role = Role.Button, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(icon, null, tint = fg, modifier = Modifier.size(22.dp))
        Spacer(Modifier.height(6.dp))
        Text(label, color = fg, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun OutlineAction(icon: ImageVector, label: String, modifier: Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Column(modifier.height(64.dp).clip(shape).border(1.dp, c.line, shape).clickable(role = Role.Button, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Icon(icon, null, tint = c.ink, modifier = Modifier.size(20.dp))
        Spacer(Modifier.height(4.dp))
        Text(label, color = c.ink, fontSize = 13.sp, fontFamily = jar.font, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun SheetChip(label: String, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Text(label, color = c.ink, fontSize = 13.sp, fontFamily = jar.font, maxLines = 1,
        modifier = Modifier.clip(shape).border(1.dp, c.line, shape).clickable(role = Role.Button, onClick = onClick).padding(horizontal = 12.dp, vertical = 9.dp))
}
