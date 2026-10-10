package com.noam.jar;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;
import androidx.core.content.ContextCompat;

import com.noam.jar.core.MemoQueue;
import com.noam.jar.core.Wav;

import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;

/**
 * Records one memo at a time, as a foreground service so it keeps going when the
 * screen turns off or the recording was started from the home-screen widget.
 * Audio format matches the pendant: 16 kHz, mono, 16-bit WAV.
 */
public final class RecorderService extends Service {
    public static final String ACTION_START = "com.noam.jar.START";
    public static final String ACTION_STOP = "com.noam.jar.STOP";
    public static final String ACTION_TOGGLE = "com.noam.jar.TOGGLE";

    private static final String CHANNEL = "recording";
    private static final int NOTIFICATION_ID = 1;
    private static final long MAX_MS = 5 * 60 * 1000;   // same cap as the firmware
    private static final long MIN_MS = 600;            // shorter = accidental press, discarded

    /** Read by the screen and the widget to show the right state. */
    private static volatile boolean recording;
    private static volatile long startedAt;            // SystemClock.elapsedRealtime()

    private final Handler main = new Handler(Looper.getMainLooper());
    private Thread worker;
    private volatile boolean stopRequested;

    public static boolean isRecording() {
        return recording;
    }

    public static long elapsedMs() {
        return recording ? SystemClock.elapsedRealtime() - startedAt : 0;
    }

    public static void send(Context c, String action) {
        Intent i = new Intent(c, RecorderService.class).setAction(action);
        if (ACTION_STOP.equals(action) || (ACTION_TOGGLE.equals(action) && recording)) {
            c.startService(i);   // already in the foreground: a plain start is enough
        } else {
            ContextCompat.startForegroundService(c, i);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_TOGGLE.equals(action)) action = recording ? ACTION_STOP : ACTION_START;

        if (ACTION_START.equals(action) && !recording) {
            if (!goForeground()) {
                stopSelf();
                return START_NOT_STICKY;
            }
            startRecording();
        } else if (ACTION_STOP.equals(action)) {
            stopRequested = true;
        } else if (!recording) {
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    // The microphone type constant is API 30, but ServiceCompat drops it safely on API 29.
    @SuppressLint("InlinedApi")
    private boolean goForeground() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL,
                    getString(R.string.channel_recording), NotificationManager.IMPORTANCE_LOW));
        }
        PendingIntent stop = PendingIntent.getService(this, 1,
                new Intent(this, RecorderService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent open = PendingIntent.getActivity(this, 2,
                new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new NotificationCompat.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_mic)
                .setContentTitle(getString(R.string.notification_recording))
                .setContentIntent(open)
                .setOngoing(true)
                .setUsesChronometer(true)
                .addAction(R.drawable.ic_stop, getString(R.string.action_stop), stop)
                .build();
        try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, n,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
            return true;
        } catch (RuntimeException e) {
            // Android refuses a microphone service started from the background.
            // The widget avoids this by starting from a (briefly visible) activity.
            new Prefs(this).addHistory(getString(R.string.history_error, Jar.localTime(), e.getClass().getSimpleName()));
            return false;
        }
    }

    private void startRecording() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            finishWithError("no microphone permission");
            return;
        }
        int minBuf = AudioRecord.getMinBufferSize(Wav.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec = new AudioRecord(MediaRecorder.AudioSource.MIC, Wav.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(minBuf, 8192) * 2);
        if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
            rec.release();
            finishWithError("microphone busy");
            return;
        }

        MemoQueue queue = Jar.queue(this);
        String id = MemoQueue.newId();
        String recordedAt = Jar.isoUtcNow();
        stopRequested = false;
        recording = true;
        startedAt = SystemClock.elapsedRealtime();
        Jar.buzz(this, 1, 40);
        Jar.notifyState(this);

        worker = new Thread(() -> {
            boolean ok = true;
            try (OutputStream out = new FileOutputStream(queue.partFile(id))) {
                out.write(Wav.header(0));              // patched with real sizes in finish()
                short[] samples = new short[1024];
                byte[] bytes = new byte[2048];
                rec.startRecording();
                while (!stopRequested && SystemClock.elapsedRealtime() - startedAt < MAX_MS) {
                    int n = rec.read(samples, 0, samples.length);
                    if (n <= 0) continue;
                    for (int i = 0; i < n; i++) {         // WAV is little-endian
                        bytes[2 * i] = (byte) samples[i];
                        bytes[2 * i + 1] = (byte) (samples[i] >> 8);
                    }
                    out.write(bytes, 0, 2 * n);
                }
            } catch (IOException | IllegalStateException e) {
                ok = false;
            } finally {
                try {
                    rec.stop();
                } catch (IllegalStateException ignored) {
                    // Never started: nothing to stop.
                }
                rec.release();
            }
            long durationMs = SystemClock.elapsedRealtime() - startedAt;
            boolean finalOk = ok;
            main.post(() -> saved(queue, id, recordedAt, durationMs, finalOk));
        }, "jar-recorder");
        worker.start();
    }

    private void saved(MemoQueue queue, String id, String recordedAt, long durationMs, boolean ok) {
        Prefs prefs = new Prefs(this);
        recording = false;
        if (durationMs < MIN_MS) {
            queue.discard(id);
            Jar.buzz(this, 1, 250);
            prefs.addHistory(getString(R.string.history_too_short, Jar.localTime()));
        } else {
            boolean kept;
            try {
                kept = queue.finish(id, recordedAt);
            } catch (IOException e) {
                kept = false;
            }
            if (kept) {
                Jar.buzz(this, 2, 60);
                prefs.addHistory(getString(ok ? R.string.history_saved : R.string.history_saved_partial,
                        Jar.localTime(), Jar.seconds(durationMs)));
                UploadWorker.enqueue(this);
            } else {
                Jar.buzz(this, 3, 200);
                prefs.addHistory(getString(R.string.history_error, Jar.localTime(), "save failed"));
            }
        }
        Jar.notifyState(this);
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void finishWithError(String why) {
        Jar.buzz(this, 3, 200);
        new Prefs(this).addHistory(getString(R.string.history_error, Jar.localTime(), why));
        Jar.notifyState(this);
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    @Override
    public void onDestroy() {
        // If Android kills us mid-memo, the .wav.part is recovered next time the app opens.
        stopRequested = true;
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
