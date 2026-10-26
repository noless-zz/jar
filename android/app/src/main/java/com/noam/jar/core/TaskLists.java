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

    /** Open tasks first, then done ones; on an "each of us" task, as {@code me} sees it. */
    public static Comparator<Task> orderFor(String me) {
        return (a, b) -> {
            int ra = rank(a, me), rb = rank(b, me);
            if (ra != rb) return Integer.compare(ra, rb);
            return ORDER.compare(a, b);
        };
    }

    private static int rank(Task t, String me) {
        int r = rank(t);
        return r == 1 && t.doneFor(me) ? 2 : r;
    }

    private static int rank(Task t) {
        if (t.isRequested()) return 0;
        if (t.isOpen()) return 1;
        return 2;
    }

    /** Mine, and still something for me to do on it. Jar ideas live on their own tab. */
    public static boolean mineOpen(Task t, String me) {
        return !t.isIdea() && t.isFor(me) && t.openFor(me);
    }

    /** The 💡 tab: new ideas first, then accepted, shipped, declined; newest first within each. */
    public static List<Task> ideas(List<Task> all) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) if (t.isIdea()) out.add(t);
        Collections.sort(out, (a, b) -> {
            int ra = ideaRank(a), rb = ideaRank(b);
            if (ra != rb) return Integer.compare(ra, rb);
            return b.updatedAt.compareTo(a.updatedAt);
        });
        return out;
    }

    static int ideaRank(Task t) {
        if (t.isRequested()) return 0;
        if (t.isOpen()) return 1;
        if (t.isDone()) return 2;
        return 3;
    }

    /** "Mine": what I have to do. */
    public static List<Task> mine(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (t.isIdea()) continue;
            if ((t.isFor(me) && !"declined".equals(t.status)) || t.waitingOn(me)) out.add(t);
        }
        Collections.sort(out, orderFor(me));
        return questionsFirst(out, me);
    }

    /** A question waiting for my answer goes to the top (stable: otherwise the usual order). */
    static List<Task> questionsFirst(List<Task> list, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : list) if (t.waitingOn(me)) out.add(t);
        for (Task t : list) if (!t.waitingOn(me)) out.add(t);
        return out;
    }

    /**
     * Tasks with a note I haven't been told about: the newest note is someone else's, and I do the task,
     * asked for it, or am the one a question waits on. Keyed "n:<task>:<note id>" in {@code seen}.
     */
    public static List<Task> newNotes(List<Task> all, String me, java.util.Set<String> seen) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            Task.Note n = t.lastNote();
            if (n == null || me.equals(n.by) || seen.contains(noteKey(t))) continue;
            if (t.isFor(me) || me.equals(t.createdBy) || t.waitingOn(me)) out.add(t);
        }
        return out;
    }

    /** "h:<task>:<to>" in {@code seen}: told about this move already. */
    public static String handoverKey(Task t) {
        return "h:" + t.id + ":" + t.handoverTo;
    }

    public static String noteKey(Task t) {
        Task.Note n = t.lastNote();
        return "n:" + t.id + ":" + (n == null ? 0 : n.id);
    }

    /** "Asked": what I gave or asked someone else to do. */
    public static List<Task> asked(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (t.isIdea()) continue;
            // A recurring chore I set up (e.g. Alona's laundry) isn't something I asked for today: it's under Family.
            boolean mine = me.equals(t.createdBy) && !t.isFor(me) && !t.isRecurring();
            if (mine || iAskedAndWait(t, me)) out.add(t);
        }
        Collections.sort(out, ORDER);
        return out;
    }

    /** A question of mine on someone else's task, still waiting for their answer. */
    static boolean iAskedAndWait(Task t, String me) {
        if (t.waitingOn.isEmpty() || t.waitingOn(me)) return false;
        for (int i = t.thread.size() - 1; i >= 0; i--) {
            Task.Note n = t.thread.get(i);
            if (n.ask) return me.equals(n.by);
        }
        return false;
    }

    /** "Family" (parents): everything else the server let me see — mostly the children's tasks. */
    public static List<Task> family(List<Task> all, String me) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) if (!t.isIdea() && !t.isFor(me) && !me.equals(t.createdBy)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    /** Requests from a child that a parent has to approve (not ones I made myself). */
    public static List<Task> needMyOk(List<Task> all, String me, boolean iAmParent) {
        List<Task> out = new ArrayList<>();
        if (!iAmParent) {                     // a child approves only moves into their own area
            for (Task t : all) if (t.mayApproveHandover(me, false)) out.add(t);
            return out;
        }
        for (Task t : all) if (t.isRequested() && !t.isIdea() && !me.equals(t.createdBy)) out.add(t);
        for (Task t : all) if (t.mayApproveHandover(me, iAmParent) && !out.contains(t)) out.add(t);
        Collections.sort(out, ORDER);
        return out;
    }

    /**
     * The tasks widget: requests waiting for my OK, then my open tasks and messages to send
     * (earliest due first, undated last), at most {@code max}.
     */
    public static List<Task> forWidget(List<Task> all, String me, boolean iAmParent, int max) {
        List<Task> out = new ArrayList<>(needMyOk(all, me, iAmParent));
        List<Task> mine = new ArrayList<>();
        for (Task t : all) if ((mineOpen(t, me) || t.waitingOn(me)) && !out.contains(t)) mine.add(t);
        Collections.sort(mine, ORDER);
        out.addAll(0, questionsFirst(mine, me).subList(0, countWaiting(mine, me)));
        for (Task t : mine) if (!t.waitingOn(me)) out.add(t);
        return out.size() > max ? new ArrayList<>(out.subList(0, max)) : out;
    }

    static int countWaiting(List<Task> list, String me) {
        int n = 0;
        for (Task t : list) if (t.waitingOn(me)) n++;
        return n;
    }

    public static int openCount(List<Task> all, String me) {
        int n = 0;
        for (Task t : all) if (mineOpen(t, me)) n++;
        return n;
    }

    /** Open tasks of mine for the morning summary: no time set, or due today or earlier. */
    public static List<Task> forMorning(List<Task> all, String me, String today) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (!mineOpen(t, me)) continue;
            String day = t.dueDay();
            if (day == null || day.compareTo(today) <= 0) out.add(t);
        }
        Collections.sort(out, ORDER);
        return out;
    }

    // ---------------------------------------------------------------- done and archive

    /** Where a finished task sits on its tab. */
    public static final int OPEN = 0, DONE_TODAY = 1, DONE_WEEK = 2, ARCHIVED = 3;
    static final long DAY_MS = 24L * 3600 * 1000;

    /**
     * Open (or still mine to do), done in the last 24 hours (to review), done in the last week, or archived
     * (done more than a week ago). {@code me} null: done for everyone. Declined counts as finished.
     */
    public static int doneBucket(Task t, String me, long now) {
        boolean finished = (me == null ? t.isDone() : t.doneFor(me)) || "declined".equals(t.status);
        if (!finished) return OPEN;
        long at = utcMillis(doneWhen(t));
        if (at < 0) return DONE_TODAY;                 // unknown time: keep it in sight
        long age = now - at;
        return age <= DAY_MS ? DONE_TODAY : age <= 7 * DAY_MS ? DONE_WEEK : ARCHIVED;
    }

    /** When it was finished: done_at, or the last change (my part of an "each of us" task, a decline). */
    public static String doneWhen(Task t) {
        return t.isDone() && t.doneAt != null && !t.doneAt.isEmpty() ? t.doneAt : t.updatedAt;
    }

    /** Most recently finished first. */
    public static final Comparator<Task> NEWEST_DONE = (a, b) -> doneWhen(b).compareTo(doneWhen(a));

    /** Epoch millis of the server's UTC "yyyy-MM-ddTHH:mm:ss[Z]", or -1. */
    public static long utcMillis(String iso) {
        if (iso == null || iso.length() < 16) return -1;
        try {
            Calendar c = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
            c.clear();
            c.set(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)) - 1,
                    Integer.parseInt(iso.substring(8, 10)), Integer.parseInt(iso.substring(11, 13)),
                    Integer.parseInt(iso.substring(14, 16)), iso.length() >= 19 ? Integer.parseInt(iso.substring(17, 19)) : 0);
            return c.getTimeInMillis();
        } catch (NumberFormatException | StringIndexOutOfBoundsException e) {
            return -1;
        }
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
        return news(all, me, iAmParent, false, seen);
    }

    /** As above; the admin also hears about each new Jar idea. */
    public static List<Task> news(List<Task> all, String me, boolean iAmParent, boolean iAmAdmin,
                                  java.util.Set<String> seen) {
        List<Task> out = new ArrayList<>();
        for (Task t : all) {
            if (t.hasHandover() && me.equals(t.handoverTo)) {
                if (!seen.contains(handoverKey(t))) out.add(t);     // asked to take a task into my area
                continue;
            }
            if (seen.contains(t.id)) continue;
            if (t.isIdea()) {
                if (iAmAdmin && t.isRequested() && !me.equals(t.createdBy)) out.add(t);
                continue;
            }
            // A WhatsApp draft from my own memo: tell me it's ready to send.
            if (t.isMessage() && t.isFor(me) && t.isOpen()) {
                out.add(t);
                continue;
            }
            if (me.equals(t.createdBy)) continue;
            boolean forMe = mineOpen(t, me);
            boolean toApprove = iAmParent && t.isRequested();
            if (forMe || toApprove) out.add(t);
        }
        return out;
    }

    /** How Home Assistant (the family wall panel, server id "home") is shown; set from strings.xml by TaskCache. */
    public static volatile String homeName = "🏠 Home";

    /** "Yoni" for an id, falling back to the id itself. */
    public static String name(Map<String, String> names, String id) {
        String n = names.get(id);
        if (n == null && "home".equals(id)) return homeName;
        return n == null ? id : n;
    }
}
