package com.noam.jar.core;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The leaderboard from GET /v1/points: this week (Sunday to Saturday) and all time per person, each
 * person's ledger as I may see it, recent lesson notes, and the week's result. Plain fields so the
 * logic can be unit-tested without Android.
 */
public final class Board {
    public String weekStart = "";
    public String weekEnd = "";
    public String me = "";
    public int workDayCoins = 30;
    public String announce = "sat 20:00";
    /** Already sorted by this week's coins, then all-time. */
    public List<Person> people = new ArrayList<>();
    public Map<String, List<Line>> ledgers = new HashMap<>();
    public List<Lesson> lessons = new ArrayList<>();
    public Summary summary = new Summary();

    public static final class Person {
        public String id = "";
        public String name = "";
        public String role = "";
        public int week;
        public int allTime;
        public int tasksWeek;
        public int streak;
        public int bestCoins;           // 0 = no best chore yet
        public String bestCategory = "";
        public String bestTitle;        // null = private to someone else
    }

    public static final class Line {
        public int id;
        public String title;            // null = a task I may not see
        public String kind = "task";
        public String category = "";
        public String at = "";
        public int coins;
        public boolean reversed;
        public String reversedWhy = "";
        public String note;
        public String ratedBy = "";
    }

    public static final class Lesson {
        public String person = "";
        public String name = "";
        public String title = "";
        public String note = "";
        public int coins;
        public String at = "";
    }

    public static final class Summary {
        public String weekStart = "";
        public int top;
        public List<String> winners = new ArrayList<>();
        public List<Person> totals = new ArrayList<>();     // id, name, week = coins
        public String improvedId = "";
        public String improvedName = "";
        public int improvedPct;
    }

    public Person person(String id) {
        for (Person p : people) if (p.id.equals(id)) return p;
        return null;
    }

    /** Who leads this week, or null while nobody has earned anything (ties: the first listed). */
    public Person leader() {
        return !people.isEmpty() && people.get(0).week > 0 ? people.get(0) : null;
    }

    /** True when the top spot is shared. */
    public boolean tied() {
        return people.size() > 1 && people.get(0).week > 0 && people.get(0).week == people.get(1).week;
    }

    /** The widget footer's numbers: the leader's name and coins, and mine ("" name = nobody leads yet). */
    public int myWeek() {
        Person p = person(me);
        return p == null ? 0 : p.week;
    }

    public List<Line> ledger(String id) {
        List<Line> l = ledgers.get(id);
        return l == null ? new ArrayList<>() : l;
    }

    /** The names of the week's winners (more than one on a tie), from the PC's summary. */
    public List<String> winnerNames() {
        List<String> out = new ArrayList<>();
        for (String id : summary.winners) {
            String name = id;
            for (Person t : summary.totals) if (t.id.equals(id)) name = t.name;
            out.add(name);
        }
        return out;
    }
}
