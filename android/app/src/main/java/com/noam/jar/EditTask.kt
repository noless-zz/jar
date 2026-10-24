package com.noam.jar

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.noam.jar.core.TaskLists
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

private val DayKeys = listOf("sun", "mon", "tue", "wed", "thu", "fri", "sat")

/**
 * New task, edit, or "make it repeat": what, for whom (one of them / each of them / taking turns), repeats?, and when.
 * The same choices as the classic dialog, as one sheet.
 */
@Composable
fun EditTaskSheet(req: EditReq, data: HomeData, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val actions = LocalActions.current
    val existing = req.task
    val me = data.me
    val names = remember(data) { data.names.ifEmpty { mapOf(me to data.myName) } }
    var title by remember { mutableStateOf(existing?.title ?: "") }
    val people = remember { mutableStateListOf<String>().apply { if (existing == null) add(me) else addAll(existing.owners()) } }
    var mode by remember { mutableStateOf(if (existing?.eachMust() == true) "all" else "any") }
    val mayRepeat = existing == null || data.canMakeRepeat(existing)
    var repeat by remember { mutableStateOf(if (req.repeat) "daily" else "once") }
    val days = remember { mutableStateListOf<String>() }
    var repeatAt by remember { mutableStateOf("") }
    var whenValue by remember { mutableStateOf(existing?.due ?: "") }
    var picked by remember { mutableStateOf<String?>(null) }
    var dialog by remember { mutableStateOf<String?>(null) }
    val now = System.currentTimeMillis()
    val tz = TimeZone.getDefault()
    val repeating = mayRepeat && repeat != "once"
    if (!repeating && mode == "turns") mode = "any"

    SheetColumn("edit_sheet") {
        SheetTitle(when {
            existing == null -> stringResource(R.string.add_title)
            req.repeat -> plain(stringResource(R.string.make_repeat))
            else -> stringResource(R.string.edit_title)
        })
        JarField(title, { title = it }, stringResource(R.string.add_what), Modifier.testTag("add_title"))

        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FormLabel(stringResource(R.string.add_for))
            ChipRow {
                for ((id, name) in names) {
                    ChoiceChip(if (id == me) stringResource(R.string.add_me) else name, id in people, Modifier.testTag("person_$id")) {
                        if (id in people) people.remove(id) else people.add(id)
                    }
                }
            }
            if (!data.parent && people.any { it != me }) Muted(stringResource(R.string.add_request_hint))
        }
        if (people.size > 1) Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FormLabel(stringResource(R.string.add_mode))
            ChipRow {
                ChoiceChip(stringResource(R.string.add_mode_any), mode == "any") { mode = "any" }
                ChoiceChip(stringResource(R.string.add_mode_all), mode == "all") { mode = "all" }
                if (repeating) ChoiceChip(stringResource(R.string.add_mode_turns), mode == "turns") { mode = "turns" }
            }
        }
        if (mayRepeat) Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FormLabel(stringResource(R.string.add_repeat))
            ChipRow {
                for ((key, label) in listOf("once" to R.string.repeat_once, "daily" to R.string.repeat_daily, "days" to R.string.repeat_days,
                    "weekly" to R.string.repeat_weekly, "monthly" to R.string.repeat_monthly)) {
                    ChoiceChip(stringResource(label), repeat == key) { repeat = key }
                }
            }
            if (repeat == "days") {
                val short = stringArrayResource(R.array.week_days_short)
                ChipRow {
                    DayKeys.forEachIndexed { i, k -> ChoiceChip(short[i], k in days) { if (k in days) days.remove(k) else days.add(k) } }
                }
            }
            if (repeating) ChipRow {
                ChoiceChip(if (repeatAt.isEmpty()) plain(stringResource(R.string.repeat_time)) else plain(ctx.getString(R.string.repeat_at, repeatAt)),
                    repeatAt.isNotEmpty()) { dialog = "time" }
            }
        }
        if (!repeating) Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FormLabel(stringResource(R.string.add_when))
            ChipRow {
                ChoiceChip(stringResource(R.string.when_none), whenValue.isEmpty()) { whenValue = "" }
                val due = existing?.due
                if (due != null) ChoiceChip(TaskFormat.`when`(ctx, due), whenValue == due) { whenValue = due }
                TaskLists.tonight(now, tz)?.let { t -> ChoiceChip(stringResource(R.string.when_tonight), whenValue == t) { whenValue = t } }
                val tomorrow = TaskLists.tomorrowMorning(now, tz)
                ChoiceChip(stringResource(R.string.when_tomorrow_morning), whenValue == tomorrow) { whenValue = tomorrow }
                val p = picked
                ChoiceChip(if (p == null) stringResource(R.string.when_pick) else TaskFormat.`when`(ctx, p), p != null && whenValue == p) { dialog = "when" }
            }
        }
        MainButton(stringResource(if (existing == null) R.string.add_save else R.string.ui_save), Modifier.testTag("add_save"),
            enabled = title.isNotBlank()) {
            val text = title.trim()
            val who = (names.keys.filter { it in people } + people.filter { it !in names }).distinct().ifEmpty { listOf(me) }
            val each = who.size > 1 && mode == "all"
            val rotate = who.size > 1 && mode == "turns"
            val rule = if (!repeating) null else when (repeat) {
                "daily" -> "daily"; "weekly" -> "weekly"; "monthly" -> "monthly"
                else -> if (days.isEmpty()) "weekly" else "weekly:" + DayKeys.filter { it in days }.joinToString(",")
            }
            val due = whenValue.ifEmpty { null }
            val prefs = Prefs(ctx)
            actions.call(if (existing == null) R.string.add_failed else R.string.edit_failed, ctx) {
                when {
                    existing == null && rule != null -> TaskApi.createRecurring(prefs, text, who, each, rule, repeatAt, rotate)
                    existing == null -> TaskApi.create(prefs, text, who, each, due)
                    rule != null -> {
                        TaskApi.edit(prefs, existing.id, text, who, each, due)
                        TaskApi.makeRecurring(prefs, existing.id, rule, repeatAt, rotate)
                    }
                    else -> TaskApi.edit(prefs, existing.id, text, who, each, due)
                }
            }
            onClose()
        }
    }
    when (dialog) {
        "time" -> WhenDialog(timeOnly = true, hour = 20, onDismiss = { dialog = null }) { repeatAt = it; dialog = null }
        "when" -> WhenDialog(timeOnly = false, hour = 8, onDismiss = { dialog = null }) { picked = it; whenValue = it; dialog = null }
    }
}

/** A day, then a time (24 h). Gives "yyyy-MM-ddTHH:mm" in the phone's time zone, or "HH:mm" with [timeOnly]. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WhenDialog(timeOnly: Boolean, hour: Int, onDismiss: () -> Unit, onPicked: (String) -> Unit) {
    var day by remember { mutableStateOf(if (timeOnly) "" else null as String?) }
    val ok = stringResource(android.R.string.ok)
    val cancel = stringResource(android.R.string.cancel)
    val d = day
    if (d == null) {
        val state = rememberDatePickerState(initialSelectedDateMillis = System.currentTimeMillis())
        DatePickerDialog(onDismissRequest = onDismiss,
            confirmButton = {
                TextButton(onClick = {
                    val ms = state.selectedDateMillis ?: return@TextButton
                    val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = ms }
                    day = String.format(Locale.US, "%04d-%02d-%02d", utc.get(Calendar.YEAR), utc.get(Calendar.MONTH) + 1, utc.get(Calendar.DAY_OF_MONTH))
                }) { Text(ok) }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text(cancel) } }) { DatePicker(state) }
    } else {
        val state = rememberTimePickerState(hour, 0, true)
        AlertDialog(onDismissRequest = onDismiss,
            title = { Text(stringResource(R.string.pick_time)) },
            text = { TimePicker(state) },
            confirmButton = {
                TextButton(onClick = {
                    val hm = String.format(Locale.US, "%02d:%02d", state.hour, state.minute)
                    onPicked(if (timeOnly) hm else "${d}T$hm")
                }) { Text(ok) }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text(cancel) } })
    }
}
