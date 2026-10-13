package com.noam.jar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import com.noam.jar.core.TaskLists;

import java.util.TimeZone;

/** Reminder alarms, the morning summary, and the Done / Snooze / Accept buttons on notifications. */
public final class TaskReceiver extends BroadcastReceiver {
    static final String REMIND = "com.noam.jar.TASK_REMIND";
    static final String MORNING = "com.noam.jar.TASK_MORNING";
    static final String WEEKLY = "com.noam.jar.TASK_WEEKLY";
    static final String ACT = "com.noam.jar.TASK_ACT";
    static final String EXTRA_ID = "id";
    static final String EXTRA_ACTION = "action";
    static final String EXTRA_SNOOZE = "snooze";

    @Override
    public void onReceive(Context c, Intent intent) {
        String a = intent.getAction();
        if (REMIND.equals(a)) {
            TaskNotify.remind(c, intent.getStringExtra(EXTRA_ID));
        } else if (MORNING.equals(a)) {
            TaskNotify.morning(c);
        } else if (WEEKLY.equals(a)) {
            BroadcastReceiver.PendingResult result = goAsync();
            new Thread(() -> {
                try {
                    TaskNotify.weekly(c);
                } finally {
                    result.finish();
                }
            }, "jar-weekly").start();
        } else if (ACT.equals(a)) {
            String id = intent.getStringExtra(EXTRA_ID);
            String action = intent.getStringExtra(EXTRA_ACTION);
            String until = null;
            if ("snooze".equals(action)) {
                long now = System.currentTimeMillis();
                TimeZone tz = TimeZone.getDefault();
                until = "tomorrow".equals(intent.getStringExtra(EXTRA_SNOOZE))
                        ? TaskLists.tomorrowMorning(now, tz) : TaskLists.inAnHour(now, tz);
            }
            if (id != null && action != null) apply(c, id, action, until);
        }
    }

    /** A change made on this phone: shown at once, sent to the PC now or when it's reachable. */
    static void apply(Context c, String taskId, String action, String until) {
        TaskCache cache = new TaskCache(c);
        cache.queue(taskId, action, until);
        TaskNotify.cancel(c, taskId);
        TaskNotify.scheduleReminders(c);
        Jar.notifyState(c);
        TaskSync.now(c);
    }
}
