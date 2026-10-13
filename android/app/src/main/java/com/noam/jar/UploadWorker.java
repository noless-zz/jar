package com.noam.jar;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.noam.jar.core.Memo;
import com.noam.jar.core.MemoQueue;

import java.util.concurrent.TimeUnit;

/**
 * Drains the memo queue. WorkManager waits for a network, survives the app
 * being closed, and retries with back-off — the phone version of the pendant's
 * "retry every 15 s until the server acknowledges".
 */
public final class UploadWorker extends Worker {
    private static final String WORK_NAME = "jar-upload";

    public UploadWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    /** "Upload now", a new pairing, a passed connection test: skip any back-off and try at once. */
    public static void now(Context c) {
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(UploadWorker.class)
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();
        WorkManager.getInstance(c).enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, req);
    }

    public static void enqueue(Context c) {
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(UploadWorker.class)
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();
        // APPEND_OR_REPLACE: a memo saved during an upload run still gets its own run afterwards.
        WorkManager.getInstance(c).enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, req);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context c = getApplicationContext();
        Prefs prefs = new Prefs(c);
        if (prefs.offlineSim()) return Result.success();   // memos wait until the switch is off

        MemoQueue queue = Jar.queue(c);
        for (Memo memo : queue.ready()) {
            if (prefs.offlineSim()) break;                    // switched on mid-run
            Uploader.Outcome o = Uploader.upload(prefs, memo);
            switch (o.result) {
                case DELETE_LOCAL:
                    queue.remove(memo);
                    prefs.addHistory(c.getString(R.string.history_uploaded,
                            Jar.localTime(), Jar.seconds(memo.durationMs)));
                    Jar.notifyState(c);
                    break;
                case KEEP_AND_FLAG:
                    // Retrying won't help (wrong token, conflicting id): wait for the user.
                    prefs.addHistory(c.getString(R.string.history_refused, Jar.localTime(), o.detail));
                    Jar.notifyState(c);
                    return Result.failure();
                case RETRY:
                default:
                    prefs.addHistory(c.getString(R.string.history_retry, Jar.localTime(), o.detail));
                    Jar.notifyState(c);
                    return Result.retry();
            }
        }
        TaskSync.soon(c);   // a memo like "remind Yoni…" shows up as a task shortly
        return Result.success();
    }
}
