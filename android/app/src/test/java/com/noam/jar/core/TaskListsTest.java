package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.TimeZone;

public class TaskListsTest {
    private static final TimeZone TZ = TimeZone.getTimeZone("Asia/Jerusalem");

    private static Task t(String id, String assignee, String by, String status, String due) {
        Task t = new Task();
        t.id = id;
        t.title = id;
        t.assignee = assignee;
        t.createdBy = by;
        t.status = status;
        t.due = due;
        t.updatedAt = "2026-10-10T10:00:00Z";
        return t;
    }

    private final List<Task> all = Arrays.asList(
            t("water", "avi", "avi", "open", null),
            t("dog", "yoni", "avi", "open", "2026-10-11T17:00"),
            t("notebook", "avi", "maya", "requested", null),
            t("room", "yoni", "dana", "done", "2026-10-10"),
            t("grades", "avi", "avi", "open", "2026-10-11T08:00"));

    @Test
    public void tabs() {
        assertEquals(Arrays.asList("notebook", "grades", "water"), ids(TaskLists.mine(all, "avi")));
        assertEquals(Arrays.asList("dog"), ids(TaskLists.asked(all, "avi")));
        assertEquals(Arrays.asList("room"), ids(TaskLists.family(all, "avi")));
        assertEquals(Arrays.asList("notebook"), ids(TaskLists.needMyOk(all, "avi", true)));
        assertTrue(TaskLists.needMyOk(all, "yoni", false).isEmpty());
        assertEquals(2, TaskLists.openCount(all, "avi"));
    }

    @Test
    public void alertTime() {
        Task a = t("a", "avi", "avi", "open", "2026-10-11");
        assertNull(a.alertAt());                         // a day without a time: morning summary only
        a.due = "2026-10-11T17:00";
        assertEquals("2026-10-11T17:00", a.alertAt());
        a.snoozedUntil = "2026-10-11T20:00";
        assertEquals("2026-10-11T20:00", a.alertAt());
        a.status = "done";
        assertNull(a.alertAt());
    }

    @Test
    public void timeMath() {
        long ms = TaskLists.toMillis("2026-10-10T18:30", TZ);
        assertEquals("2026-10-10T18:30", TaskLists.format(ms, TZ));
        assertEquals("2026-10-10T19:30", TaskLists.inAnHour(ms, TZ));
        assertEquals("2026-10-10T20:00", TaskLists.tonight(ms, TZ));
        assertNull(TaskLists.tonight(TaskLists.toMillis("2026-10-10T19:10", TZ), TZ));
        assertEquals("2026-10-11T08:00", TaskLists.tomorrowMorning(ms, TZ));
        assertEquals("2026-10-11T08:00", TaskLists.format(TaskLists.nextMorning(ms, TZ, 8), TZ));
        long early = TaskLists.toMillis("2026-10-10T06:00", TZ);
        assertEquals("2026-10-10T08:00", TaskLists.format(TaskLists.nextMorning(early, TZ, 8), TZ));
        assertEquals(-1, TaskLists.toMillis("soon", TZ));
        // Israel's clocks go back on 25 Oct 2026: the day after still rings at 08:00 local
        long beforeDst = TaskLists.toMillis("2026-10-24T21:00", TZ);
        assertEquals("2026-10-25T08:00", TaskLists.tomorrowMorning(beforeDst, TZ));
    }

    @Test
    public void morningAndNews() {
        assertEquals(Arrays.asList("water"), ids(TaskLists.forMorning(all, "avi", "2026-10-10")));
        assertEquals(Arrays.asList("grades", "water"), ids(TaskLists.forMorning(all, "avi", "2026-10-11")));
        assertEquals(Arrays.asList("dog"), ids(TaskLists.news(all, "yoni", false, new HashSet<>())));
        assertEquals(Arrays.asList("notebook"), ids(TaskLists.news(all, "dana", true, new HashSet<>())));
        assertTrue(TaskLists.news(all, "yoni", false, new HashSet<>(Arrays.asList("dog"))).isEmpty());
    }

    @Test
    public void whatsappDraft() {
        Task m = t("msg", "avi", "avi", "open", null);
        m.kind = "message";
        m.message = "אני מגיע בשש & see you";
        m.phone = "972501234567";
        assertEquals("https://wa.me/972501234567?text=%D7%90%D7%A0%D7%99%20%D7%9E%D7%92%D7%99%D7%A2%20"
                + "%D7%91%D7%A9%D7%A9%20%26%20see%20you", m.whatsappUrl());
        m.phone = "";
        assertTrue(m.whatsappUrl().startsWith("https://wa.me/?text="));
        // my own memo made it, but I still get told it's ready to send
        assertEquals(Arrays.asList("msg"), ids(TaskLists.news(Arrays.asList(m), "avi", true, new HashSet<>())));
    }

    private static List<String> ids(List<Task> ts) {
        String[] out = new String[ts.size()];
        for (int i = 0; i < out.length; i++) out[i] = ts.get(i).id;
        return Arrays.asList(out);
    }

    @Test
    public void widgetShowsRequestsThenMyOpenTasks() {
        java.util.List<Task> all = java.util.Arrays.asList(
                t("later", "dana", "dana", "open", null),
                t("soon", "dana", "dana", "open", "2026-10-12T09:00"),
                t("done", "dana", "dana", "done", "2026-10-11"),
                t("ask", "dana", "yoni", "requested", null),
                t("kids", "yoni", "dana", "open", "2026-10-11"));
        java.util.List<String> ids = new java.util.ArrayList<>();
        for (Task x : TaskLists.forWidget(all, "dana", true, 10)) ids.add(x.id);
        org.junit.Assert.assertEquals(java.util.Arrays.asList("ask", "soon", "later"), ids);
        org.junit.Assert.assertEquals(1, TaskLists.forWidget(all, "dana", true, 1).size());
        org.junit.Assert.assertEquals(2, TaskLists.forWidget(all, "dana", false, 10).size());   // a child approves nothing
    }

    private static Task.Note note(int id, String by, boolean ask) {
        Task.Note n = new Task.Note();
        n.id = id;
        n.by = by;
        n.text = "?";
        n.ask = ask;
        return n;
    }

    @Test
    public void questionWaitingOnMeIsMineAndFirst() {
        Task a = t("a", "dana", "dana", "open", "2026-10-11");
        Task q = t("q", "yoni", "dana", "open", null);           // Dana gave Yoni a task; Yoni asked back
        q.thread.add(note(1, "yoni", true));
        q.waitingOn = "dana";
        java.util.List<Task> all = java.util.Arrays.asList(a, q);
        org.junit.Assert.assertEquals("q", TaskLists.mine(all, "dana").get(0).id);
        org.junit.Assert.assertEquals("q", TaskLists.forWidget(all, "dana", true, 10).get(0).id);
        org.junit.Assert.assertEquals("dana", q.counterpart("yoni"));
        org.junit.Assert.assertEquals("yoni", q.counterpart("dana"));
        org.junit.Assert.assertEquals("", a.counterpart("dana"));
    }

    @Test
    public void newNotesFromOthersOnly() {
        Task q = t("q", "yoni", "dana", "open", null);
        q.thread.add(note(1, "yoni", true));
        java.util.Set<String> seen = new java.util.HashSet<>();
        org.junit.Assert.assertEquals(1, TaskLists.newNotes(java.util.Collections.singletonList(q), "dana", seen).size());
        org.junit.Assert.assertEquals(0, TaskLists.newNotes(java.util.Collections.singletonList(q), "yoni", seen).size());
        seen.add(TaskLists.noteKey(q));
        org.junit.Assert.assertEquals(0, TaskLists.newNotes(java.util.Collections.singletonList(q), "dana", seen).size());
        q.thread.add(note(2, "yoni", false));                       // another note: news again
        org.junit.Assert.assertEquals(1, TaskLists.newNotes(java.util.Collections.singletonList(q), "dana", seen).size());
    }
}
