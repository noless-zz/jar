package com.noam.jar;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;

import com.noam.jar.core.MemoQueue;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** Small shared helpers: the queue folder, state broadcasts, haptics, timestamps. */
public final class Jar {
    /** Sent (inside this app only) whenever recording or the queue changes. */
    public static final String ACTION_STATE = "com.noam.jar.STATE";

    private Jar() {}

    public static MemoQueue queue(Context c) {
        return new MemoQueue(new File(c.getFilesDir(), "memos"));
    }

    /** Tell the open screen and the home-screen widgets to refresh. */
    public static void notifyState(Context c) {
        c.sendBroadcast(new Intent(ACTION_STATE).setPackage(c.getPackageName()));
        JarWidget.updateAll(c);
    }

    public static String isoUtcNow() {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date());
    }

    public static String localTime() {
        return new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date());
    }

    public static String seconds(long ms) {
        return String.format(Locale.getDefault(), "%.1f", ms / 1000.0);
    }

    /**
     * The same buzz patterns as the pendant, so the phone "feels" like the device:
     * 1 short = started, 2 short = saved, 1 long = too short, 3 long = error.
     */
    public static void buzz(Context c, int pulses, int onMs) {
        Vibrator v;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            VibratorManager vm = c.getSystemService(VibratorManager.class);
            v = vm == null ? null : vm.getDefaultVibrator();
        } else {
            v = c.getSystemService(Vibrator.class);
        }
        if (v == null || !v.hasVibrator()) return;
        long[] pattern = new long[pulses * 2];
        for (int i = 0; i < pulses; i++) {
            pattern[2 * i] = i == 0 ? 0 : 90;
            pattern[2 * i + 1] = onMs;
        }
        v.vibrate(VibrationEffect.createWaveform(pattern, -1));
    }
}
