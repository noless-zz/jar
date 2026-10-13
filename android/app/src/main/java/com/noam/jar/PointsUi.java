package com.noam.jar;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import com.noam.jar.core.Award;

import java.util.ArrayList;
import java.util.List;

/** Wording for coins: the toast after a task is done ("+9 🪙 — on time ×1.2, streak ×1.1"). */
final class PointsUi {
    private PointsUi() {}

    /** The factors that changed the coins, in words ("on time ×1.2"); empty in phase 1, where only effort counts. */
    static String why(Context c, Award a) {
        List<String> out = new ArrayList<>();
        for (String[] part : a.parts()) {
            int res;
            switch (part[0]) {
                case "T":
                    res = a.timing > 1 ? R.string.award_on_time : R.string.award_late;
                    break;
                case "S":
                    res = R.string.award_streak;
                    break;
                case "R":
                    res = R.string.award_repeat;
                    break;
                default:
                    res = R.string.award_habit;
            }
            out.add(c.getString(res, part[1]));
        }
        return String.join(", ", out);
    }

    static String text(Context c, Award a) {
        String why = why(c, a);
        return why.isEmpty() ? c.getString(R.string.award_toast, a.coins)
                : c.getString(R.string.award_toast_why, a.coins, why);
    }

    /** From any thread (the sync worker too). Nothing for a task that paid nothing or was already paid. */
    static void toast(Context c, Award a) {
        if (a == null || !a.worthShowing()) return;
        String msg = text(c, a);
        new Handler(Looper.getMainLooper()).post(() -> Toast.makeText(c, msg, Toast.LENGTH_LONG).show());
    }
}
