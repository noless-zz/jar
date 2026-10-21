package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;

/** 1.3.0: recurring-task occurrences and Jar ideas in the app's lists. */
public class RecurringIdeasTest {
    private static Task t(String id, String assignee, String by, String status, String kind, String updated) {
        Task t = new Task();
        t.id = id;
        t.title = id;
        t.assignee = assignee;
        t.createdBy = by;
        t.status = status;
        t.kind = kind;
        t.updatedAt = updated;
        return t;
    }

    private static List<String> ids(List<Task> list) {
        List<String> out = new ArrayList<>();
        for (Task t : list) out.add(t.id);
        return out;
    }

    private final List<Task> all = Arrays.asList(
            t("dark-mode", "avi", "yoni", "requested", "idea", "2026-10-20T10:00:00Z"),
            t("calendar", "avi", "yoni", "done", "idea", "2026-10-19T10:00:00Z"),
            t("repeats", "avi", "maya", "open", "idea", "2026-10-21T10:00:00Z"),
            t("old", "avi", "maya", "declined", "idea", "2026-10-22T10:00:00Z"),
            t("water", "avi", "avi", "open", "task", "2026-10-10T10:00:00Z"));

    @Test
    public void ideasHaveTheirOwnTab() {
        assertEquals(Arrays.asList("dark-mode", "repeats", "calendar", "old"), ids(TaskLists.ideas(all)));
        assertEquals(Arrays.asList("water"), ids(TaskLists.mine(all, "avi")));       // not among the admin's chores
        assertEquals(new ArrayList<String>(), ids(TaskLists.asked(all, "yoni")));
        assertEquals(new ArrayList<String>(), ids(TaskLists.needMyOk(all, "avi", true)));
        assertEquals(1, TaskLists.openCount(all, "avi"));
        assertFalse(all.get(0).canRate());
    }

    @Test
    public void onlyTheAdminHearsAboutNewIdeas() {
        assertEquals(Arrays.asList("dark-mode"), ids(TaskLists.news(all, "avi", true, true, new HashSet<>())));
        assertEquals(new ArrayList<String>(), ids(TaskLists.news(all, "dana", true, false, new HashSet<>())));
    }

    @Test
    public void occurrence() {
        Task o = t("trash", "yoni", "dana", "open", "task", "");
        assertFalse(o.isRecurring());
        o.seriesId = "s123";
        assertTrue(o.isRecurring());
        assertTrue(TaskLists.mineOpen(o, "yoni"));
    }

    @Test
    public void whoMayChangeASeries() {
        Series s = new Series();
        s.createdBy = "dana";
        s.owners.add("yoni");
        HashSet<String> parents = new HashSet<>(Arrays.asList("avi", "dana"));
        assertTrue(s.canChange("dana", false, true, parents));
        assertTrue(s.canChange("avi", true, true, parents));
        assertFalse(s.canChange("yoni", false, false, parents));        // given to him by a parent
        s.owners.add("dana");
        assertFalse(s.canChange("avi2", false, true, parents));          // includes a grown-up: not another parent's
    }
}
