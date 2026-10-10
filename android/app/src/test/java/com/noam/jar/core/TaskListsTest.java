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

    private static List<String> ids(List<Task> ts) {
        String[] out = new String[ts.size()];
        for (int i = 0; i < out.length; i++) out[i] = ts.get(i).id;
        return Arrays.asList(out);
    }
}
