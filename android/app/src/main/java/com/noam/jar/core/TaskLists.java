package com.noam.jar.core;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/** Sorting tasks into the app's tabs, and the time arithmetic for reminders and snoozing. */
public final class TaskLists {
    private TaskLists() {}

    /** Open tasks first (earliest due first, undated after dated), then the recently done ones. */
    public static final Comparator<Task> ORDER = (a, b) -> {
        int ra = rank(a), rb = rank(b);
        if (ra != rb) return Integer.compare(ra, rb);
        String da = a.due == null ? "9999" : a.due, db = b.due == null ? "9999" : b.due;
        int c = da.compareTo(db);
        if (c != 0) return c;
        return b.updatedAt.compareTo(a.updatedAt);
    };

    private static int rank(Task t) {
        if (t.isRequested()) return 0;
        if (t.isOpen()) return 1;
        return 2;
    }

    /** "Mine": what I have to do. */
    public static List<Task> mine(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) if (me.equals(t.assignee) && !"declined".equals(t.status)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    /** "Asked": what I gave or asked someone else to do. */
    public static List<Task> asked(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) if (me.equals(t.createdBy) && !me.equals(t.assignee)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    /** "Family" (parents): everything else the server let me see — mostly the children's tasks. */
    public static List<Task> family(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) if (!me.equals(t.assignee) && !me.equals(t.createdBy)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    /** Requests from a child that a parent has to approve (not ones I made myself). */
    public static List<Task> needMyOk(List<Task> all, String me, boolean iAmParent) {
        List<Task> out = new ArrayList<>();
        if (!iAmParent) return out;
        for (Task t : all) if (t.isRequested() && !me.equals(t.createdBy)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    public static int openCount(List<Task> all, String me) {
        int n = 0;
        for (Task t : all) if (me.equals(t.assignee) && t.isOpen()) n++;
        return n;
    }

    /** Open tasks of mine for the morning summary: no time set, or due today or earlier. */
    public static List<Task> forMorning(List<Task> all, String me, String today) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (!me.equals(t.assignee) || !t.isOpen()) continue;
            String day = t.dueDay();
            if (day == null || day.compareTo(today) <= 0) out.add(t);
        }
        Collections.sort(out, ORDER);
        return out;
    }

    // ---------------------------------------------------------------- time

    /** Epoch millis of a local "yyyy-MM-dd[THH:mm]" (date only = 08:00), or -1 if unreadable. */
    public static long toMillis(String local, TimeZone tz) {
        if (local == null || local.length() < 10) return -1;
        try {
            Calendar c = Calendar.getInstance(tz);
            c.clear();
            c.set(Integer.parseInt(local.substring(0, 4)), Integer.parseInt(local.substring(5, 7)) - 1,
                    Integer.parseInt(local.substring(8, 10)));
            if (local.length() >= 16) {
                c.set(Calendar.HOUR_OF_DAY, Integer.parseInt(local.substring(11, 13)));
                c.set(Calendar.MINUTE, Integer.parseInt(local.substring(14, 16)));
            } else {
                c.set(Calendar.HOUR_OF_DAY, 8);
            }
            return c.getTimeInMillis();
        } catch (NumberFormatException | StringIndexOutOfBoundsException e) {
            return -1;
        }
    }

    public static String format(long millis, TimeZone tz) {
        Calendar c = Calendar.getInstance(tz);
        c.setTimeInMillis(millis);
        return String.format(Locale.US, "%04d-%02d-%02dT%02d:%02d", c.get(Calendar.YEAR),
                c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH),
                c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE));
    }

    public static String day(long millis, TimeZone tz) {
        return format(millis, tz).substring(0, 10);
    }

    /** Snooze choices: in an hour, this evening at 20:00 (null once it's past 19:00), tomorrow at 08:00. */
    public static String inAnHour(long now, TimeZone tz) {
        return format(now + 60 * 60 * 1000L, tz);
    }

    public static String tonight(long now, TimeZone tz) {
        Calendar c = Calendar.getInstance(tz);
        c.setTimeInMillis(now);
        if (c.get(Calendar.HOUR_OF_DAY) >= 19) return null;
        return day(now, tz) + "T20:00";
    }

    public static String tomorrowMorning(long now, TimeZone tz) {
        Calendar c = Calendar.getInstance(tz);
        c.setTimeInMillis(now);
        c.add(Calendar.DAY_OF_MONTH, 1);
        return day(c.getTimeInMillis(), tz) + "T08:00";
    }

    /** Next time the morning summary should appear (08:00 today if still ahead, else tomorrow). */
    public static long nextMorning(long now, TimeZone tz, int hour) {
        Calendar c = Calendar.getInstance(tz);
        c.setTimeInMillis(now);
        c.set(Calendar.HOUR_OF_DAY, hour);
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        if (c.getTimeInMillis() <= now) c.add(Calendar.DAY_OF_MONTH, 1);
        return c.getTimeInMillis();
    }

    /** Ids of tasks assigned to me (or waiting for my OK) that I haven't been told about yet. */
    public static List<Task> news(List<Task> all, String me, boolean iAmParent, java.util.Set<String> seen) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (seen.contains(t.id)) continue;
            // A WhatsApp draft from my own memo: tell me it's ready to send.
            if (t.isMessage() && me.equals(t.assignee) && t.isOpen()) {
                out.add(t);
                continue;
            }
            if (me.equals(t.createdBy)) continue;
            boolean forMe = me.equals(t.assignee) && t.isOpen();
            boolean toApprove = iAmParent && t.isRequested();
            if (forMe || toApprove) out.add(t);
        }
        return out;
    }

    /** "Yoni" for an id, falling back to the id itself. */
    public static String name(Map<String, String> names, String id) {
        String n = names.get(id);
        return n == null ? id : n;
    }
}
