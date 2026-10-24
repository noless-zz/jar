package com.noam.jar

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.animation.core.withInfiniteAnimationFrameMillis

// ---------------------------------------------------------------- the bottom bar

/**
 * Calm: a labelled bar with a pill on the current tab. Night: no bar, icon-only squares and a glowing orb.
 * Playful: a dark floating capsule. The record button sits in the middle of all three.
 */
@Composable
fun BottomBar(modifier: Modifier, tab: Tab, parent: Boolean, recording: Boolean, onTab: (Tab) -> Unit, onRecord: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val items = buildList {
        add(Triple(Tab.TASKS, JarIcons.Tasks, R.string.ui_nav_tasks))
        if (parent) add(Triple(Tab.FAMILY, JarIcons.Family, R.string.ui_nav_family))
        add(Triple(Tab.BOARD, JarIcons.Trophy, R.string.ui_nav_board))
        add(Triple(Tab.IDEAS, JarIcons.Idea, R.string.ui_nav_ideas))
    }
    val half = (items.size + 1) / 2
    val recLabel = ctx.getString(if (recording) R.string.ui_nav_stop else R.string.ui_nav_record)
    when (jar.style) {
        JarStyle.NIGHT -> Row(modifier.fillMaxWidth().height(104.dp).padding(horizontal = 18.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
            items.take(half).forEach { (t, icon, res) -> Slot { NightNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
            Slot { Orb(recording, recLabel, onRecord) }
            items.drop(half).forEach { (t, icon, res) -> Slot { NightNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
        }
        JarStyle.PLAYFUL -> Box(modifier.fillMaxWidth().padding(14.dp), contentAlignment = Alignment.Center) {
            Row(Modifier.fillMaxWidth().height(72.dp).clip(RoundedCornerShape(26.dp)).background(c.ink),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceAround) {
                items.take(half).forEach { (t, icon, res) -> Slot { PlayfulNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
                Slot { Spacer(Modifier.width(60.dp)) }
                items.drop(half).forEach { (t, icon, res) -> Slot { PlayfulNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
            }
            RecordButton(recording, recLabel, 60.dp, c.record, c.onRecord, Modifier.border(3.dp, c.bg, CircleShape), onRecord)
        }
        JarStyle.CALM -> Box(modifier.fillMaxWidth(), contentAlignment = Alignment.BottomCenter) {
            Row(Modifier.fillMaxWidth().height(80.dp).background(c.surface).border(1.dp, c.line),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceAround) {
                items.take(half).forEach { (t, icon, res) -> Slot { CalmNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
                Slot { Spacer(Modifier.width(72.dp)) }
                items.drop(half).forEach { (t, icon, res) -> Slot { CalmNav(icon, ctx.getString(res), t == tab) { onTab(t) } } }
            }
            RecordButton(recording, recLabel, 66.dp, c.record, c.onRecord,
                Modifier.padding(bottom = 34.dp).shadow(8.dp, CircleShape), onRecord)
        }
    }
}

/** An equal share of the bar, so the items sit evenly around the record button whatever their width. */
@Composable
private fun androidx.compose.foundation.layout.RowScope.Slot(content: @Composable () -> Unit) {
    Box(Modifier.weight(1f), contentAlignment = Alignment.Center) { content() }
}

@Composable
private fun RecordButton(recording: Boolean, label: String, size: androidx.compose.ui.unit.Dp, bg: Color, fg: Color, modifier: Modifier, onClick: () -> Unit) {
    Box(modifier.size(size).clip(CircleShape).background(if (recording) Color(0xFFC2402E) else bg)
        .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label }.testTag("record"),
        contentAlignment = Alignment.Center) {
        Icon(if (recording) JarIcons.Stop else JarIcons.Mic, null, tint = if (recording) Color.White else fg, modifier = Modifier.size(size * 0.42f))
    }
}

/** Night's voice orb: a gradient sphere with a soft halo that breathes. */
@Composable
private fun Orb(recording: Boolean, label: String, onClick: () -> Unit) {
    val c = LocalJar.current.colors
    val pulse by rememberInfiniteTransition(label = "orb").animateFloat(1f, 1.08f,
        infiniteRepeatable(tween(1800, easing = LinearEasing), RepeatMode.Reverse), label = "halo")
    Box(contentAlignment = Alignment.Center) {
        Box(Modifier.size(92.dp).scale(pulse).clip(CircleShape).background(c.accent.copy(alpha = 0.14f)))
        Box(Modifier.size(76.dp).clip(CircleShape)
            .background(if (recording) Brush.radialGradient(listOf(Color(0xFFFF9A90), Color(0xFFC2402E)))
            else Brush.radialGradient(listOf(Color.White.copy(alpha = 0.85f), c.accent, c.accent.copy(alpha = 0.8f))))
            .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label }.testTag("record"),
            contentAlignment = Alignment.Center) {
            Icon(if (recording) JarIcons.Stop else JarIcons.Mic, null, tint = if (recording) Color.White else c.onRecord, modifier = Modifier.size(30.dp))
        }
    }
}

@Composable
private fun NightNav(icon: ImageVector, label: String, selected: Boolean, onClick: () -> Unit) {
    val c = LocalJar.current.colors
    Box(Modifier.size(48.dp).clip(RoundedCornerShape(16.dp)).background(if (selected) c.surface2 else Color.Transparent)
        .clickable(role = Role.Tab, onClick = onClick).semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = if (selected) c.ink else c.muted, modifier = Modifier.size(22.dp))
    }
}

@Composable
private fun CalmNav(icon: ImageVector, label: String, selected: Boolean, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    Column(Modifier.clip(RoundedCornerShape(16.dp)).clickable(role = Role.Tab, onClick = onClick).padding(horizontal = 6.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.width(56.dp).height(30.dp).clip(RoundedCornerShape(15.dp)).background(if (selected) c.accentSoft else Color.Transparent),
            contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = if (selected) c.onAccentSoft else c.muted, modifier = Modifier.size(20.dp))
        }
        Text(label, color = if (selected) c.onAccentSoft else c.muted, fontSize = 12.sp, fontFamily = jar.font,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

@Composable
private fun PlayfulNav(icon: ImageVector, label: String, selected: Boolean, onClick: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    Box(Modifier.size(width = 54.dp, height = 46.dp).clip(RoundedCornerShape(18.dp)).background(if (selected) c.accent else Color.Transparent)
        .clickable(role = Role.Tab, onClick = onClick).semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = if (selected) c.ink else c.bg, modifier = Modifier.size(22.dp))
    }
}

// ---------------------------------------------------------------- finishing a task

/**
 * Calm: a dark snackbar "+12 · Nice! 2 left for today · Undo". Night: a glowing ring with the coins, then a
 * quiet line with Undo. Playful: a full-screen sticker "+8 coins, well done!" with the streak.
 */
@Composable
fun DoneOverlay(m: DoneMoment, modifier: Modifier) {
    val jar = LocalJar.current
    val actions = LocalActions.current
    LaunchedEffect(m.id) {
        // Frame-clock timer rather than delay(): tests suspend it (so they can see the moment), the app doesn't.
        val until = System.currentTimeMillis() + if (jar.style == JarStyle.PLAYFUL) 6000 else 4000
        while (System.currentTimeMillis() < until) withInfiniteAnimationFrameMillis { }
        actions.dismissMoment()
    }
    when (jar.style) {
        JarStyle.PLAYFUL -> PlayfulDone(m)
        JarStyle.NIGHT -> Box(Modifier.fillMaxSize()) {
            NightRing(m, Modifier.align(Alignment.Center))
            Snack(m, modifier.align(Alignment.BottomCenter).padding(start = 18.dp, end = 18.dp, bottom = 118.dp), ring = false)
        }
        JarStyle.CALM -> Box(Modifier.fillMaxSize()) {
            Snack(m, modifier.align(Alignment.BottomCenter).padding(start = 16.dp, end = 16.dp, bottom = 100.dp), ring = true)
        }
    }
}

@Composable
private fun Snack(m: DoneMoment, modifier: Modifier, ring: Boolean) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val night = jar.style == JarStyle.NIGHT
    val text = if (m.leftToday > 0) stringResource(R.string.ui_done_left, m.leftToday) else stringResource(R.string.ui_done_all)
    Row(modifier.fillMaxWidth().clip(RoundedCornerShape(if (night) 16.dp else 18.dp))
        .background(if (night) c.surface2 else Color(0xFF1C2420)).then(if (night) Modifier.border(1.dp, c.line, RoundedCornerShape(16.dp)) else Modifier)
        .padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp).testTag("done_moment"),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        if (ring && m.coins > 0) Box(Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFF2C46B)), contentAlignment = Alignment.Center) {
            Text("+${m.coins}", color = Color(0xFF4A2E00), fontSize = 13.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.font)
        }
        Column(Modifier.weight(1f)) {
            Text(text, color = if (night) c.ink else Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
            if (!night && m.weekCoins > 0) Text(stringResource(R.string.ui_week_coins, m.weekCoins + m.coins), color = Color(0xFFC9D2CD), fontSize = 13.sp, fontFamily = jar.font)
        }
        Text(stringResource(R.string.ui_undo), color = if (night) c.accent else Color(0xFF9FE0C2), fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            fontFamily = jar.font, modifier = Modifier.clip(RoundedCornerShape(20.dp)).clickable(role = Role.Button) { actions.undo(m) }
                .padding(horizontal = 12.dp, vertical = 10.dp))
    }
}

@Composable
private fun NightRing(m: DoneMoment, modifier: Modifier) {
    val jar = LocalJar.current
    val c = jar.colors
    val grow = remember(m.id) { Animatable(0.6f) }
    LaunchedEffect(m.id) { grow.animateTo(1f, tween(500)) }
    Box(modifier.size(170.dp).scale(grow.value).alpha(grow.value), contentAlignment = Alignment.Center) {
        Box(Modifier.size(170.dp).clip(CircleShape).border(2.dp, c.accent.copy(alpha = 0.25f), CircleShape))
        Box(Modifier.size(128.dp).clip(CircleShape).background(c.bg.copy(alpha = 0.92f)).border(2.dp, c.accent.copy(alpha = 0.6f), CircleShape),
            contentAlignment = Alignment.Center) {
            if (m.coins > 0) Text("+${m.coins}", color = c.coin, fontSize = 36.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
            else Icon(JarIcons.Check, null, tint = c.accent, modifier = Modifier.size(48.dp))
        }
    }
}

@Composable
private fun PlayfulDone(m: DoneMoment) {
    val jar = LocalJar.current
    val c = jar.colors
    val actions = LocalActions.current
    val pop = remember(m.id) { Animatable(0.5f) }
    LaunchedEffect(m.id) { pop.animateTo(1f, tween(350)) }
    Box(Modifier.fillMaxSize().background(c.bg).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
        .padding(24.dp).testTag("done_moment"), contentAlignment = Alignment.Center) {
        Confetti()
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(24.dp)) {
            Box(Modifier.scale(pop.value)) {
                Box(Modifier.size(180.dp).offset(6.dp, 6.dp).clip(CircleShape).background(c.ink))
                Column(Modifier.size(180.dp).clip(CircleShape).background(c.accent).border(4.dp, c.ink, CircleShape),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                    Text(if (m.coins > 0) "+${m.coins}" else "✓", color = c.ink, fontSize = 60.sp, fontWeight = FontWeight.ExtraBold, fontFamily = jar.display)
                    if (m.coins > 0) Text(stringResource(R.string.ui_coins, m.coins).replace("${m.coins}", "").trim(), color = c.ink, fontSize = 16.sp,
                        fontWeight = FontWeight.Bold, fontFamily = jar.display)
                }
            }
            Text(stringResource(R.string.ui_well_done, m.name), color = c.ink, fontSize = 32.sp, fontWeight = FontWeight.ExtraBold,
                fontFamily = jar.display, textAlign = TextAlign.Center)
            Text(m.task.title, color = c.ink, fontSize = 18.sp, fontFamily = jar.font, textAlign = TextAlign.Center)
            if (m.streak >= 2) Row(Modifier.clip(RoundedCornerShape(22.dp)).background(c.surface).border(2.dp, c.ink, RoundedCornerShape(22.dp))
                .padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(JarIcons.Fire, null, tint = c.ink, modifier = Modifier.size(22.dp))
                Text(LocalContext.current.getString(R.string.board_streak, m.streak).replace("🔥", "").trim(), color = c.ink, fontSize = 17.sp,
                    fontWeight = FontWeight.Bold, fontFamily = jar.display)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(Modifier.height(58.dp).clip(RoundedCornerShape(20.dp)).background(c.ink).clickable(role = Role.Button) { actions.dismissMoment() }
                    .padding(horizontal = 36.dp), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.ui_yes), color = c.bg, fontSize = 18.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                }
                Box(Modifier.height(58.dp).clip(RoundedCornerShape(20.dp)).border(2.dp, c.ink, RoundedCornerShape(20.dp)).clickable(role = Role.Button) { actions.undo(m) }
                    .padding(horizontal = 20.dp), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.ui_undo), color = c.ink, fontSize = 16.sp, fontWeight = FontWeight.Bold, fontFamily = jar.display)
                }
            }
        }
    }
}

/** A few outlined shapes scattered around, in the family's colours. */
@Composable
private fun Confetti() {
    val c = LocalJar.current.colors
    Box(Modifier.fillMaxSize()) {
        val bits = listOf(
            Triple(0.12f, 0.10f, PersonColors[2]), Triple(0.78f, 0.14f, PersonColors[0]), Triple(0.30f, 0.06f, c.accent),
            Triple(0.85f, 0.70f, PersonColors[1]), Triple(0.10f, 0.78f, PersonColors[3]), Triple(0.62f, 0.86f, c.accent),
        )
        androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxSize()) {
            for ((i, b) in bits.withIndex()) {
                Box(Modifier.offset(maxWidth * b.first, maxHeight * b.second).size(if (i % 2 == 0) 20.dp else 16.dp)
                    .clip(if (i % 3 == 0) CircleShape else RoundedCornerShape(3.dp)).background(b.third).border(2.dp, c.ink, if (i % 3 == 0) CircleShape else RoundedCornerShape(3.dp)))
            }
        }
    }
}

// ---------------------------------------------------------------- recording

/** While recording: a full screen in the look's style with the timer and one big "stop and send". */
@Composable
fun RecordOverlay(onStop: () -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    var ms by remember { mutableLongStateOf(RecorderService.elapsedMs()) }
    LaunchedEffect(Unit) { while (true) withInfiniteAnimationFrameMillis { ms = RecorderService.elapsedMs() } }
    val time = "%d:%02d".format(ms / 60000, (ms / 1000) % 60)
    val playful = jar.style == JarStyle.PLAYFUL
    val night = jar.style == JarStyle.NIGHT
    val bg = if (playful) c.record else c.bg
    val fg = if (playful) Color.White else c.ink
    val breathe by rememberInfiniteTransition(label = "rec").animateFloat(0.92f, 1.06f,
        infiniteRepeatable(tween(900, easing = LinearEasing), RepeatMode.Reverse), label = "breathe")
    Column(Modifier.fillMaxSize().background(bg).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
        .padding(24.dp).testTag("record_overlay"), horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 12.dp)) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(if (playful) Color.White else Color(0xFFE5483A)))
            Text(stringResource(R.string.ui_recording, time), color = fg, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
        }
        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
            when {
                night -> Box(contentAlignment = Alignment.Center) {
                    Box(Modifier.size(300.dp).clip(CircleShape).border(1.dp, c.accent.copy(alpha = 0.15f), CircleShape))
                    Box(Modifier.size(236.dp).scale(breathe).clip(CircleShape).border(1.dp, c.accent.copy(alpha = 0.35f), CircleShape))
                    Box(Modifier.size(176.dp).scale(breathe).shadow(40.dp, CircleShape, ambientColor = c.accent, spotColor = c.accent).clip(CircleShape)
                        .background(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.85f), c.accent, c.accent.copy(alpha = 0.75f)))),
                        contentAlignment = Alignment.Center) { Icon(JarIcons.Mic, null, tint = c.onRecord, modifier = Modifier.size(56.dp)) }
                }
                playful -> Box(contentAlignment = Alignment.Center) {
                    Box(Modifier.size(210.dp).offset(6.dp, 6.dp).clip(CircleShape).background(c.ink))
                    Box(Modifier.size(210.dp).scale(breathe).clip(CircleShape).background(Color.White).border(4.dp, c.ink, CircleShape),
                        contentAlignment = Alignment.Center) { Icon(JarIcons.Mic, null, tint = c.ink, modifier = Modifier.size(80.dp)) }
                }
                else -> Box(contentAlignment = Alignment.Center) {
                    Box(Modifier.size(260.dp).scale(breathe).clip(CircleShape).background(c.accentSoft))
                    Box(Modifier.size(196.dp).clip(CircleShape).background(c.accent.copy(alpha = 0.22f)))
                    Box(Modifier.size(132.dp).clip(CircleShape).background(c.accent), contentAlignment = Alignment.Center) {
                        Icon(JarIcons.Mic, null, tint = c.onAccent, modifier = Modifier.size(48.dp))
                    }
                }
            }
        }
        Text(stringResource(R.string.ui_looks_like), color = if (playful) Color.White else c.muted, fontSize = 15.sp, fontFamily = jar.font,
            textAlign = TextAlign.Center, modifier = Modifier.padding(bottom = 18.dp))
        val shape = RoundedCornerShape(if (playful) 20.dp else 30.dp)
        Row(Modifier.fillMaxWidth().height(60.dp).clip(shape)
            .background(if (playful) c.ink else if (night) c.ink else c.accent)
            .clickable(role = Role.Button, onClick = onStop).testTag("stop"),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
            Icon(JarIcons.Stop, null, tint = if (playful) Color.White else if (night) c.bg else c.onAccent, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(10.dp))
            Text(stringResource(R.string.ui_nav_stop), color = if (playful) Color.White else if (night) c.bg else c.onAccent, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold, fontFamily = jar.font)
        }
    }
}
