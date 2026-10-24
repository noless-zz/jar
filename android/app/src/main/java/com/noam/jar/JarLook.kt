@file:OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)

package com.noam.jar

import android.content.Context
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * The look each person picks in Settings → Look: a style (Calm, Night, Playful), light/dark,
 * one of 16 accents (Calm and Night) or one of 4 palettes (Playful). Kept on this phone only.
 * The design: claude/jar-ui-redesign.md in the project, and its Design canvas.
 */
enum class JarStyle { CALM, NIGHT, PLAYFUL }

enum class JarMode { LIGHT, DARK, AUTO }

data class Look(val style: JarStyle, val mode: JarMode, val accent: Int, val palette: Int)

object LookPrefs {
    private const val FILE = "jar_look"

    /** Children start on Playful, grown-ups on Calm; both follow the phone's light/dark. */
    fun load(c: Context, child: Boolean): Look {
        val sp = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        val style = runCatching { JarStyle.valueOf(sp.getString("style", null) ?: "") }
            .getOrDefault(if (child) JarStyle.PLAYFUL else JarStyle.CALM)
        val mode = runCatching { JarMode.valueOf(sp.getString("mode", null) ?: "") }.getOrDefault(JarMode.AUTO)
        return Look(style, mode, sp.getInt("accent", 0).coerceIn(0, Accents.size - 1),
            sp.getInt("palette", 0).coerceIn(0, Palettes.size - 1))
    }

    fun save(c: Context, look: Look) {
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit()
            .putString("style", look.style.name).putString("mode", look.mode.name)
            .putInt("accent", look.accent).putInt("palette", look.palette).apply()
    }

    /** The new screens are opt-in while they are being built ("New design (beta)" in the menu). */
    fun newUi(c: Context): Boolean = c.getSharedPreferences(FILE, Context.MODE_PRIVATE).getBoolean("new_ui", false)

    fun setNewUi(c: Context, on: Boolean) {
        c.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putBoolean("new_ui", on).apply()
    }
}

/** An accent: its Hebrew/English name, the shade for light mode and the one for dark mode. */
data class Accent(val he: String, val en: String, val light: Color, val dark: Color)

val Accents = listOf(
    Accent("ירוק Jar", "Jar green", Color(0xFF2E6F57), Color(0xFF6FD3A8)),
    Accent("מנטה", "Mint", Color(0xFF0F7A63), Color(0xFF5BE3B0)),
    Accent("טורקיז", "Teal", Color(0xFF0E7490), Color(0xFF5CC8E0)),
    Accent("שמיים", "Sky", Color(0xFF1D6FB8), Color(0xFF7DB8F5)),
    Accent("כחול", "Blue", Color(0xFF2F55D4), Color(0xFF8DA6FF)),
    Accent("אינדיגו", "Indigo", Color(0xFF4B45C4), Color(0xFFA9A3FF)),
    Accent("סגול", "Violet", Color(0xFF7040C0), Color(0xFFC3A2FF)),
    Accent("שזיף", "Plum", Color(0xFF8A2F80), Color(0xFFE39BD8)),
    Accent("ורוד", "Pink", Color(0xFFB8306E), Color(0xFFFF9CC4)),
    Accent("אדום", "Red", Color(0xFFB3261E), Color(0xFFFF9A90)),
    Accent("אלמוג", "Coral", Color(0xFFB7472A), Color(0xFFFF9E80)),
    Accent("כתום", "Orange", Color(0xFFA85208), Color(0xFFFFB570)),
    Accent("ענבר", "Amber", Color(0xFF8A6100), Color(0xFFFFD27A)),
    Accent("זית", "Olive", Color(0xFF5C6B12), Color(0xFFC9DB6A)),
    Accent("צפחה", "Slate", Color(0xFF44546A), Color(0xFFB5C2D3)),
    Accent("גרפיט", "Graphite", Color(0xFF3A3A3A), Color(0xFFD6D6D6)),
)

/** A Playful palette: the ground, the highlight (coins, the selected tab) and the record button. */
data class Palette(val he: String, val en: String, val ground: Color, val highlight: Color, val record: Color, val chip: Color)

val Palettes = listOf(
    Palette("שמש", "Sun", Color(0xFFFFF4DE), Color(0xFFFFD15C), Color(0xFFFF6B4A), Color(0xFFFFE3CC)),
    Palette("ים", "Sea", Color(0xFFE5F3FF), Color(0xFF7FD3FF), Color(0xFF2459C9), Color(0xFFD3ECFF)),
    Palette("יער", "Forest", Color(0xFFEAF6E4), Color(0xFFB8E986), Color(0xFFE2701C), Color(0xFFD6EFC6)),
    Palette("ממתק", "Candy", Color(0xFFFFE9F3), Color(0xFFFFB3D6), Color(0xFF8A2F80), Color(0xFFFFD6E8)),
)

/** Avatar colours, one per family member in the PC's order (white text passes 4.5:1 on each). */
val PersonColors = listOf(
    Color(0xFF2459C9), Color(0xFF8A2F80), Color(0xFFB4520C), Color(0xFF0F766E),
    Color(0xFF7040C0), Color(0xFFB3261E), Color(0xFF44546A), Color(0xFF5C6B12),
)

/** Everything a screen paints with. One instance per style × mode × accent. */
@Immutable
data class JarColors(
    val bg: Color, val surface: Color, val surface2: Color, val ink: Color, val muted: Color, val line: Color,
    val accent: Color, val onAccent: Color, val accentSoft: Color, val onAccentSoft: Color,
    val danger: Color, val dangerSoft: Color, val coin: Color, val coinSoft: Color,
    val record: Color, val onRecord: Color, val dark: Boolean,
)

@Immutable
data class JarShape(val card: Dp, val outline: Dp, val shadow: Dp, val outlineColor: Color)

@Immutable
data class JarTheme(val style: JarStyle, val colors: JarColors, val shape: JarShape, val font: FontFamily, val display: FontFamily)

val LocalJar = staticCompositionLocalOf<JarTheme> { error("JarTheme not provided") }

private val Heebo = FontFamily(
    listOf(400, 500, 600, 700, 800).map { w ->
        Font(R.font.heebo, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    }
)
private val Plex = FontFamily(
    Font(R.font.plex_hebrew_regular, FontWeight.Normal),
    Font(R.font.plex_hebrew_medium, FontWeight.Medium),
    Font(R.font.plex_hebrew_semibold, FontWeight.SemiBold),
    Font(R.font.plex_hebrew_bold, FontWeight.Bold),
)
private val Rubik = FontFamily(
    listOf(500, 700, 800).map { w ->
        Font(R.font.rubik, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    }
)
private val Varela = FontFamily(Font(R.font.varela_round, FontWeight.Normal))

/** The tokens for a look; [systemDark] is what the phone says when the mode is AUTO. */
fun themeFor(look: Look, systemDark: Boolean): JarTheme {
    val dark = when (look.mode) { JarMode.LIGHT -> false; JarMode.DARK -> true; JarMode.AUTO -> systemDark }
    val acc = Accents[look.accent]
    return when (look.style) {
        JarStyle.PLAYFUL -> {
            val p = Palettes[look.palette]
            val ink = Color(0xFF23201A)
            JarTheme(look.style, JarColors(
                bg = p.ground, surface = Color.White, surface2 = p.chip, ink = ink, muted = Color(0xFF5C5446), line = ink,
                accent = p.highlight, onAccent = ink, accentSoft = p.chip, onAccentSoft = ink,
                danger = Color(0xFFB3261E), dangerSoft = Color(0xFFFBE7E3), coin = Color(0xFF6B4300), coinSoft = Color(0xFFFFD15C),
                record = p.record, onRecord = Color.White, dark = false,
            ), JarShape(card = 22.dp, outline = 2.dp, shadow = 4.dp, outlineColor = ink), Varela, Rubik)
        }
        JarStyle.NIGHT -> if (dark) JarTheme(look.style, JarColors(
            bg = Color(0xFF0E1116), surface = Color(0xFF171C24), surface2 = Color(0xFF1F2631), ink = Color(0xFFEEF2F6),
            muted = Color(0xFF9AA6B5), line = Color(0xFF2A3240),
            accent = acc.dark, onAccent = Color(0xFF0E1116), accentSoft = acc.dark.copy(alpha = 0.16f), onAccentSoft = acc.dark,
            danger = Color(0xFFFF8A7A), dangerSoft = Color(0xFF3A2226), coin = Color(0xFFFFD27A), coinSoft = Color(0xFF2E2614),
            record = acc.dark, onRecord = Color(0xFF06261C), dark = true,
        ), JarShape(18.dp, 1.dp, 0.dp, Color(0xFF2A3240)), Plex, Plex)
        else JarTheme(look.style, JarColors(
            bg = Color(0xFFF4F6F9), surface = Color.White, surface2 = Color(0xFFE6EAF0), ink = Color(0xFF11151B),
            muted = Color(0xFF556070), line = Color(0xFFDDE3EA),
            accent = acc.light, onAccent = Color.White, accentSoft = acc.light.copy(alpha = 0.10f), onAccentSoft = acc.light,
            danger = Color(0xFFB3261E), dangerSoft = Color(0xFFFBE7E3), coin = Color(0xFF8A5212), coinSoft = Color(0xFFFBEFD9),
            record = acc.light, onRecord = Color.White, dark = false,
        ), JarShape(18.dp, 1.dp, 0.dp, Color(0xFFDDE3EA)), Plex, Plex)
        JarStyle.CALM -> if (dark) JarTheme(look.style, JarColors(
            bg = Color(0xFF15181A), surface = Color(0xFF1E2225), surface2 = Color(0xFF2A3036), ink = Color(0xFFECEFEA),
            muted = Color(0xFFA5AEA8), line = Color(0xFF2C3134),
            accent = acc.dark, onAccent = Color(0xFF111412), accentSoft = acc.dark.copy(alpha = 0.18f), onAccentSoft = acc.dark,
            danger = Color(0xFFFF9A90), dangerSoft = Color(0xFF3A2226), coin = Color(0xFFFFD27A), coinSoft = Color(0xFF3A2F18),
            record = acc.dark, onRecord = Color(0xFF111412), dark = true,
        ), JarShape(20.dp, 0.dp, 0.dp, Color(0xFF2C3134)), Heebo, Heebo)
        else JarTheme(look.style, JarColors(
            bg = Color(0xFFF6F4EF), surface = Color.White, surface2 = Color(0xFFF1EFE9), ink = Color(0xFF1C2420),
            muted = Color(0xFF5B6660), line = Color(0xFFE4E1D8),
            accent = acc.light, onAccent = Color.White, accentSoft = acc.light.copy(alpha = 0.12f), onAccentSoft = acc.light,
            danger = Color(0xFFA33A2B), dangerSoft = Color(0xFFFBE7E3), coin = Color(0xFF8A5212), coinSoft = Color(0xFFFBEFD9),
            record = acc.light, onRecord = Color.White, dark = false,
        ), JarShape(20.dp, 0.dp, 0.dp, Color(0xFFE4E1D8)), Heebo, Heebo)
    }
}

/** Provides [LocalJar] and a Material 3 scheme built from the same tokens (dialogs, sheets, text fields). */
@Composable
fun JarThemed(look: Look, content: @Composable () -> Unit) {
    val t = themeFor(look, isSystemInDarkTheme())
    val c = t.colors
    val scheme = if (c.dark) darkColorScheme(
        primary = c.accent, onPrimary = c.onAccent, background = c.bg, onBackground = c.ink,
        surface = c.surface, onSurface = c.ink, surfaceContainerLow = c.surface, onSurfaceVariant = c.muted, outline = c.line,
    ) else lightColorScheme(
        primary = c.accent, onPrimary = c.onAccent, background = c.bg, onBackground = c.ink,
        surface = c.surface, onSurface = c.ink, surfaceContainerLow = c.surface, onSurfaceVariant = c.muted, outline = c.line,
    )
    val type = MaterialTheme.typography
    val withFont = type.copy(
        bodyLarge = type.bodyLarge.copy(fontFamily = t.font), bodyMedium = type.bodyMedium.copy(fontFamily = t.font),
        bodySmall = type.bodySmall.copy(fontFamily = t.font), labelLarge = type.labelLarge.copy(fontFamily = t.font),
        labelMedium = type.labelMedium.copy(fontFamily = t.font), titleLarge = type.titleLarge.copy(fontFamily = t.display),
        titleMedium = type.titleMedium.copy(fontFamily = t.display), headlineMedium = type.headlineMedium.copy(fontFamily = t.display),
    )
    CompositionLocalProvider(LocalJar provides t) {
        MaterialTheme(colorScheme = scheme, typography = withFont, content = content)
    }
}
