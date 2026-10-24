package com.noam.jar

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Pieces the screens over the tabs share, each drawn in the person's style. */

/** "📌 Pick…" → "Pick…": the classic screen's emoji prefixes don't belong in the new design. */
fun plain(s: String): String = s.replace(Regex("^[^\\p{L}\\p{N}]+"), "")

/** A screen over the tabs: a back button, a title in the style's voice and a list. */
@Composable
fun SubScreen(title: String, tag: String, sub: String? = null, content: LazyListScope.() -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    LazyColumn(Modifier.fillMaxSize().testTag(tag), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 40.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item(key = "sub_title") {
            Column(Modifier.padding(top = 14.dp, bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                BackButton { actions.back() }
                Column(Modifier.padding(horizontal = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(title, color = c.ink, fontSize = when (jar.style) { JarStyle.NIGHT -> 32.sp; JarStyle.PLAYFUL -> 28.sp; JarStyle.CALM -> 26.sp },
                        fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.ExtraBold else FontWeight.Bold, fontFamily = jar.display)
                    if (sub != null) Text(sub, color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
                }
            }
        }
        content()
    }
}

@Composable
fun BackButton(onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val back = androidx.compose.ui.res.stringResource(R.string.ui_back)
    val m = Modifier.size(44.dp).semantics { contentDescription = back }
    val shaped = when (jar.style) {
        JarStyle.CALM -> m.clip(CircleShape).background(c.surface)
        JarStyle.NIGHT -> m.clip(RoundedCornerShape(14.dp)).border(1.dp, c.line, RoundedCornerShape(14.dp))
        JarStyle.PLAYFUL -> m.clip(CircleShape).background(c.surface).border(2.dp, c.ink, CircleShape)
    }
    Box(shaped.clickable(role = Role.Button, onClick = onClick).testTag("back"), contentAlignment = Alignment.Center) {
        Icon(JarIcons.Back, null, tint = c.ink, modifier = Modifier.size(20.dp))
    }
}

/**
 * Rows of a list: Calm puts them in one soft card with dividers; Night and Playful give each its own card
 * (the same split as the task list, so the styles keep their character on every screen).
 */
fun <T> LazyListScope.rows(key: String, list: List<T>, id: (T) -> String, row: @Composable (T) -> Unit) {
    if (list.isEmpty()) return
    item(key = "rows_$key") {
        val jar = LocalJar.current
        if (jar.style == JarStyle.CALM) {
            Block {
                Column {
                    list.forEachIndexed { i, x ->
                        if (i > 0) HorizontalDivider(color = jar.colors.line)
                        row(x)
                    }
                }
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { for (x in list) androidx.compose.runtime.key(id(x)) { Block { row(x) } } }
        }
    }
}

/** A choice: Calm fills it softly, Night outlines it in the accent, Playful gives it an ink border and the highlight. */
@Composable
fun ChoiceChip(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(if (jar.style == JarStyle.NIGHT) 12.dp else 18.dp)
    val (bg, fg, border) = when (jar.style) {
        JarStyle.CALM -> Triple(if (selected) c.accent else c.surface, if (selected) c.onAccent else c.ink, if (selected) Color.Transparent else c.line)
        JarStyle.NIGHT -> Triple(if (selected) c.accentSoft else Color.Transparent, if (selected) c.onAccentSoft else c.ink, if (selected) c.accent else c.line)
        JarStyle.PLAYFUL -> Triple(if (selected) c.accent else c.surface, c.ink, c.ink)
    }
    Text(label, color = fg, fontSize = 14.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal, fontFamily = jar.font, maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = modifier.heightIn(min = 40.dp).clip(shape).background(bg)
            .border(if (jar.style == JarStyle.PLAYFUL) 2.dp else 1.dp, border, shape)
            .semantics { this.selected = selected }
            .clickable(role = Role.Checkbox, onClick = onClick).padding(horizontal = 14.dp, vertical = 10.dp))
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun ChipRow(content: @Composable () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
}

/** A labelled group on a form; Night writes the label small and spaced out, like a dashboard. */
@Composable
fun FormLabel(text: String) {
    val jar = LocalJar.current
    val c = jar.colors
    if (jar.style == JarStyle.NIGHT)
        Text(text.uppercase(), color = c.muted, fontSize = 12.sp, letterSpacing = 1.2.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
    else Text(text, color = c.ink, fontSize = if (jar.style == JarStyle.PLAYFUL) 17.sp else 15.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
}

@Composable
fun JarField(value: String, onChange: (String) -> Unit, label: String, modifier: Modifier = Modifier, minLines: Int = 1, singleLine: Boolean = false) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    OutlinedTextField(value, onChange, modifier.fillMaxWidth(), label = { Text(label, fontFamily = jar.font) }, minLines = minLines, singleLine = singleLine,
        textStyle = TextStyle(fontFamily = jar.font, fontSize = 17.sp, color = c.ink),
        shape = RoundedCornerShape(if (jar.style == JarStyle.NIGHT) 14.dp else 18.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = if (playful) c.ink else c.accent, unfocusedBorderColor = if (playful) c.ink else c.line,
            focusedLabelColor = if (playful) c.ink else c.accent, unfocusedLabelColor = c.muted, cursorColor = c.ink,
            focusedContainerColor = c.surface, unfocusedContainerColor = c.surface,
        ))
}

/** The one main button of a sheet: Calm a filled pill, Night a glowing accent bar, Playful the record colour with an ink shadow. */
@Composable
fun MainButton(label: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(when (jar.style) { JarStyle.CALM -> 28.dp; JarStyle.NIGHT -> 16.dp; JarStyle.PLAYFUL -> 20.dp })
    val bg = if (jar.style == JarStyle.PLAYFUL) c.record else c.accent
    val fg = if (jar.style == JarStyle.PLAYFUL) c.onRecord else c.onAccent
    Box(modifier.fillMaxWidth()) {
        if (jar.style == JarStyle.PLAYFUL) Box(Modifier.matchParentSize().offset(4.dp, 4.dp).clip(shape).background(c.ink))
        Box(Modifier.fillMaxWidth().height(56.dp).clip(shape).background(if (enabled) bg else c.surface2)
            .then(if (jar.style == JarStyle.PLAYFUL) Modifier.border(2.dp, c.ink, shape) else Modifier)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick), contentAlignment = Alignment.Center) {
            Text(label, color = if (enabled) fg else c.muted, fontSize = 17.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        }
    }
}

/** A secondary button: outlined in every style (ink in Playful). */
@Composable
fun SideButton(label: String, modifier: Modifier = Modifier, danger: Boolean = false, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(if (jar.style == JarStyle.NIGHT) 16.dp else 26.dp)
    Box(modifier.fillMaxWidth().height(52.dp).clip(shape).background(c.surface)
        .border(if (playful) 2.dp else 1.dp, if (playful) c.ink else if (danger) c.danger.copy(alpha = 0.5f) else c.line, shape)
        .clickable(role = Role.Button, onClick = onClick), contentAlignment = Alignment.Center) {
        Text(label, color = if (danger) c.danger else c.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
    }
}

/** A row in an action list (the task's "All actions", a series' menu): icon, label, and a tone for risky ones. */
@Composable
fun ActionRow(icon: ImageVector, label: String, danger: Boolean = false, tag: String? = null, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val tint = if (danger) c.danger else c.ink
    Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onClick)
        .then(if (tag != null) Modifier.testTag(tag) else Modifier).padding(horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        val box = Modifier.size(36.dp)
        Box(when (jar.style) {
            JarStyle.CALM -> box.clip(CircleShape).background(if (danger) c.dangerSoft else c.accentSoft)
            JarStyle.NIGHT -> box.clip(RoundedCornerShape(10.dp)).border(1.dp, if (danger) c.danger.copy(alpha = 0.5f) else c.line, RoundedCornerShape(10.dp))
            JarStyle.PLAYFUL -> box.clip(RoundedCornerShape(12.dp)).background(if (danger) c.dangerSoft else c.surface2).border(2.dp, c.ink, RoundedCornerShape(12.dp))
        }, contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = if (danger) c.danger else if (jar.style == JarStyle.CALM) c.onAccentSoft else c.ink, modifier = Modifier.size(18.dp))
        }
        Text(label, color = tint, fontSize = 16.sp, fontFamily = jar.font, modifier = Modifier.weight(1f))
    }
}

/** Sheet content padding and spacing, shared by every sheet. */
@Composable
fun SheetColumn(tag: String? = null, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 28.dp).then(if (tag != null) Modifier.testTag(tag) else Modifier),
        verticalArrangement = Arrangement.spacedBy(16.dp)) { content() }
}

@Composable
fun SheetTitle(text: String, sub: String? = null) {
    val jar = LocalJar.current
    val c = jar.colors
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(text, color = c.ink, fontSize = if (jar.style == JarStyle.NIGHT) 26.sp else 24.sp,
            fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.ExtraBold else FontWeight.Bold, fontFamily = jar.display)
        if (sub != null) Text(sub, color = c.muted, fontSize = 14.sp, fontFamily = jar.font)
    }
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    val jar = LocalJar.current
    Text(text, color = jar.colors.muted, fontSize = 14.sp, fontFamily = jar.font, modifier = modifier)
}
