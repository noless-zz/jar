package com.noam.jar

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.Locale

/** Settings → Look: style, light/dark, accent (Calm, Night) or palette (Playful), with a live preview. */
class LookActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val child = !TaskCache(this).iAmParent()
        setContent {
            var look by remember { mutableStateOf(LookPrefs.load(this, child)) }
            JarThemed(look) {
                LookScreen(look, onChange = { look = it }, onSave = { LookPrefs.save(this, look); finish() }, onBack = { finish() })
            }
        }
    }
}

@Composable
private fun LookScreen(look: Look, onChange: (Look) -> Unit, onSave: () -> Unit, onBack: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val hebrew = Locale.getDefault().language.let { it == "iw" || it == "he" }
    Column(Modifier.fillMaxSize().background(c.bg).windowInsetsPadding(WindowInsets.safeDrawing)) {
        Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(44.dp).clip(CircleShape).background(c.surface).clickable(role = Role.Button, onClick = onBack)
                .semantics { contentDescription = "back" }, contentAlignment = Alignment.Center) {
                Icon(JarIcons.Back, null, tint = c.ink, modifier = Modifier.size(20.dp))
            }
            Text(stringResource(R.string.ui_look_title), color = c.ink, fontSize = 24.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 18.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Label(stringResource(R.string.ui_style))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StyleCard(stringResource(R.string.ui_style_calm), Color(0xFFF6F4EF), Accents[look.accent].light, look.style == JarStyle.CALM,
                    Modifier.weight(1f).testTag("style_calm")) { onChange(look.copy(style = JarStyle.CALM)) }
                StyleCard(stringResource(R.string.ui_style_night), Color(0xFF0E1116), Color(0xFF5BE3B0), look.style == JarStyle.NIGHT,
                    Modifier.weight(1f).testTag("style_night")) { onChange(look.copy(style = JarStyle.NIGHT)) }
                StyleCard(stringResource(R.string.ui_style_playful), Palettes[look.palette].ground, Palettes[look.palette].record,
                    look.style == JarStyle.PLAYFUL, Modifier.weight(1f).testTag("style_playful")) { onChange(look.copy(style = JarStyle.PLAYFUL)) }
            }
            if (look.style != JarStyle.PLAYFUL) {
                Label(stringResource(R.string.ui_mode))
                Row(Modifier.clip(RoundedCornerShape(16.dp)).background(c.surface).padding(4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((mode, res) in listOf(JarMode.LIGHT to R.string.ui_mode_light, JarMode.DARK to R.string.ui_mode_dark, JarMode.AUTO to R.string.ui_mode_auto)) {
                        val on = look.mode == mode
                        Box(Modifier.weight(1f).height(44.dp).clip(RoundedCornerShape(12.dp)).background(if (on) c.accent else Color.Transparent)
                            .clickable(role = Role.RadioButton) { onChange(look.copy(mode = mode)) }.semantics { selected = on },
                            contentAlignment = Alignment.Center) {
                            Text(stringResource(res), color = if (on) c.onAccent else c.ink, fontSize = 14.sp, fontFamily = jar.font)
                        }
                    }
                }
                val acc = Accents[look.accent]
                Label(stringResource(R.string.ui_colour, if (hebrew) acc.he else acc.en))
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.surface).padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    for (row in Accents.indices.chunked(8)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            for (i in row) {
                                val a = Accents[i]
                                val shade = if (c.dark) a.dark else a.light
                                val on = look.accent == i
                                Box(Modifier.size(36.dp).clip(CircleShape)
                                    .border(if (on) 3.dp else 0.dp, if (on) shade else Color.Transparent, CircleShape)
                                    .padding(if (on) 5.dp else 0.dp).clip(CircleShape).background(shade)
                                    .clickable(role = Role.RadioButton) { onChange(look.copy(accent = i)) }
                                    .semantics { contentDescription = if (hebrew) a.he else a.en; selected = on })
                            }
                        }
                    }
                }
            } else {
                Label(stringResource(R.string.ui_palette))
                for (row in Palettes.indices.chunked(2)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        for (i in row) {
                            val p = Palettes[i]
                            val on = look.palette == i
                            Row(Modifier.weight(1f).height(64.dp).clip(RoundedCornerShape(18.dp)).background(p.ground)
                                .border(if (on) 3.dp else 2.dp, Color(0xFF23201A), RoundedCornerShape(18.dp))
                                .clickable(role = Role.RadioButton) { onChange(look.copy(palette = i)) }.semantics { selected = on }
                                .padding(horizontal = 14.dp),
                                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(if (hebrew) p.he else p.en, color = Color(0xFF23201A), fontSize = 15.sp, fontFamily = jar.font)
                                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                    for (col in listOf(p.highlight, p.record)) Box(Modifier.size(18.dp).clip(CircleShape).background(col)
                                        .border(2.dp, Color(0xFF23201A), CircleShape))
                                }
                            }
                        }
                    }
                }
                Text(stringResource(R.string.ui_palette_note), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
            }
            Label(stringResource(R.string.ui_preview))
            Preview()
        }
        Box(Modifier.padding(16.dp).fillMaxWidth().height(54.dp).clip(RoundedCornerShape(27.dp))
            .background(if (jar.style == JarStyle.PLAYFUL) c.record else c.accent)
            .clickable(role = Role.Button, onClick = onSave).testTag("save"), contentAlignment = Alignment.Center) {
            Text(stringResource(R.string.ui_save), color = if (jar.style == JarStyle.PLAYFUL) c.onRecord else c.onAccent,
                fontSize = 16.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
        }
    }
}

@Composable
private fun Label(text: String) {
    val jar = LocalJar.current
    Text(text, color = jar.colors.muted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
}

@Composable
private fun StyleCard(label: String, ground: Color, dot: Color, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val shape = RoundedCornerShape(18.dp)
    Column(modifier.height(100.dp).clip(shape).background(c.surface)
        .border(if (selected) 2.dp else 1.dp, if (selected) c.accent.takeIf { jar.style != JarStyle.PLAYFUL } ?: c.ink else c.line, shape)
        .clickable(role = Role.RadioButton, onClick = onClick).semantics { this.selected = selected },
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Box(Modifier.size(48.dp, 32.dp).clip(RoundedCornerShape(10.dp)).background(ground).border(1.dp, Color(0x26000000), RoundedCornerShape(10.dp)),
            contentAlignment = Alignment.Center) {
            Box(Modifier.size(14.dp).clip(CircleShape).background(dot))
        }
        Text(label, color = c.ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font, modifier = Modifier.padding(top = 8.dp))
    }
}

/** One sample task, drawn with the look being chosen. */
@Composable
private fun Preview() {
    val jar = LocalJar.current
    val c = jar.colors
    val playful = jar.style == JarStyle.PLAYFUL
    val shape = RoundedCornerShape(jar.shape.card)
    Row(Modifier.fillMaxWidth().clip(shape).background(c.surface)
        .then(if (jar.shape.outline > 0.dp) Modifier.border(jar.shape.outline, jar.shape.outlineColor, shape) else Modifier).padding(14.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(26.dp).clip(CircleShape).border(if (playful) 3.dp else 2.dp, if (playful) c.ink else c.accent, CircleShape))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(stringResource(R.string.ui_preview_task), color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Medium, fontFamily = jar.font)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(stringResource(R.string.when_today) + " 18:00", color = c.ink, fontSize = 12.sp, fontFamily = jar.font,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(c.surface2).padding(horizontal = 8.dp, vertical = 3.dp))
                Text(stringResource(R.string.ui_coins, 6), color = c.onAccent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(c.accent).padding(horizontal = 8.dp, vertical = 3.dp))
            }
        }
    }
}
