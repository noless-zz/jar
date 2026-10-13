package com.noam.jar;

import android.Manifest;
import android.app.AlarmManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;

/** Reminders, "new task" alerts and the morning summary, with Done / Snooze buttons. */
public final class TaskNotify {
    static final String CH_REMIND = "task_reminders";
    static final String CH_NEW = "task_new";
    static final String CH_MORNING = "task_morning";
    static final int MORNING_HOUR = 8;
    private static final int MORNING_ID = 7000;

    private TaskNotify() {}

    static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return;
        nm.createNotificationChannel(new NotificationChannel(CH_REMIND,
                c.getString(R.string.channel_task_reminders), NotificationManager.IMPORTANCE_HIGH));
        nm.createNotificationChannel(new NotificationChannel(CH_NEW,
                c.getString(R.string.channel_task_new), NotificationManager.IMPORTANCE_DEFAULT));
        nm.createNotificationChannel(new NotificationChannel(CH_MORNING,
                c.getString(R.string.channel_task_morning), NotificationManager.IMPORTANCE_LOW));
    }

    // ---------------------------------------------------------------- after every sync

    static void afterSync(Context c) {
        TaskCache cache = new TaskCache(c);
        String me = cache.myId();
        if (me.isEmpty()) return;
        List<Task> tasks = cache.tasks();
        Set<String> seen = cache.seen();
        if (!cache.firstSyncDone()) {
            // Just paired: don't fire a burst of alerts for everything that already exists.
            for (Task t : tasks) seen.add(t.id);
            cache.setSeen(seen);
            cache.setFirstSyncDone();
        } else {
            for (Task t : TaskLists.news(tasks, me, cache.iAmParent(), seen)) {
                showNew(c, cache, t);
                seen.add(t.id);
            }
            cache.setSeen(seen);
        }
        scheduleReminders(c);
        scheduleMorning(c);
    }

    // ---------------------------------------------------------------- alarms

    /** One alarm per open task of mine with a time; changed times replace the old alarm. */
    static void scheduleReminders(Context c) {
        TaskCache cache = new TaskCache(c);
        String me = cache.myId();
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am == null || me.isEmpty()) return;
        TimeZone tz = TimeZone.getDefault();
        long now = System.currentTimeMillis();
        Map<String, Long> old = cache.alarms(), next = new HashMap<>();
        for (Task t : cache.tasks()) {
            if (!me.equals(t.assignee)) continue;
            long at = TaskLists.toMillis(t.alertAt(), tz);
            if (at < 0) continue;
            String key = t.id + "@" + t.alertAt();
            if (cache.alreadyRang(key)) continue;
            if (at <= now) {
                if (now - at < 12 * 3600 * 1000L) remind(c, t.id);   // missed while off/asleep
                continue;
            }
            next.put(t.id, at);
            if (old.containsKey(t.id) && old.get(t.id) == at) continue;   // already set
            set(am, at, remindIntent(c, t.id));
        }
        for (String id : old.keySet()) {
            if (!next.containsKey(id)) am.cancel(remindIntent(c, id));
        }
        cache.setAlarms(next);
    }

    static void scheduleMorning(Context c) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am == null) return;
        long at = TaskLists.nextMorning(System.currentTimeMillis(), TimeZone.getDefault(), MORNING_HOUR);
        am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, morningIntent(c));
    }

    private static void set(AlarmManager am, long at, PendingIntent pi) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        } else {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);   // within a few minutes
        }
    }

    private static PendingIntent remindIntent(Context c, String taskId) {
        Intent i = new Intent(c, TaskReceiver.class).setAction(TaskReceiver.REMIND)
                .setData(android.net.Uri.parse("jar-task://" + taskId))
                .putExtra(TaskReceiver.EXTRA_ID, taskId);
        return PendingIntent.getBroadcast(c, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static PendingIntent morningIntent(Context c) {
        Intent i = new Intent(c, TaskReceiver.class).setAction(TaskReceiver.MORNING);
        return PendingIntent.getBroadcast(c, 1, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    // ---------------------------------------------------------------- notifications

    /** The reminder itself, at the due/snooze time. */
    static void remind(Context c, String taskId) {
        TaskCache cache = new TaskCache(c);
        Task t = cache.find(taskId);
        if (t == null || t.alertAt() == null || !cache.myId().equals(t.assignee)) return;
        cache.markRang(t.id + "@" + t.alertAt());
        Map<String, String> names = cache.names();
        String text = t.createdBy.equals(t.assignee) ? c.getString(R.string.notif_reminder)
                : c.getString(R.string.notif_from, TaskLists.name(names, t.createdBy));
        NotificationCompat.Builder b = base(c, CH_REMIND, t.title, text)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .addAction(0, c.getString(R.string.action_done), action(c, t.id, "done", null))
                .addAction(0, c.getString(R.string.snooze_hour), action(c, t.id, "snooze", "hour"))
                .addAction(0, c.getString(R.string.snooze_tomorrow), action(c, t.id, "snooze", "tomorrow"));
        post(c, id(t.id), b);
    }

    /** "Dana gave you a task" / "Maya asks: …" (parents approve). */
    static void showNew(Context c, TaskCache cache, Task t) {
        Map<String, String> names = cache.names();
        NotificationCompat.Builder b;
        if (t.isMessage()) {
            PendingIntent send = PendingIntent.getActivity(c, id(t.id), new Intent(c, TasksActivity.class)
                            .putExtra(TasksActivity.EXTRA_SEND, t.id)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            b = base(c, CH_NEW, c.getString(R.string.notif_message_ready, t.title), t.message)
                    .setStyle(new NotificationCompat.BigTextStyle().bigText(t.message))
                    .setContentIntent(send)
                    .addAction(0, c.getString(R.string.send_whatsapp), send);
            post(c, id(t.id), b);
            return;
        }
        if (t.isRequested()) {
            String text = c.getString(R.string.notif_request, TaskLists.name(names, t.createdBy),
                    TaskLists.name(names, t.assignee));
            b = base(c, CH_NEW, t.title, text)
                    .addAction(0, c.getString(R.string.action_accept), action(c, t.id, "accept", null))
                    .addAction(0, c.getString(R.string.action_decline), action(c, t.id, "decline", null));
        } else {
            String text = c.getString(R.string.notif_new_from, TaskLists.name(names, t.createdBy))
                    + (t.due == null ? "" : " · " + TaskFormat.when(c, t.due));
            b = base(c, CH_NEW, t.title, text)
                    .addAction(0, c.getString(R.string.action_done), action(c, t.id, "done", null));
        }
        post(c, id(t.id), b);
    }

    /** 08:00: what's open today, so tasks without a time aren't forgotten. */
    static void morning(Context c) {
        TaskCache cache = new TaskCache(c);
        String me = cache.myId();
        scheduleMorning(c);
        if (me.isEmpty()) return;
        TimeZone tz = TimeZone.getDefault();
        List<Task> today = TaskLists.forMorning(cache.tasks(), me, TaskLists.day(System.currentTimeMillis(), tz));
        if (today.isEmpty()) return;
        NotificationCompat.InboxStyle inbox = new NotificationCompat.InboxStyle();
        for (int i = 0; i < today.size() && i < 6; i++) inbox.addLine("• " + today.get(i).title);
        String title = c.getResources().getQuantityString(R.plurals.morning_title, today.size(), today.size());
        NotificationCompat.Builder b = base(c, CH_MORNING, title, today.get(0).title).setStyle(inbox);
        post(c, MORNING_ID, b);
    }

    private static NotificationCompat.Builder base(Context c, String channel, String title, String text) {
        channels(c);
        PendingIntent open = PendingIntent.getActivity(c, 0, new Intent(c, TasksActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(c, channel)
                .setSmallIcon(R.drawable.ic_task)
                .setColor(ContextCompat.getColor(c, R.color.accent))
                .setContentTitle(title)
                .setContentText(text)
                .setContentIntent(open)
                .setAutoCancel(true);
    }

    private static PendingIntent action(Context c, String taskId, String action, String snooze) {
        Intent i = new Intent(c, TaskReceiver.class).setAction(TaskReceiver.ACT)
                .setData(android.net.Uri.parse("jar-task://" + taskId + "/" + action + "/" + snooze))
                .putExtra(TaskReceiver.EXTRA_ID, taskId)
                .putExtra(TaskReceiver.EXTRA_ACTION, action)
                .putExtra(TaskReceiver.EXTRA_SNOOZE, snooze);
        return PendingIntent.getBroadcast(c, 2, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** Once per new version: "Jar 0.4.0 is ready — tap to update". */
    static void updateAvailable(Context c, String tag) {
        if (tag == null) return;
        android.content.SharedPreferences sp = c.getSharedPreferences("jar_update", Context.MODE_PRIVATE);
        if (tag.equals(sp.getString("notified_tag", null))) return;
        sp.edit().putString("notified_tag", tag).apply();
        String news = Updater.whatsNew(c);
        post(c, 7001, base(c, CH_NEW, c.getString(R.string.update_notif_title, tag),
                news.isEmpty() ? c.getString(R.string.update_notif_text) : news));
    }

    static int id(String taskId) {
        return 10000 + (taskId.hashCode() & 0x3fffffff);
    }

    private static void post(Context c, int id, NotificationCompat.Builder b) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && ContextCompat.checkSelfPermission(c, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        NotificationManagerCompat.from(c).notify(id, b.build());
    }

    static void cancel(Context c, String taskId) {
        NotificationManagerCompat.from(c).cancel(id(taskId));
    }
}
