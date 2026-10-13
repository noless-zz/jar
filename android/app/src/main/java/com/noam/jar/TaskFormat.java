package com.noam.jar;

import android.content.Context;

import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import java.text.DateFormat;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/** Human wording for task times and the small grey line under a task. */
final class TaskFormat {
    private TaskFormat() {}

    /** "today 18:00", "tomorrow", "Thu 15 Oct 08:00". */
    static String when(Context c, String local) {
        if (local == null) return "";
        TimeZone tz = TimeZone.getDefault();
        long now = System.currentTimeMillis();
        String day = local.substring(0, Math.min(10, local.length()));
        String time = local.length() >= 16 ? local.substring(11, 16) : "";
        String today = TaskLists.day(now, tz);
        String tomorrow = TaskLists.day(now + 24 * 3600 * 1000L, tz);
        String d;
        if (day.equals(today)) d = c.getString(R.string.when_today);
        else if (day.equals(tomorrow)) d = c.getString(R.string.when_tomorrow);
        else {
            long ms = TaskLists.toMillis(day, tz);
            d = ms < 0 ? day : new SimpleDateFormat("EEE d MMM", Locale.getDefault()).format(new Date(ms));
        }
        return time.isEmpty() ? d : d + " " + time;
    }

    static boolean overdue(Task t) {
        if (!t.isOpen() || t.due == null) return false;
        long at = TaskLists.toMillis(t.dueHasTime() ? t.due : t.due + "T23:59", TimeZone.getDefault());
        return at > 0 && at < System.currentTimeMillis();
    }

    /** "for Yoni · from Dana · tomorrow 18:00 · snoozed to 20:00 · waiting for a parent's OK". */
    static String meta(Context c, Task t, String me, Map<String, String> names) {
        List<String> parts = new ArrayList<>();
        if (t.isMessage()) {
            String m = t.message == null ? "" : t.message.replace('\n', ' ');
            parts.add("“" + (m.length() > 70 ? m.substring(0, 70) + "…" : m) + "”");
        }
        if (!me.equals(t.assignee)) parts.add(c.getString(R.string.meta_for, TaskLists.name(names, t.assignee)));
        if (!me.equals(t.createdBy) && !t.createdBy.equals(t.assignee))
            parts.add(c.getString(R.string.meta_from, TaskLists.name(names, t.createdBy)));
        if (t.due != null) parts.add(when(c, t.due));
        if (t.isOpen() && t.snoozedUntil != null) parts.add(c.getString(R.string.meta_snoozed, when(c, t.snoozedUntil)));
        if (t.isRequested()) parts.add(c.getString(R.string.meta_waiting));
        if ("declined".equals(t.status)) parts.add(c.getString(R.string.meta_declined));
        if (t.isDone() && t.doneBy != null && !me.equals(t.doneBy))
            parts.add(c.getString(R.string.meta_done_by, TaskLists.name(names, t.doneBy)));
        return String.join(" · ", parts);
    }

    /** "12:40" for today, else "Mon 12:40", from the PC's UTC "2026-10-12T09:40:00Z". */
    static String memoTime(String isoUtc) {
        try {
            SimpleDateFormat in = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);
            in.setTimeZone(TimeZone.getTimeZone("UTC"));
            Date d = in.parse(isoUtc.replace("Z", ""));
            if (d == null) return "";
            boolean today = TaskLists.day(d.getTime(), TimeZone.getDefault())
                    .equals(TaskLists.day(System.currentTimeMillis(), TimeZone.getDefault()));
            return new SimpleDateFormat(today ? "HH:mm" : "EEE HH:mm", Locale.getDefault()).format(d);
        } catch (Exception e) {
            return "";
        }
    }

    static String syncedAgo(Context c, long syncedAt) {
        if (syncedAt <= 0) return c.getString(R.string.synced_never);
        return c.getString(R.string.synced_at,
                DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date(syncedAt)));
    }
}
