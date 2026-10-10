package com.noam.jar;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;

import androidx.core.content.ContextCompat;

/**
 * Invisible trampoline for the home-screen widget. Android only lets an app open
 * the microphone from a foreground service if the app is visible when the
 * service starts, so the widget opens this see-through screen for a moment,
 * which starts or stops the recording and closes itself.
 */
public final class RecordActivity extends Activity {

    @Override
    protected void onResume() {
        super.onResume();
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            // First use: the main screen asks for the microphone permission.
            startActivity(new Intent(this, MainActivity.class));
        } else {
            RecorderService.send(this, RecorderService.ACTION_TOGGLE);
        }
        finish();
        overridePendingTransitionCompat();
    }

    @SuppressWarnings("deprecation")
    private void overridePendingTransitionCompat() {
        // No slide animation: the widget tap should feel instant.
        overridePendingTransition(0, 0);
    }
}
