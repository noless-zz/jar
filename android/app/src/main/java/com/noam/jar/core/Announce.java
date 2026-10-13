package com.noam.jar.core;

import java.util.Calendar;
import java.util.Locale;
import java.util.TimeZone;

/** When the phones announce the week's result: the PC's "sat 20:00" setting. */
public final class Announce {
    public final int dayOfWeek;     // Calendar.SATURDAY…
    public final int hour;
    public final int minute;

    private Announce(int day, int hour, int minute) {
        this.dayOfWeek = day;
        this.hour = hour;
        this.minute = minute;
    }

    /** "sat 20:00", "Friday 19:30"; anything unreadable means Saturday 20:00. */
    public static Announce parse(String text) {
        Announce fallback = new Announce(Calendar.SATURDAY, 20, 0);
        if (text == null) return fallback;
        String[] parts = text.trim().toLowerCase(Locale.US).split("\\s+");
        if (parts.length != 2) return fallback;
        int day = day(parts[0]);
        String[] hm = parts[1].split(":");
        if (day < 0 || hm.length != 2) return fallback;
        try {
            int h = Integer.parseInt(hm[0]), m = Integer.parseInt(hm[1]);
            if (h < 0 || h > 23 || m < 0 || m > 59) return fallback;
            return new Announce(day, h, m);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static int day(String word) {
        String[] names = {"sun", "mon", "tue", "wed", "thu", "fri", "sat"};
        for (int i = 0; i < names.length; i++) if (word.startsWith(names[i])) return Calendar.SUNDAY + i;
        return -1;
    }

    /** The next time (strictly after {@code now}) this day and time comes round. */
    public long next(long now, TimeZone tz) {
        Calendar c = Calendar.getInstance(tz);
        c.setTimeInMillis(now);
        c.set(Calendar.HOUR_OF_DAY, hour);
        c.set(Calendar.MINUTE, minute);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        int ahead = (dayOfWeek - c.get(Calendar.DAY_OF_WEEK) + 7) % 7;
        c.add(Calendar.DAY_OF_MONTH, ahead);
        if (c.getTimeInMillis() <= now) c.add(Calendar.DAY_OF_MONTH, 7);
        return c.getTimeInMillis();
    }
}
