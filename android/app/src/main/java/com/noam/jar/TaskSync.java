package com.noam.jar;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

/**
 * Keeps the phone's task list in step with the PC: sends ticks/snoozes made on the phone
 * (also offline ones), fetches the list, then sets the reminders and tells about new tasks.
 * Runs every 15 minutes in the background, and right away after any change or when the list opens.
 */
public final class TaskSync extends Worker {
    private static final String NOW = "jar-tasks-now";
    private static final String PERIODIC = "jar-tasks-periodic";

    public TaskSync(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    private static Constraints online() {
        return new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    }

    public static void now(Context c) {
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(TaskSync.class)
                .setConstraints(online())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();
        WorkManager.getInstance(c).enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, req);
    }

    /** After a memo upload: the PC needs a little while to turn it into a task. */
    public static void soon(Context c) {
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(TaskSync.class)
                .setConstraints(online())
                .setInitialDelay(45, TimeUnit.SECONDS)
                .build();
        WorkManager.getInstance(c).enqueueUniqueWork("jar-tasks-soon", ExistingWorkPolicy.REPLACE, req);
    }

    public static void schedule(Context c) {
        PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(TaskSync.class, 15, TimeUnit.MINUTES)
                .setConstraints(online()).build();
        WorkManager.getInstance(c).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, req);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context c = getApplicationContext();
        Prefs prefs = new Prefs(c);
        TaskCache cache = new TaskCache(c);
        if (prefs.token().isEmpty() || prefs.offlineSim()) return Result.success();
        try {
            flush(c, prefs, cache);
            JSONObject me = TaskApi.me(prefs);
            cache.setMe(me);
            JSONArray urls = me.optJSONArray("urls");
            if (urls != null) {
                java.util.List<String> got = new java.util.ArrayList<>();
                for (int i = 0; i < urls.length(); i++) got.add(urls.optString(i));
                prefs.mergeServerUrls(got);
            }
            cache.setTasks(TaskApi.tasks(prefs));
            try {
                cache.setPoints(TaskApi.points(prefs));
            } catch (TaskApi.HttpError e) {
                if (e.code == 401) throw e;
                // an older PC without the points game: the rest of the list still works
            }
        } catch (TaskApi.HttpError e) {
            prefs.setTaskProblem(e.code == 401 ? c.getString(R.string.tasks_bad_token) : e.getMessage());
            Jar.notifyState(c);
            return e.code == 401 ? Result.failure() : Result.retry();
        } catch (IOException e) {
            prefs.setTaskProblem(c.getString(R.string.tasks_offline));
            Jar.notifyState(c);
            return Result.retry();
        }
        try {
            JSONArray last = TaskApi.lastMemo(prefs).optJSONArray("memos");
            cache.setLastMemo(last != null && last.length() > 0 ? last.optJSONObject(0) : null);
        } catch (IOException ignored) {
            // the widget keeps the previous line
        }
        prefs.setTaskProblem("");
        TaskNotify.afterSync(c);
        TaskNotify.scheduleWeekly(c);
        try {
            if (Updater.check(c, false)) TaskNotify.updateAvailable(c, Updater.availableTag(c));
        } catch (IOException ignored) {
            // GitHub unreachable: try again next sync
        }
        Jar.notifyState(c);
        return Result.success();
    }

    /** Send the queued changes in order. One the PC refuses for good (gone, not allowed) is dropped. */
    private static void flush(Context c, Prefs prefs, TaskCache cache) throws IOException {
        JSONArray pending = cache.pending();
        int done = 0;
        try {
            for (; done < pending.length(); done++) {
                JSONObject a = pending.optJSONObject(done);
                if (a == null) continue;
                try {
                    JSONObject r = TaskApi.act(prefs, a.optString("id"), a.optString("action"),
                            a.isNull("until") ? null : a.optString("until", null), a.optLong("at", 0));
                    if ("done".equals(a.optString("action"))) PointsUi.toast(c, TaskApi.parseAward(r));
                } catch (TaskApi.HttpError e) {
                    if (e.code == 401 || e.code >= 500) throw e;   // keep it for later
                    // 400/403/404/409: this change can never apply; drop it and carry on
                }
            }
        } finally {
            cache.dropPending(done);
        }
    }
}
