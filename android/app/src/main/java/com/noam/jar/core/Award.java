package com.noam.jar.core;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * What a finished task paid, from the PC's answer to "done": coins, the factors that made them
 * (effort E, repeat R, streak S, timing T, habit) and this week's total. Phase 1 only has E; the
 * others are already read so the toast explains them as soon as the PC sends them.
 */
public final class Award {
    public boolean fresh;           // false = the PC had already paid this task (a retried tick)
    public int coins;
    public int weekTotal;
    public double effort = 1, repeat = 1, streak = 1, timing = 1, habit = 1;
    public int fixed;               // a work day: the fixed base instead of a formula

    /** The factors that are not 1.0, as "R", "S", "T" or "H" with their value, in the order the toast lists them. */
    public List<String[]> parts() {
        List<String[]> out = new ArrayList<>();
        add(out, "T", timing);
        add(out, "S", streak);
        add(out, "R", repeat);
        add(out, "H", habit);
        return out;
    }

    private static void add(List<String[]> out, String key, double v) {
        if (Math.abs(v - 1.0) > 0.001) out.add(new String[]{key, String.format(Locale.US, "×%s", trim(v))});
    }

    static String trim(double v) {
        String s = String.format(Locale.US, "%.2f", v);
        s = s.indexOf('.') < 0 ? s : s.replaceAll("0+$", "").replaceAll("\\.$", "");
        return s;
    }

    public boolean worthShowing() {
        return fresh && coins > 0;
    }
}
