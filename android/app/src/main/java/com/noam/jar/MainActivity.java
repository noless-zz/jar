package com.noam.jar;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.MotionEvent;
import android.widget.Button;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;

import com.google.android.material.button.MaterialButton;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import com.noam.jar.core.PairingLink;
import com.noam.jar.core.ServerList;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.textfield.TextInputEditText;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The companion's only screen: a big hold-to-talk button (like the pendant),
 * the upload queue, server settings, and a log of what happened.
 */
public final class MainActivity extends AppCompatActivity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    private Prefs prefs;
    private MaterialButton recordButton;
    private TextView recordStatus, queueText, historyText, testResult, pairInfo, tailscaleStatus;
    private MaterialButton tailscaleButton;
    private TextInputEditText urlField, tokenField, deviceField;
    private MaterialSwitch offlineSwitch;

    private final ActivityResultLauncher<String[]> permissions = registerForActivityResult(
            new ActivityResultContracts.RequestMultiplePermissions(), granted -> refresh());

    /** Refreshes the screen when a recording starts/stops or an upload finishes. */
    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            refresh();
        }
    };

    /** Ticks the "Recording 0:07" timer while a memo is being recorded. */
    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            refresh();
            if (RecorderService.isRecording()) main.postDelayed(this, 250);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        prefs = new Prefs(this);

        recordButton = findViewById(R.id.record_button);
        recordStatus = findViewById(R.id.record_status);
        queueText = findViewById(R.id.queue_text);
        historyText = findViewById(R.id.history_text);
        testResult = findViewById(R.id.test_result);
        urlField = findViewById(R.id.server_url);
        tokenField = findViewById(R.id.token);
        deviceField = findViewById(R.id.device_id);
        offlineSwitch = findViewById(R.id.offline_switch);

        urlField.setText(prefs.serverUrl());
        tokenField.setText(prefs.token());
        deviceField.setText(prefs.deviceId());
        offlineSwitch.setChecked(prefs.offlineSim());

        setUpRecordButton();
        offlineSwitch.setOnCheckedChangeListener((b, on) -> {
            prefs.setOfflineSim(on);
            if (!on) UploadWorker.enqueue(this);   // "Wi-Fi is back": flush the queue
            refresh();
        });
        Button uploadNow = findViewById(R.id.upload_now);
        uploadNow.setOnClickListener(v -> UploadWorker.enqueue(this));
        findViewById(R.id.save_settings).setOnClickListener(v -> saveSettings());
        findViewById(R.id.test_connection).setOnClickListener(v -> testConnection());
        pairInfo = findViewById(R.id.pair_info);
        tailscaleStatus = findViewById(R.id.tailscale_status);
        tailscaleButton = findViewById(R.id.tailscale_button);
        findViewById(R.id.pair_scan).setOnClickListener(v -> scanPairingCode());
        findViewById(R.id.pair_paste).setOnClickListener(v -> pastePairingLink());
        tailscaleButton.setOnClickListener(v -> TailscaleHelper.openOrInstall(this));
        findViewById(R.id.clear_log).setOnClickListener(v -> {
            prefs.clearHistory();
            refresh();
        });

        recoverInterruptedMemos();
        askPermissions();
        handlePairingIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handlePairingIntent(intent);
    }

    // ---------------------------------------------------------------- pairing

    /** Scan the QR code on the PC's dashboard (Jar → Dashboard → "Pair a phone"). */
    private void scanPairingCode() {
        GmsBarcodeScannerOptions options = new GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE).build();
        GmsBarcodeScanning.getClient(this, options).startScan()
                .addOnSuccessListener(code -> applyPairing(code.getRawValue()))
                .addOnFailureListener(e -> testResult.setText(getString(R.string.pair_scan_failed,
                        e.getClass().getSimpleName())));
    }

    /** For the emulator or no camera: copy the link from the pairing page, then tap "Paste link". */
    private void pastePairingLink() {
        ClipboardManager cb = getSystemService(ClipboardManager.class);
        ClipData clip = cb == null ? null : cb.getPrimaryClip();
        CharSequence text = clip != null && clip.getItemCount() > 0 ? clip.getItemAt(0).getText() : null;
        applyPairing(text == null ? null : text.toString());
    }

    /** The link itself, opened from a message or a browser: jar://pair?... */
    private void handlePairingIntent(Intent intent) {
        if (intent != null && Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            applyPairing(intent.getData().toString());
            intent.setData(null);   // don't pair again on rotation
        }
    }

    private void applyPairing(String raw) {
        PairingLink link = PairingLink.parse(raw);
        if (link == null) {
            testResult.setText(R.string.pair_bad);
            return;
        }
        if (!link.token.equals(prefs.token())) new TaskCache(this).clearAll();   // someone else's phone now
        prefs.setToken(link.token);
        prefs.setServerUrls(link.urls);
        tokenField.setText(link.token);
        urlField.setText(prefs.serverUrl());
        prefs.addHistory(getResources().getQuantityString(R.plurals.history_paired, link.urls.size(),
                Jar.localTime(), link.urls.size()));
        refresh();
        testConnection(false);   // find the address that works right now
    }

    /**
     * Press and hold records; release saves — same gesture as the pendant.
     * A plain tap (or a screen reader's double-tap) toggles instead, so the
     * button also works without holding.
     */
    @SuppressLint("ClickableViewAccessibility")
    private void setUpRecordButton() {
        final long[] downAt = {0};
        recordButton.setOnTouchListener((v, e) -> {
            if (!hasMic()) {
                if (e.getAction() == MotionEvent.ACTION_UP) askPermissions();
                return true;
            }
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downAt[0] = e.getEventTime();
                    if (!RecorderService.isRecording()) startRecording();
                    else RecorderService.send(this, RecorderService.ACTION_STOP);   // tap-mode stop
                    return true;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    // Held longer than a tap: it was push-to-talk, so release stops it.
                    if (e.getEventTime() - downAt[0] > 400 && RecorderService.isRecording()) {
                        RecorderService.send(this, RecorderService.ACTION_STOP);
                    }
                    if (e.getActionMasked() == MotionEvent.ACTION_UP) v.performClick();
                    return true;
                default:
                    return true;
            }
        });
        // The touch listener does the work (a tap starts, the next tap stops);
        // performClick() above just lets screen readers announce the press.
        recordButton.setOnClickListener(v -> { });
    }

    private void startRecording() {
        RecorderService.send(this, RecorderService.ACTION_START);
        main.removeCallbacks(ticker);
        main.postDelayed(ticker, 150);
    }

    private void saveSettings() {
        prefs.setServerUrl(text(urlField));
        if (!text(tokenField).equals(prefs.token())) new TaskCache(this).clearAll();
        prefs.setToken(text(tokenField));
        prefs.setDeviceId(text(deviceField).isEmpty() ? "phone-01" : text(deviceField));
        urlField.setText(prefs.serverUrl());
        testResult.setText(R.string.settings_saved);
        refresh();
        UploadWorker.enqueue(this);
    }

    private void testConnection() {
        testConnection(true);
    }

    private void testConnection(boolean saveFirst) {
        if (saveFirst) saveSettings();
        testResult.setText(R.string.testing);
        io.execute(() -> {
            Uploader.Check c = Uploader.testConnection(prefs);
            main.post(() -> {
                if (c.problem == null) {
                    testResult.setText(getString(ServerList.isTailscale(c.url)
                            ? R.string.test_ok_tailscale : R.string.test_ok_home, hostOf(c.url)));
                    urlField.setText(prefs.serverUrl());
                    UploadWorker.enqueue(this);   // anything waiting can go now
                    TaskSync.now(this);           // and fetch who this phone belongs to + the tasks
                } else if (Uploader.BAD_TOKEN.equals(c.problem)) {
                    testResult.setText(R.string.test_bad_token);
                } else if (c.url != null) {
                    testResult.setText(getString(R.string.test_failed, c.problem));
                } else {
                    testResult.setText(getString(R.string.test_unreachable, prefs.serverUrls().size(), c.problem));
                }
                refresh();
            });
        });
    }

    private static String hostOf(String url) {
        return url.replaceFirst("^https?://", "");
    }

    /** A memo cut off by a crash or a killed app is kept, as the pendant does after power loss. */
    private void recoverInterruptedMemos() {
        if (RecorderService.isRecording()) return;
        io.execute(() -> {
            try {
                int n = Jar.queue(this).recoverPartials(Jar.isoUtcNow());
                if (n > 0) {
                    prefs.addHistory(getResources().getQuantityString(R.plurals.history_recovered, n, Jar.localTime(), n));
                    UploadWorker.enqueue(this);
                    main.post(this::refresh);
                }
            } catch (IOException ignored) {
                // Leave the part file; we'll try again next time.
            }
        });
    }

    private void askPermissions() {
        List<String> needed = new ArrayList<>();
        if (!hasMic()) needed.add(Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (!needed.isEmpty()) permissions.launch(needed.toArray(new String[0]));
    }

    private boolean hasMic() {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void refresh() {
        boolean rec = RecorderService.isRecording();
        recordButton.setText(rec ? R.string.release_to_save : R.string.hold_to_record);
        recordButton.setIconResource(rec ? R.drawable.ic_stop : R.drawable.ic_mic);
        recordButton.setBackgroundTintList(ContextCompat.getColorStateList(this,
                rec ? R.color.recording : R.color.accent));
        if (!hasMic()) {
            recordStatus.setText(R.string.need_mic_permission);
        } else if (rec) {
            long s = RecorderService.elapsedMs() / 1000;
            recordStatus.setText(getString(R.string.recording_time,
                    String.format(Locale.getDefault(), "%d:%02d", s / 60, s % 60)));
        } else {
            recordStatus.setText(R.string.ready);
        }

        int queued = Jar.queue(this).readyCount();
        String q = queued == 0 ? getString(R.string.queue_empty)
                : getResources().getQuantityString(R.plurals.queued_count, queued, queued);
        if (prefs.offlineSim() && queued > 0) q = q + " · " + getString(R.string.offline_on);
        queueText.setText(q);

        int n = prefs.serverUrls().size();
        pairInfo.setText(n > 1
                ? getResources().getQuantityString(R.plurals.pair_info_paired, n, n)
                : getString(R.string.pair_info_single));

        switch (TailscaleHelper.state(this)) {
            case CONNECTED:
                tailscaleStatus.setText(R.string.ts_connected);
                tailscaleButton.setText(R.string.ts_open);
                break;
            case INSTALLED_OFF:
                tailscaleStatus.setText(R.string.ts_off);
                tailscaleButton.setText(R.string.ts_open);
                break;
            default:
                tailscaleStatus.setText(R.string.ts_not_installed);
                tailscaleButton.setText(R.string.ts_install);
        }

        String h = prefs.history();
        historyText.setText(h.isEmpty() ? getString(R.string.history_empty) : h);
    }

    @Override
    protected void onStart() {
        super.onStart();
        ContextCompat.registerReceiver(this, stateReceiver, new IntentFilter(Jar.ACTION_STATE),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        refresh();
        if (RecorderService.isRecording()) main.post(ticker);
    }

    @Override
    protected void onStop() {
        unregisterReceiver(stateReceiver);
        main.removeCallbacks(ticker);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        io.shutdown();
        super.onDestroy();
    }

    private static String text(TextInputEditText f) {
        return f.getText() == null ? "" : f.getText().toString().trim();
    }
}
