package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** 1.4.0: moving a task to the owner of its area of responsibility. */
public class AreasTest {
    private static Task t(String id, String assignee, String by) {
        Task t = new Task();
        t.id = id;
        t.title = id;
        t.assignee = assignee;
        t.createdBy = by;
        t.status = "open";
        t.updatedAt = "2026-10-22T10:00:00Z";
        return t;
    }

    private static List<String> ids(List<Task> list) {
        List<String> out = new ArrayList<>();
        for (Task x : list) out.add(x.id);
        return out;
    }

    @Test
    public void whoApprovesAMove() {
        Task floor = t("floor", "livne", "livne");
        floor.handoverTo = "sveta";
        floor.handoverBy = "livne";
        assertTrue(floor.mayApproveHandover("sveta", true));        // the area's owner
        assertTrue(floor.mayApproveHandover("noam", true));         // a parent
        assertFalse(floor.mayApproveHandover("alona", false));      // another child
        assertFalse(floor.mayApproveHandover("livne", false));      // the one who asked

        Task laundry = t("laundry", "noam", "noam");
        laundry.handoverTo = "alona";
        laundry.handoverBy = "noam";
        assertFalse(laundry.mayApproveHandover("noam", true));      // a parent can't approve their own request
        assertTrue(laundry.mayApproveHandover("alona", false));     // a child approves a move into her area

        List<Task> all = Arrays.asList(floor, laundry);
        assertEquals(Arrays.asList("laundry"), ids(TaskLists.needMyOk(all, "alona", false)));
        assertEquals(Arrays.asList("floor"), ids(TaskLists.needMyOk(all, "noam", true)));
    }

    @Test
    public void theOwnerHearsAboutItOnce() {
        Task floor = t("floor", "livne", "livne");
        floor.handoverTo = "sveta";
        floor.handoverBy = "livne";
        Set<String> seen = new HashSet<>(Arrays.asList("floor"));      // the task itself was seen long ago
        assertEquals(Arrays.asList("floor"), ids(TaskLists.news(Arrays.asList(floor), "sveta", true, false, seen)));
        seen.add(TaskLists.handoverKey(floor));
        assertEquals(new ArrayList<String>(), ids(TaskLists.news(Arrays.asList(floor), "sveta", true, false, seen)));
    }

    @Test
    public void areaLabel() {
        Area a = new Area();
        a.name = "רצפות";
        a.emoji = "🧽";
        assertEquals("🧽 רצפות", a.label());
    }
}
