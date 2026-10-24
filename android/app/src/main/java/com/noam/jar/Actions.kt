package com.noam.jar

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Series
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import kotlin.math.roundToInt

/**
 * The rest of what can be done with a task (the classic long menu), as a list in the sheet:
 * OK a request, move it to whoever is in charge, snooze to a picked time, coins, repeat, delete.
 */
@Composable
fun MoreActions(t: Task, data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val me = data.me
    val act = { a: String, until: String? -> actions.act(t, a, until); onClose() }
    var dialog by remember { mutableStateOf<String?>(null) }
    val series = data.seriesOf(t)
    val seriesMine = series != null && data.mayChange(series)
    Column(Modifier.testTag("more_actions"), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        if (t.isRequested && data.parent && me != t.createdBy) {
            ActionRow(JarIcons.Check, plain(ctx.getString(R.string.action_accept))) { act("accept", null) }
            ActionRow(JarIcons.Close, ctx.getString(R.string.action_decline), danger = true) { act("decline", null) }
        }
        if (t.mayApproveHandover(me, data.parent)) {
            ActionRow(JarIcons.Check, plain(ctx.getString(R.string.handover_accept, TaskLists.name(data.names, t.handoverTo)))) { act("handover_accept", null) }
            ActionRow(JarIcons.Close, plain(ctx.getString(R.string.handover_decline))) { act("handover_decline", null) }
        } else if (t.hasHandover() && me == t.handoverBy) {
            ActionRow(JarIcons.Close, ctx.getString(R.string.handover_cancel)) { act("handover_decline", null) }
        } else if (t.areaSuggest.isNotEmpty() && (t.isFor(me) || me == t.createdBy)) {
            val area = TaskFormat.area(ctx, t.area)
            ActionRow(JarIcons.Family, plain(ctx.getString(R.string.handover_ask, TaskLists.name(data.names, t.areaSuggest), area?.label() ?: ""))) { act("handover", null) }
            ActionRow(JarIcons.Check, ctx.getString(R.string.handover_keep)) { act("dismiss_suggest", null) }
        }
        if (t.openFor(me)) ActionRow(JarIcons.Clock, plain(ctx.getString(R.string.snooze_pick))) { dialog = "snooze" }
        else if (t.doneFor(me) || t.status == "declined") ActionRow(JarIcons.Undo, ctx.getString(R.string.action_reopen)) { act("reopen", null) }
        if (data.parent && t.canRate()) ActionRow(JarIcons.Trophy, plain(ctx.getString(R.string.effort_menu))) { dialog = "effort" }
        if (data.canMakeRepeat(t)) ActionRow(JarIcons.Repeat, plain(ctx.getString(R.string.make_repeat))) { onClose(); actions.edit(EditReq(t, true)) }
        if (seriesMine) ActionRow(JarIcons.Repeat, ctx.getString(R.string.recurring_stop), danger = true) { dialog = "stop" }
        if (me == t.createdBy || data.admin) ActionRow(JarIcons.Close, ctx.getString(R.string.action_delete), danger = true, tag = "delete") {
            dialog = if (seriesMine) "delete_series" else "delete"
        }
    }
    when (dialog) {
        "snooze" -> WhenDialog(timeOnly = false, hour = 8, onDismiss = { dialog = null }) { dialog = null; act("snooze", it) }
        "effort" -> EffortDialog(t, onDismiss = { dialog = null })
        "stop" -> series?.let { s -> StopSeriesDialog(s, onDismiss = { dialog = null }) { dialog = null; onClose() } }
        "delete" -> Confirm(ctx.getString(R.string.ui_delete_confirm, t.title), ctx.getString(R.string.action_delete), onDismiss = { dialog = null }) {
            dialog = null; act("delete", null)
        }
        "delete_series" -> AlertDialog(onDismissRequest = { dialog = null },
            title = { Text(ctx.getString(R.string.delete_recurring_title, t.title)) },
            text = {
                Column {
                    TextButton(onClick = { dialog = null; act("delete", null) }) { Text(stringResource(R.string.delete_only_this)) }
                    TextButton(onClick = { dialog = null; seriesAct(actions, ctx, series!!, "stop"); onClose() }) { Text(stringResource(R.string.delete_whole_series)) }
                }
            },
            confirmButton = {}, dismissButton = { TextButton(onClick = { dialog = null }) { Text(stringResource(android.R.string.cancel)) } })
    }
}

fun seriesAct(actions: HomeActions, ctx: android.content.Context, s: Series, action: String) {
    val prefs = Prefs(ctx)
    actions.call(R.string.edit_failed, ctx) { TaskApi.seriesAct(prefs, s.id, action) }
}

@Composable
fun StopSeriesDialog(s: Series, onDismiss: () -> Unit, onDone: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    Confirm(ctx.getString(R.string.recurring_stop_confirm, s.title), ctx.getString(R.string.recurring_stop), onDismiss) {
        seriesAct(actions, ctx, s, "stop"); onDone()
    }
}

@Composable
fun Confirm(message: String, yes: String, onDismiss: () -> Unit, onYes: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, text = { Text(message) },
        confirmButton = { TextButton(onClick = onYes, modifier = Modifier.testTag("confirm")) { Text(yes) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) } })
}

/** A parent says what a task is worth: 1-10 (× 5 coins), or no coins for this one. */
@Composable
fun EffortDialog(t: Task, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val jar = LocalJar.current
    var effort by remember { mutableFloatStateOf((if (t.effort > 0) t.effort else 3).toFloat()) }
    var none by remember { mutableStateOf(t.noCoins) }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(ctx.getString(R.string.effort_title, t.title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val e = effort.roundToInt()
                Text(if (none) ctx.getString(R.string.effort_no_coins) else ctx.getString(R.string.effort_value, e, e * 5),
                    fontSize = 18.sp, fontFamily = jar.display)
                Slider(effort, { effort = it }, valueRange = 1f..10f, steps = 8, enabled = !none,
                    colors = SliderDefaults.colors(thumbColor = jar.colors.accent, activeTrackColor = jar.colors.accent))
                Muted(stringResource(R.string.effort_scale))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(none, { none = it }, colors = CheckboxDefaults.colors(checkedColor = jar.colors.accent))
                    Text(stringResource(R.string.effort_no_coins))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val e = effort.roundToInt()
                val prefs = Prefs(ctx)
                val noCoins = none
                actions.call(R.string.edit_failed, ctx, ok = { actions.toast(ctx.getString(R.string.effort_saved)) }) {
                    TaskApi.setPoints(prefs, t.id, if (noCoins) 0 else e, if (noCoins == t.noCoins) null else noCoins)
                }
                onDismiss()
            }) { Text(stringResource(android.R.string.ok)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) } })
}

// ---------------------------------------------------------------- ideas

/** An idea: its status, the notes, and for the admin accept / decline (with a word) / shipped. */
@Composable
fun IdeaSheet(t: Task, data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val jar = LocalJar.current
    val c = jar.colors
    var declining by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("") }
    var confirmDelete by remember { mutableStateOf(false) }
    val act = { a: String -> actions.act(t, a, null); onClose() }
    SheetColumn("idea_sheet") {
        val (label, bg, fg) = when {
            t.isRequested -> Triple(R.string.idea_status_new, c.coinSoft, c.coin)
            t.isOpen -> Triple(R.string.idea_status_accepted, c.accentSoft, c.onAccentSoft)
            t.isDone -> Triple(R.string.idea_status_shipped, c.accent, c.onAccent)
            else -> Triple(R.string.idea_status_declined, c.surface2, c.muted)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip(plain(ctx.getString(label)), bg, fg)
                if (t.createdBy.isNotEmpty()) Muted(ctx.getString(R.string.ui_from, TaskLists.name(data.names, t.createdBy)))
            }
            SheetTitle(t.title)
        }
        Notes(t, data) { onClose(); actions.thread(t) }
        if (data.admin) {
            if (declining) {
                JarField(note, { note = it }, stringResource(R.string.idea_decline_note), minLines = 2)
                MainButton(stringResource(R.string.idea_decline)) {
                    val prefs = Prefs(ctx); val text = note.trim()
                    actions.call(R.string.edit_failed, ctx) { TaskApi.declineIdea(prefs, t.id, text) }
                    onClose()
                }
            } else when {
                t.isRequested -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    MainButton(plain(stringResource(R.string.idea_accept)), Modifier.weight(1f)) { act("accept") }
                    SideButton(stringResource(R.string.idea_decline), Modifier.weight(1f)) { declining = true }
                }
                t.isOpen -> MainButton(plain(stringResource(R.string.idea_shipped))) { act("done") }
                t.isDone -> SideButton(stringResource(R.string.idea_reopen)) { act("reopen") }
            }
        }
        if (data.me == t.createdBy || data.admin) SideButton(stringResource(R.string.action_delete), danger = true) { confirmDelete = true }
    }
    if (confirmDelete) Confirm(ctx.getString(R.string.ui_delete_confirm, t.title), ctx.getString(R.string.action_delete), { confirmDelete = false }) {
        confirmDelete = false; act("delete")
    }
}

@Composable
fun NewIdeaSheet(onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var title by remember { mutableStateOf("") }
    var details by remember { mutableStateOf("") }
    SheetColumn("idea_new") {
        SheetTitle(plain(stringResource(R.string.idea_new)), stringResource(R.string.idea_hint))
        JarField(title, { title = it }, stringResource(R.string.idea_what), Modifier.testTag("idea_title"))
        JarField(details, { details = it }, stringResource(R.string.idea_details), minLines = 3)
        MainButton(stringResource(R.string.lesson_send), enabled = title.isNotBlank()) {
            val prefs = Prefs(ctx); val t = title.trim(); val d = details.trim()
            actions.call(R.string.idea_failed, ctx) { TaskApi.createIdea(prefs, t, d) }
            onClose()
        }
    }
}

// ---------------------------------------------------------------- coins

/** A child writes what they learned; the PC's AI rates it (a few seconds), then a toast with the coins. */
@Composable
fun LessonSheet(onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var subject by remember { mutableStateOf("") }
    var learned by remember { mutableStateOf("") }
    SheetColumn("lesson") {
        SheetTitle(stringResource(R.string.lesson_title))
        JarField(subject, { subject = it }, stringResource(R.string.lesson_subject_hint), singleLine = true)
        JarField(learned, { learned = it }, stringResource(R.string.lesson_learned_hint), Modifier.testTag("lesson_text"), minLines = 4)
        MainButton(stringResource(R.string.lesson_send), enabled = learned.isNotBlank()) {
            val note = learned.trim(); val title = subject.trim()
            if (note.length < 12) { actions.toast(ctx.getString(R.string.lesson_too_short)); return@MainButton }
            actions.toast(ctx.getString(R.string.lesson_rating))
            val prefs = Prefs(ctx)
            actions.background({ TaskApi.parseAward(TaskApi.lesson(prefs, title, note)) },
                { a -> PointsUi.toast(ctx, a) },
                { e -> actions.toast(if (e is TaskApi.HttpError && e.code == 429) ctx.getString(R.string.lesson_limit)
                    else ctx.getString(R.string.lesson_failed, e.message)) })
            onClose()
        }
    }
}

/** A parent: "I worked today" pays the work-day base, once a day. */
fun logWorkDay(actions: HomeActions, ctx: android.content.Context) {
    val prefs = Prefs(ctx)
    actions.background({ TaskApi.parseAward(TaskApi.workDay(prefs)) },
        { a -> actions.toast(ctx.getString(R.string.workday_logged, a?.coins ?: 0)) },
        { e -> actions.toast(if (e is TaskApi.HttpError && e.code == 409) ctx.getString(R.string.workday_already) else e.message ?: "") })
}

/** Parents: how long finished tasks stay in the archive before the PC removes them. */
@Composable
fun KeepDoneSheet(current: Int, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    SheetColumn("keep_done") {
        SheetTitle(stringResource(R.string.menu_keep_done), stringResource(R.string.ui_keep_done_sub))
        ChipRow {
            for (d in listOf(0, 30, 90, 180, 365)) {
                ChoiceChip(if (d == 0) ctx.getString(R.string.keep_forever) else ctx.resources.getQuantityString(R.plurals.keep_days, d, d), d == current) {
                    val prefs = Prefs(ctx)
                    actions.call(R.string.edit_failed, ctx) { TaskApi.setSettings(prefs, org.json.JSONObject().put("keep_done_days", d)) }
                    onClose()
                }
            }
        }
    }
}

// ---------------------------------------------------------------- WhatsApp messages, invite, about

/** A message Jar drafted for WhatsApp: the text, then send (WhatsApp opens with it), change it, or copy it. */
@Composable
fun MessageActions(t: Task, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val jar = LocalJar.current
    var editing by remember { mutableStateOf(false) }
    var text by remember { mutableStateOf(t.message) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.testTag("message")) {
        if (editing) {
            JarField(text, { text = it }, stringResource(R.string.ui_message), minLines = 3)
            MainButton(stringResource(R.string.ui_save), enabled = text.isNotBlank()) {
                val prefs = Prefs(ctx); val m = text.trim()
                actions.call(R.string.edit_failed, ctx) { TaskApi.editMessage(prefs, t.id, m) }
                onClose()
            }
        } else {
            Block {
                Text(t.message, color = jar.colors.ink, fontSize = 16.sp, fontFamily = jar.font, modifier = Modifier.padding(14.dp))
            }
            if (t.isOpen) {
                MainButton(stringResource(R.string.send_whatsapp), Modifier.testTag("send_whatsapp")) { onClose(); actions.sendWhatsApp(t) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SideButton(plain(stringResource(R.string.message_edit)).trimEnd('…'), Modifier.weight(1f)) { editing = true }
                    SideButton(stringResource(R.string.message_copy), Modifier.weight(1f)) {
                        ctx.getSystemService(android.content.ClipboardManager::class.java)
                            ?.setPrimaryClip(android.content.ClipData.newPlainText("Jar", t.message))
                        actions.toast(ctx.getString(R.string.message_copied))
                    }
                }
            }
        }
    }
}

/** The admin picks who to invite; the PC writes their personal "install and join" message for WhatsApp. */
@Composable
fun InviteSheet(data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val others = data.names.filterKeys { it != data.me }
    SheetColumn("invite") {
        SheetTitle(stringResource(R.string.ui_set_invite), stringResource(R.string.ui_invite_sub))
        if (others.isEmpty()) Muted(stringResource(R.string.invite_nobody))
        for ((id, name) in others) {
            ActionRow(JarIcons.Family, name) { onClose(); actions.invite(id) }
        }
    }
}

/** Version, updates, the download page and sharing the app. */
@Composable
fun AboutSheet(data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    SheetColumn("about") {
        SheetTitle(stringResource(R.string.ui_set_about), ctx.getString(R.string.ui_version, BuildConfig.VERSION_NAME))
        if (data.update != null) {
            Muted(ctx.getString(R.string.update_available, data.update, BuildConfig.VERSION_NAME) +
                if (data.whatsNew.isEmpty()) "" else "\n" + ctx.getString(R.string.update_whats_new, data.whatsNew))
            MainButton(stringResource(R.string.update_install)) { onClose(); actions.installUpdate() }
        } else {
            MainButton(stringResource(R.string.menu_update)) { actions.checkUpdate() }
        }
        SideButton(stringResource(R.string.update_open_page)) { onClose(); actions.openUrl(TasksActivity.downloadPage()) }
        SideButton(stringResource(R.string.share_app)) { onClose(); actions.shareApp() }
    }
}

/** On the task list when a newer Jar is out: what's new, and Update. */
@Composable
fun UpdateBanner(data: HomeData) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val jar = LocalJar.current
    val tag = data.update ?: return
    Block(Modifier.testTag("update_banner")) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f)) {
                Text(ctx.getString(R.string.ui_update_title, tag), color = jar.colors.ink, fontSize = 15.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                    fontFamily = jar.font)
                if (data.whatsNew.isNotEmpty()) Text(data.whatsNew, color = jar.colors.muted, fontSize = 13.sp, fontFamily = jar.font, maxLines = 3)
            }
            MainButton(stringResource(R.string.update_install), Modifier.width(110.dp)) { actions.installUpdate() }
        }
    }
}
