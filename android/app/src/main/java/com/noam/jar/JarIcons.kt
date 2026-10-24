package com.noam.jar

import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** Line icons drawn on a 24×24 grid (the same ones as on the design canvas), tinted where used. */
object JarIcons {
    private fun line(name: String, vararg paths: String, width: Float = 2f, mirror: Boolean = false): ImageVector {
        val b = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f, autoMirror = mirror)
        for (p in paths) {
            b.addPath(
                pathData = addPathNodes(p), fill = null, stroke = SolidColor(Color.Black), strokeLineWidth = width,
                strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
            )
        }
        return b.build()
    }

    private fun solid(name: String, vararg paths: String): ImageVector {
        val b = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f)
        for (p in paths) b.addPath(pathData = addPathNodes(p), fill = SolidColor(Color.Black))
        return b.build()
    }

    val Mic = line("mic", "M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0z", "M5 11a7 7 0 0 0 14 0M12 18v3")
    val Stop = solid("stop", "M8 6h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z")
    val Tasks = line("tasks", "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2")
    val Family = line("family", "M6 8a3 3 0 1 0 6 0a3 3 0 1 0-6 0", "M14.5 9a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
        "M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M15 20c0-2.5 1.5-4.5 4-4.5")
    val Trophy = line("trophy", "M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3")
    val Idea = line("idea", "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z")
    val Check = line("check", "M5 12l5 5 9-10", width = 2.6f)
    val Plus = line("plus", "M12 5v14M5 12h14")
    val Clock = line("clock", "M4 13a8 8 0 1 0 16 0a8 8 0 1 0-16 0", "M12 9v4l2 2M9 2h6")
    val Repeat = line("repeat", "M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3")
    val More = solid("more", "M10.2 5a1.8 1.8 0 1 0 3.6 0a1.8 1.8 0 1 0-3.6 0", "M10.2 12a1.8 1.8 0 1 0 3.6 0a1.8 1.8 0 1 0-3.6 0",
        "M10.2 19a1.8 1.8 0 1 0 3.6 0a1.8 1.8 0 1 0-3.6 0")
    val Back = line("back", "M15 6l-6 6 6 6", mirror = true)     // points to the start: left in English, right in Hebrew
    val Close = line("close", "M6 6l12 12M18 6L6 18")
    val Undo = line("undo", "M4 12a8 8 0 1 0 3-6.2M4 4v4h4")
    val Chevron = line("chevron", "M15 6l-6 6 6 6")
    val Palette = line("palette", "M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0",
        "M12 3a9 9 0 0 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5 1-1.5 2-1.5h2a4 4 0 0 0 4-4c0-4.4-4-8-9-8z")
}
