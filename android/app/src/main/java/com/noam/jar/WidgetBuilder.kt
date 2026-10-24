package com.noam.jar

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
import androidx.compose.ui.graphics.toArgb
import com.noam.jar.core.Task
import com.noam.jar.core.TaskLists
import java.util.Calendar
import kotlin.math.roundToInt

/**
 * The tasks widget, drawn per style like the app (home-screen widgets can't run Compose, so each style has its
 * own layout, and the progress, the record button and the ticks are drawn as small pictures):
 *  - Calm: the date and a greeting, "+ Task" and the mic; a soft progress bar; rows in one card.
 *  - Night: a big count for today, a progress ring and a glowing orb; rows on a timeline with the time on the side.
 *  - Playful: "Hi!" with the week's coins on a sticker and a big record button; coins for progress; ink-outlined cards.
 * Small sizes keep only the header and the progress. Tick, OK or send from the widget; tap a row to open it in the app.
 */
object WidgetBuilder {

    @JvmStatic
    fun build(c: Context, widthDp: Int, heightDp: Int): RemoteViews {
        val cache = TaskCache(c)
        val prefs = Prefs(c)
        val me = cache.myId()
        val look = LookPrefs.load(c, me.isNotEmpty() && !cache.iAmParent())
        val systemDark = (c.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        val t = themeFor(look, systemDark)
        val col = t.colors
        val style = t.style
        val ink = col.ink.toArgb()
        val muted = col.muted.toArgb()
        val danger = col.danger.toArgb()
        val accent = (if (style == JarStyle.PLAYFUL) col.record else col.accent).toArgb()
        val onAccent = (if (style == JarStyle.PLAYFUL) col.onRecord else col.onAccent).toArgb()
        val coin = col.coin.toArgb()
        val v = RemoteViews(c.packageName, when (style) {
            JarStyle.CALM -> R.layout.widget_calm; JarStyle.NIGHT -> R.layout.widget_night; JarStyle.PLAYFUL -> R.layout.widget_playful
        })
        v.setInt(R.id.w_root, "setBackgroundResource", when (style) {
            JarStyle.CALM -> if (col.dark) R.drawable.widget_bg_calm_dark else R.drawable.widget_background
            JarStyle.NIGHT -> if (col.dark) R.drawable.widget_bg_night_dark else R.drawable.widget_bg_night_light
            JarStyle.PLAYFUL -> listOf(R.drawable.widget_bg_playful_0, R.drawable.widget_bg_playful_1,
                R.drawable.widget_bg_playful_2, R.drawable.widget_bg_playful_3)[look.palette.coerceIn(0, 3)]
        })

        // ---- what today looks like
        val all = cache.tasks()
        val parent = cache.iAmParent()
        val waiting = TaskLists.needMyOk(all, me, parent)
        val s = sectionsOf(TaskLists.mine(all, me), waiting)
        val openToday = s.waiting.size + s.overdue.size + s.today.size
        val done = s.doneToday.size
        val total = openToday + done
        val frac = if (total == 0) 1f else done.toFloat() / total
        val paired = prefs.token().isNotEmpty()
        val name = cache.myName()
        val board = cache.board()
        val week = board.people.firstOrNull { it.id == me }?.week ?: 0

        // ---- header
        when (style) {
            JarStyle.CALM -> {
                v.setTextViewText(R.id.w_date, longDate())
                v.setTextViewText(R.id.w_title, if (name.isEmpty()) c.getString(R.string.tasks_title) else c.getString(greeting(), name))
                v.setTextColor(R.id.w_date, muted); v.setTextColor(R.id.w_title, ink)
                v.setInt(R.id.w_add, "setBackgroundResource", if (col.dark) R.drawable.widget_pill_calm_dark else R.drawable.widget_pill_calm_light)
                v.setTextColor(R.id.w_add, ink)
            }
            JarStyle.NIGHT -> {
                v.setTextViewText(R.id.w_date, shortDate())
                v.setTextViewText(R.id.w_title, openToday.toString())
                val sub = buildList {
                    add(c.getString(R.string.w_today))
                    if (s.overdue.isNotEmpty()) add(c.getString(R.string.ui_sum_overdue, s.overdue.size))
                }.joinToString(" · ")
                v.setTextViewText(R.id.w_sub, sub)
                v.setTextColor(R.id.w_date, muted); v.setTextColor(R.id.w_title, ink)
                v.setTextColor(R.id.w_sub, if (s.overdue.isNotEmpty()) danger else muted)
                v.setInt(R.id.w_add, "setBackgroundResource", if (col.dark) R.drawable.widget_square_night_dark else R.drawable.widget_square_night_light)
                v.setInt(R.id.w_add, "setColorFilter", ink)
            }
            JarStyle.PLAYFUL -> {
                v.setTextViewText(R.id.w_title, if (name.isEmpty()) c.getString(R.string.tasks_title) else c.getString(R.string.ui_hi, name))
                v.setTextViewText(R.id.w_coins, "● $week")
                v.setTextColor(R.id.w_title, ink)
                v.setInt(R.id.w_add, "setColorFilter", ink)
            }
        }

        // ---- record button
        val rec = RecorderService.isRecording()
        val micFill = if (rec) danger else accent
        v.setImageViewBitmap(R.id.w_mic_bg, when (style) {
            JarStyle.CALM -> disc(c, 44, micFill)
            JarStyle.NIGHT -> orb(c, 52, micFill)
            JarStyle.PLAYFUL -> sticker(c, 58, micFill, ink)
        })
        v.setImageViewResource(R.id.w_mic_icon, if (rec) R.drawable.ic_widget_stop else R.drawable.ic_widget_mic)
        v.setInt(R.id.w_mic_icon, "setColorFilter", if (rec) android.graphics.Color.WHITE else onAccent)
        v.setContentDescription(R.id.w_mic_icon, c.getString(if (rec) R.string.widget_recording else R.string.widget_tap_to_record))

        // ---- progress
        val progressText = when {
            !paired -> c.getString(R.string.widget_not_paired)
            total == 0 -> c.getString(R.string.w_nothing_today)
            openToday == 0 -> c.getString(R.string.ui_done_all)
            else -> c.getString(R.string.w_done_of, done, total)
        }
        when (style) {
            JarStyle.CALM -> {
                v.setImageViewBitmap(R.id.w_progress, bar(c, (widthDp - 30).coerceAtLeast(60), 8, frac, col.surface2.toArgb(), accent))
                v.setTextViewText(R.id.w_progress_text, progressText); v.setTextColor(R.id.w_progress_text, muted)
            }
            JarStyle.NIGHT -> {
                v.setImageViewBitmap(R.id.w_progress, ring(c, 56, 5, frac, col.line.toArgb(), accent))
                v.setTextViewText(R.id.w_progress_text, if (total == 0) "✓" else "$done/$total")
                v.setTextColor(R.id.w_progress_text, ink)
                v.setContentDescription(R.id.w_progress, progressText)
            }
            JarStyle.PLAYFUL -> {
                val n = total.coerceIn(1, 7)
                val earned = if (total == 0) n else (done * n + total / 2) / total
                v.setImageViewBitmap(R.id.w_progress, coins(c, n, earned, col.coinSoft.toArgb(), col.surface.toArgb(), ink))
                v.setTextViewText(R.id.w_progress_text, progressText); v.setTextColor(R.id.w_progress_text, muted)
            }
        }

        // ---- rows: as many as fit
        val compact = heightDp < 150
        val head = when (style) { JarStyle.CALM -> 118; JarStyle.NIGHT -> 92; JarStyle.PLAYFUL -> 120 }
        val rowH = when (style) { JarStyle.CALM -> 48; JarStyle.NIGHT -> 52; JarStyle.PLAYFUL -> 60 }
        val fit = if (compact) 0 else ((heightDp - head - 24) / rowH).coerceIn(0, 6)
        val items = if (paired) TaskLists.forWidget(all, me, parent, fit) else emptyList()
        val names = cache.names()
        v.removeAllViews(R.id.w_rows)
        if (style == JarStyle.CALM) v.setInt(R.id.w_rows, "setBackgroundResource",
            if (col.dark) R.drawable.widget_card_calm_dark else R.drawable.widget_card_calm_light)
        items.forEachIndexed { i, task -> v.addView(R.id.w_rows, row(c, task, style, me, names, i, ink, muted, accent, danger, coin, col.dark)) }
        v.setViewVisibility(R.id.w_rows, if (items.isEmpty()) View.GONE else View.VISIBLE)
        val showEmpty = !compact && items.isEmpty()
        v.setViewVisibility(R.id.w_empty, if (showEmpty) View.VISIBLE else View.GONE)
        if (showEmpty) {
            v.setTextViewText(R.id.w_empty, c.getString(if (!paired) R.string.widget_not_paired else R.string.widget_nothing))
            v.setTextColor(R.id.w_empty, if (style == JarStyle.PLAYFUL) ink else muted)
        }

        // ---- footer: what Jar did with the last memo, or who leads the week
        val memoLine = TasksWidget.lastMemoLine(c, cache.lastMemo())
        val lead = board.leader()
        val leadLine = lead?.let {
            if (it.id == me) c.getString(R.string.widget_board_you, it.week) else c.getString(R.string.widget_board_leads, it.name, it.week, board.myWeek())
        } ?: ""
        val footer = when (style) {
            JarStyle.CALM -> memoLine.ifEmpty { leadLine }
            else -> leadLine.ifEmpty { memoLine }
        }
        v.setTextViewText(R.id.w_footer, footer)
        v.setTextColor(R.id.w_footer, muted)
        v.setViewVisibility(R.id.w_footer, if (compact || footer.isEmpty()) View.GONE else View.VISIBLE)
        v.setViewVisibility(R.id.w_add, if (widthDp < 230 && style != JarStyle.NIGHT) View.GONE else View.VISIBLE)

        // ---- taps
        val open = pending(c, 2, Intent(c, TasksActivity::class.java))
        v.setOnClickPendingIntent(R.id.w_head, open)
        v.setOnClickPendingIntent(R.id.w_empty, open)
        v.setOnClickPendingIntent(R.id.w_add, pending(c, 5, Intent(c, TasksActivity::class.java).putExtra(TasksActivity.EXTRA_ADD, true)
            .setData(Uri.parse("jar://widget/add"))))
        v.setOnClickPendingIntent(R.id.w_mic, pending(c, 6, Intent(c, RecordActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION)))
        v.setOnClickPendingIntent(R.id.w_footer, pending(c, 3,
            if (LookPrefs.newUi(c)) Intent(c, HomeActivity::class.java).putExtra(HomeActivity.EXTRA_SUB, if (memoLine.isNotEmpty() && style == JarStyle.CALM) "MEMOS" else "")
            else Intent(c, MemosActivity::class.java)))
        return v
    }

    private fun row(c: Context, t: Task, style: JarStyle, me: String, names: Map<String, String>, i: Int,
                    ink: Int, muted: Int, accent: Int, danger: Int, coin: Int, dark: Boolean): RemoteViews {
        val r = RemoteViews(c.packageName, when (style) {
            JarStyle.CALM -> R.layout.widget_row_calm; JarStyle.NIGHT -> R.layout.widget_row_night; JarStyle.PLAYFUL -> R.layout.widget_row_playful
        })
        val overdue = TaskFormat.overdue(t)
        var title = t.title
        val action = when {
            t.waitingOn(me) -> { title = "❓ " + t.title + (t.lastNote()?.let { ": " + it.text } ?: ""); "open" }
            t.isRequested -> { title = c.getString(R.string.widget_asks, TaskLists.name(names, t.createdBy), t.title); "accept" }
            t.isMessage -> "send"
            else -> "done"
        }
        r.setTextViewText(R.id.r_title, title)
        r.setTextColor(R.id.r_title, ink)
        val meta = TaskFormat.meta(c, t, me, names)
        r.setTextViewText(R.id.r_meta, meta)
        r.setTextColor(R.id.r_meta, if (overdue) danger else muted)
        r.setViewVisibility(R.id.r_meta, if (meta.isEmpty()) View.GONE else View.VISIBLE)
        when (action) {
            "done" -> r.setImageViewBitmap(R.id.r_tick, tick(c, if (style == JarStyle.PLAYFUL) 28 else 22,
                if (overdue) danger else if (style == JarStyle.PLAYFUL) ink else accent, if (style == JarStyle.PLAYFUL) 3f else 2f))
            else -> {
                r.setImageViewResource(R.id.r_tick, if (action == "send") R.drawable.ic_widget_send else R.drawable.ic_widget_ok)
                r.setInt(R.id.r_tick, "setColorFilter", accent)
            }
        }
        r.setContentDescription(R.id.r_tick, c.getString(when (action) {
            "accept" -> R.string.action_accept; "send" -> R.string.send_whatsapp; "open" -> R.string.thread_answer_button; else -> R.string.action_done
        }) + ": " + t.title)
        if (style == JarStyle.NIGHT) {
            val time = t.due?.let { d -> if (d.length >= 16) d.substring(11, 16) else TaskFormat.shortDay(d.take(10)) } ?: "··"
            r.setTextViewText(R.id.r_time, time)
            r.setTextColor(R.id.r_time, if (overdue) danger else accent)
            r.setInt(R.id.r_card, "setBackgroundResource", if (dark) R.drawable.widget_card_night_dark else R.drawable.widget_card_night_light)
        } else {
            r.setTextViewText(R.id.r_coins, if (t.coins > 0 && !t.isMessage) "+${t.coins}" else "")
            r.setTextColor(R.id.r_coins, if (style == JarStyle.PLAYFUL) ink else coin)
        }
        r.setOnClickPendingIntent(R.id.r_tick, pending(c, 100 + i * 2, widgetAction(c, t.id, action)))
        r.setOnClickPendingIntent(R.id.r_text, pending(c, 101 + i * 2, widgetAction(c, t.id, "open")))
        return r
    }

    private fun widgetAction(c: Context, id: String, what: String) = Intent(c, WidgetActionActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION)
        .setData(Uri.parse("jar://widget/$id/$what"))      // one PendingIntent per task and action
        .putExtra(WidgetActionActivity.EXTRA_ID, id).putExtra(WidgetActionActivity.EXTRA_DO, what)

    private fun pending(c: Context, req: Int, i: Intent): PendingIntent =
        PendingIntent.getActivity(c, req, i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    private fun greeting(): Int = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
        in 5..11 -> R.string.ui_good_morning; in 12..16 -> R.string.ui_good_afternoon; else -> R.string.ui_good_evening
    }

    // ---------------------------------------------------------------- the small pictures

    private fun px(c: Context, dp: Float) = (dp * c.resources.displayMetrics.density).roundToInt().coerceAtLeast(1)
    private fun paint(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color }

    /** Calm's progress: a rounded track with the done part in the accent. */
    private fun bar(c: Context, wDp: Int, hDp: Int, frac: Float, track: Int, fill: Int): Bitmap {
        val w = px(c, wDp.toFloat()); val h = px(c, hDp.toFloat())
        val b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val cv = Canvas(b); val r = h / 2f
        cv.drawRoundRect(RectF(0f, 0f, w.toFloat(), h.toFloat()), r, r, paint(track))
        if (frac > 0f) cv.drawRoundRect(RectF(0f, 0f, maxOf(h.toFloat(), w * frac), h.toFloat()), r, r, paint(fill))
        return b
    }

    /** Night's progress ring. */
    private fun ring(c: Context, sizeDp: Int, strokeDp: Int, frac: Float, track: Int, fill: Int): Bitmap {
        val s = px(c, sizeDp.toFloat()); val st = px(c, strokeDp.toFloat()).toFloat()
        val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
        val cv = Canvas(b)
        val rect = RectF(st, st, s - st, s - st)
        cv.drawArc(rect, 0f, 360f, false, paint(track).apply { style = Paint.Style.STROKE; strokeWidth = st })
        cv.drawArc(rect, -90f, 360f * frac, false, paint(fill).apply { style = Paint.Style.STROKE; strokeWidth = st; strokeCap = Paint.Cap.ROUND })
        return b
    }

    /** Calm's record button: a plain disc. */
    private fun disc(c: Context, sizeDp: Int, fill: Int): Bitmap {
        val s = px(c, sizeDp.toFloat())
        val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
        Canvas(b).drawCircle(s / 2f, s / 2f, s / 2f, paint(fill))
        return b
    }

    /** Night's orb: a glow around a disc with a lighter centre. */
    private fun orb(c: Context, sizeDp: Int, fill: Int): Bitmap {
        val s = px(c, sizeDp.toFloat())
        val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
        val cv = Canvas(b); val r = s / 2f
        cv.drawCircle(r, r, r, Paint(Paint.ANTI_ALIAS_FLAG).apply {
            shader = RadialGradient(r, r, r, intArrayOf(withAlpha(fill, 110), withAlpha(fill, 0)), floatArrayOf(0.55f, 1f), Shader.TileMode.CLAMP)
        })
        cv.drawCircle(r, r, r * 0.66f, Paint(Paint.ANTI_ALIAS_FLAG).apply {
            shader = RadialGradient(r * 0.85f, r * 0.8f, r * 0.7f, intArrayOf(lighten(fill), fill), null, Shader.TileMode.CLAMP)
        })
        return b
    }

    /** Playful's record button: the record colour with an ink border and an offset shadow. */
    private fun sticker(c: Context, sizeDp: Int, fill: Int, ink: Int): Bitmap {
        val s = px(c, sizeDp.toFloat()); val off = px(c, 3f).toFloat(); val bw = px(c, 2.5f).toFloat()
        val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
        val cv = Canvas(b); val r = (s - off) / 2f
        cv.drawCircle(r + off, r + off, r - bw / 2, paint(ink))
        cv.drawCircle(r, r, r - bw / 2, paint(fill))
        cv.drawCircle(r, r, r - bw / 2, paint(ink).apply { style = Paint.Style.STROKE; strokeWidth = bw })
        return b
    }

    /** An empty circle to tick. */
    private fun tick(c: Context, sizeDp: Int, color: Int, strokeDp: Float): Bitmap {
        val s = px(c, sizeDp.toFloat()); val st = px(c, strokeDp).toFloat()
        val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
        Canvas(b).drawCircle(s / 2f, s / 2f, s / 2f - st, paint(color).apply { style = Paint.Style.STROKE; strokeWidth = st })
        return b
    }

    /** Playful's progress: a row of coins, the earned ones gold. */
    private fun coins(c: Context, n: Int, earned: Int, gold: Int, empty: Int, ink: Int): Bitmap {
        val d = px(c, 20f); val gap = px(c, 4f); val bw = px(c, 2f).toFloat()
        val b = Bitmap.createBitmap(n * d + (n - 1) * gap, d + px(c, 2f), Bitmap.Config.ARGB_8888)
        val cv = Canvas(b)
        for (i in 0 until n) {
            val cx = i * (d + gap) + d / 2f; val cy = d / 2f; val r = d / 2f - bw / 2
            cv.drawCircle(cx, cy, r, paint(if (i < earned) gold else empty))
            cv.drawCircle(cx, cy, r, paint(ink).apply { style = Paint.Style.STROKE; strokeWidth = bw })
        }
        return b
    }

    private fun withAlpha(color: Int, a: Int) = (color and 0x00FFFFFF) or (a shl 24)
    private fun lighten(color: Int): Int {
        fun ch(shift: Int) = ((color shr shift) and 0xFF).let { it + (255 - it) / 3 }
        return (0xFF shl 24) or (ch(16) shl 16) or (ch(8) shl 8) or ch(0)
    }
}
