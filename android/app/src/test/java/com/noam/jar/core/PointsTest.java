package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Calendar;
import java.util.List;
import java.util.TimeZone;

public class PointsTest {
    private static final TimeZone TZ = TimeZone.getTimeZone("Asia/Jerusalem");

    private static long at(int y, int m, int d, int h, int min) {
        Calendar c = Calendar.getInstance(TZ);
        c.clear();
        c.set(y, m - 1, d, h, min);
        return c.getTimeInMillis();
    }

    private static Board.Person person(String id, int week) {
        Board.Person p = new Board.Person();
        p.id = id;
        p.name = id.toUpperCase();
        p.week = week;
        return p;
    }

    @Test
    public void announcementTimeIsReadFromTheSetting() {
        Announce a = Announce.parse("sat 20:00");
        assertEquals(Calendar.SATURDAY, a.dayOfWeek);
        assertEquals(20, a.hour);
        a = Announce.parse("Friday 19:30");
        assertEquals(Calendar.FRIDAY, a.dayOfWeek);
        assertEquals(30, a.minute);
        for (String bad : new String[]{null, "", "soon", "sat", "sat 25:00", "xyz 10:00", "sat 10:99", "sat ab:cd"}) {
            Announce f = Announce.parse(bad);
            assertEquals(bad, Calendar.SATURDAY, f.dayOfWeek);
            assertEquals(bad, 20, f.hour);
        }
    }

    @Test
    public void nextAnnouncementIsTheComingSaturdayEvening() {
        Announce a = Announce.parse("sat 20:00");
        // Wednesday 14 Oct 2026 -> Saturday 17 Oct 20:00
        assertEquals(at(2026, 10, 17, 20, 0), a.next(at(2026, 10, 14, 9, 0), TZ));
        // Saturday before 20:00: today; at or after 20:00: next week
        assertEquals(at(2026, 10, 17, 20, 0), a.next(at(2026, 10, 17, 19, 59), TZ));
        assertEquals(at(2026, 10, 24, 20, 0), a.next(at(2026, 10, 17, 20, 0), TZ));
        // Sunday morning: six days ahead
        assertEquals(at(2026, 10, 17, 20, 0), a.next(at(2026, 10, 11, 8, 0), TZ));
    }

    @Test
    public void leaderIsTheTopOfTheWeekAndNobodyLeadsAtZero() {
        Board b = new Board();
        b.me = "yoni";
        assertNull(b.leader());
        b.people.add(person("dana", 0));
        b.people.add(person("yoni", 0));
        assertNull(b.leader());
        assertFalse(b.tied());
        b.people.clear();
        b.people.add(person("dana", 312));
        b.people.add(person("yoni", 280));
        assertEquals("dana", b.leader().id);
        assertEquals(280, b.myWeek());
        assertFalse(b.tied());
        b.people.get(1).week = 312;
        assertTrue(b.tied());
        assertEquals(0, new Board().myWeek());
        assertTrue(b.ledger("nobody").isEmpty());
    }

    @Test
    public void toastExplainsOnlyTheFactorsThatChangedTheCoins() {
        Award a = new Award();
        assertTrue(a.parts().isEmpty());
        a.timing = 1.2;
        a.streak = 1.3;
        a.repeat = 0.7;
        a.habit = 1.25;
        List<String[]> parts = a.parts();
        assertEquals(4, parts.size());
        assertEquals("T", parts.get(0)[0]);
        assertEquals("×1.2", parts.get(0)[1]);
        assertEquals("×1.3", parts.get(1)[1]);
        assertEquals("×0.7", parts.get(2)[1]);
        assertEquals("×1.25", parts.get(3)[1]);
        a.fresh = true;
        a.coins = 40;
        assertTrue(a.worthShowing());
        a.fresh = false;                          // a retried tick the PC already paid
        assertFalse(a.worthShowing());
        a.fresh = true;
        a.coins = 0;
        assertFalse(a.worthShowing());
    }

    @Test
    public void taskKnowsWhenAParentCanRateIt() {
        Task t = new Task();
        assertTrue(t.canRate());
        t.status = "done";
        assertTrue(t.canRate());
        t.status = "declined";
        assertFalse(t.canRate());
        t.status = "open";
        t.kind = "message";
        assertFalse(t.canRate());
        t.kind = "lesson";
        assertFalse(t.canRate());
        assertTrue(t.isLesson());
    }
}
