package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Shared family tasks: several people, "one of them" or "each of them". */
public class SharedTaskTest {
    private static Task shared(String id, String mode, String... who) {
        Task t = new Task();
        t.id = id;
        t.title = id;
        t.assignee = who[0];
        t.assignees.addAll(Arrays.asList(who));
        t.mode = mode;
        t.createdBy = "dana";
        t.status = "open";
        t.updatedAt = "2026-10-18T10:00:00Z";
        return t;
    }

    @Test
    public void everyoneOnItHasIt() {
        Task t = shared("salon", "all", "yoni", "maya");
        List<Task> all = Collections.singletonList(t);
        for (String p : new String[] {"yoni", "maya"}) {
            assertEquals(1, TaskLists.mine(all, p).size());
            assertEquals(1, TaskLists.openCount(all, p));
        }
        assertTrue(TaskLists.mine(all, "avi").isEmpty());
        assertEquals(1, TaskLists.family(all, "avi").size());
        assertEquals(1, TaskLists.asked(all, "dana").size());
    }

    @Test
    public void eachPartIsMine() {
        Task t = shared("salon", "all", "yoni", "maya");
        t.doneParts.add("yoni");
        assertTrue(t.doneFor("yoni"));
        assertFalse(t.doneFor("maya"));
        assertTrue(t.openFor("maya"));
        List<Task> all = Collections.singletonList(t);
        assertEquals(0, TaskLists.openCount(all, "yoni"));
        assertEquals(1, TaskLists.openCount(all, "maya"));
        assertTrue(TaskLists.forWidget(all, "yoni", false, 5).isEmpty());
    }

    @Test
    public void oneOfThemIsEnough() {
        Task t = shared("bread", "any", "avi", "dana");
        assertFalse(t.eachMust());
        t.doneParts.add("avi");                   // ignored in "any" mode
        assertTrue(t.openFor("avi"));
        t.status = "done";
        assertTrue(t.doneFor("dana"));
    }

    @Test
    public void questionsGoToTheOthers() {
        Task t = shared("salon", "all", "yoni", "maya");
        assertEquals("dana", t.counterpart("yoni"));
        assertEquals("yoni", t.counterpart("avi"));
        Task mine = shared("gift", "any", "dana", "avi");
        assertEquals("avi", mine.counterpart("dana"));
    }

    @Test
    public void plainTaskStillWorks() {
        Task t = new Task();
        t.assignee = "yoni";
        assertEquals(Collections.singletonList("yoni"), t.owners());
        assertFalse(t.isShared());
        t.mode = "all";
        assertFalse(t.eachMust());
    }
}
