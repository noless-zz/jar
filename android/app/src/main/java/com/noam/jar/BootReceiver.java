package com.noam.jar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Alarms don't survive a restart or an app update: set the reminders again. */
public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent intent) {
        String a = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(a) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) {
            new TaskCache(c).setAlarms(new java.util.HashMap<>());   // all cleared by the system
            TaskNotify.scheduleReminders(c);
            TaskNotify.scheduleMorning(c);
            TaskSync.schedule(c);
        }
    }
}
