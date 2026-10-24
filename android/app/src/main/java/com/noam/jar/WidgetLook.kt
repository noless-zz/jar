package com.noam.jar

import android.content.Context
import android.content.res.Configuration
import androidx.compose.ui.graphics.toArgb

/**
 * The tasks widget in the person's look (home-screen widgets can't run Compose, so it takes the colours and
 * a matching background shape): Calm soft and rounded, Night dark with a thin outline, Playful white with an ink border.
 */
class WidgetLook(val background: Int, val ink: Int, val muted: Int, val accent: Int, val danger: Int) {
    companion object {
        @JvmStatic
        fun of(c: Context): WidgetLook {
            val cache = TaskCache(c)
            val look = LookPrefs.load(c, cache.myId().isNotEmpty() && !cache.iAmParent())
            val systemDark = (c.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
            val t = themeFor(look, systemDark)
            val col = t.colors
            val bg = when (t.style) {
                JarStyle.CALM -> if (col.dark) R.drawable.widget_bg_calm_dark else R.drawable.widget_background
                JarStyle.NIGHT -> if (col.dark) R.drawable.widget_bg_night_dark else R.drawable.widget_bg_night_light
                JarStyle.PLAYFUL -> R.drawable.widget_bg_playful
            }
            val accent = if (t.style == JarStyle.PLAYFUL) col.record else col.accent
            return WidgetLook(bg, col.ink.toArgb(), col.muted.toArgb(), accent.toArgb(), col.danger.toArgb())
        }
    }
}
