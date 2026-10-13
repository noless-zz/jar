package com.noam.jar;

import android.Manifest;
import android.app.AlarmManager;
import android.appwidget.AppWidgetManager;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.View;
import android.widget.HorizontalScrollView;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.tabs.TabLayout;
import com.google.android.material.textfield.TextInputEditText;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import com.noam.jar.core.PairingLink;
import com.noam.jar.core.ServerList;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Settings, in pages: Connection (pairing, test, addresses), Memos (queue, log),
 * PC (the admin looks after the PC: status, update from GitHub, restart, logs) and App
 * (version, permission checks, widgets). Recording lives on the task screen and the widgets.
 */
public final class MainActivity extends AppCompatActivity {
    private static final String PAGE = "settings_page";

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    private Prefs prefs;
    private TaskCache cache;
    private TabLayout tabs;
    private View[] pages;
    private TextView queueText, historyText, testResult, pairInfo, addressList, tailscaleStatus, pcStatus;
    private TextView appVersion, checkNotifications, checkMic, checkAlarms, checkBattery;
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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        prefs = new Prefs(this);
        cache = new TaskCache(this);

        MaterialToolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setNavigationOnClickListener(v -> finish());

        queueText = findViewById(R.id.queue_text);
        historyText = findViewById(R.id.history_text);
        testResult = findViewById(R.id.test_result);
        pairInfo = findViewById(R.id.pair_info);
        addressList = findViewById(R.id.address_list);
        tailscaleStatus = findViewById(R.id.tailscale_status);
        pcStatus = findViewById(R.id.pc_status);
        appVersion = findViewById(R.id.app_version);
        checkNotifications = findViewById(R.id.check_notifications);
        checkMic = findViewById(R.id.check_mic);
        checkAlarms = findViewById(R.id.check_alarms);
        checkBattery = findViewById(R.id.check_battery);
        urlField = findViewById(R.id.server_url);
        tokenField = findViewById(R.id.token);
        deviceField = findViewById(R.id.device_id);
        offlineSwitch = findViewById(R.id.offline_switch);

        urlField.setText(prefs.serverUrl());
        tokenField.setText(prefs.token());
        deviceField.setText(prefs.deviceId());
        offlineSwitch.setChecked(prefs.offlineSim());

        setUpTabs();
        setUpConnection();
        setUpMemos();
        setUpPc();
        setUpApp();

        recoverInterruptedMemos();
        askPermissions();
        handlePairingIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handlePairingIntent(intent);
    }

    // ---------------------------------------------------------------- pages

    private void setUpTabs() {
        tabs = findViewById(R.id.settings_tabs);
        pages = new View[] {findViewById(R.id.page_connection), findViewById(R.id.page_memos),
                findViewById(R.id.page_pc), findViewById(R.id.page_app)};
        int[] titles = {R.string.tab_connection, R.string.tab_memos, R.string.tab_pc, R.string.tab_app};
        boolean admin = cache.iAmAdmin();
        for (int i = 0; i < pages.length; i++) {
            if (i == 2 && !admin) continue;
            tabs.addTab(tabs.newTab().setText(titles[i]).setTag(i));
        }
        tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override public void onTabSelected(TabLayout.Tab tab) { show((Integer) tab.getTag()); }
            @Override public void onTabUnselected(TabLayout.Tab tab) { }
            @Override public void onTabReselected(TabLayout.Tab tab) { }
        });
        int want = getSharedPreferences("jar", MODE_PRIVATE).getInt(PAGE, 0);
        for (int i = 0; i < tabs.getTabCount(); i++) {
            TabLayout.Tab t = tabs.getTabAt(i);
            if (t != null && Integer.valueOf(want).equals(t.getTag())) t.select();
        }
        TabLayout.Tab sel = tabs.getTabAt(tabs.getSelectedTabPosition());
        show(sel == null ? 0 : (Integer) sel.getTag());
    }

    private void show(int page) {
        for (int i = 0; i < pages.length; i++) pages[i].setVisibility(i == page ? View.VISIBLE : View.GONE);
        ((ScrollView) findViewById(R.id.settings_scroll)).scrollTo(0, 0);
        getSharedPreferences("jar", MODE_PRIVATE).edit().putInt(PAGE, page).apply();
        if (page == 2) loadPcStatus();
        refresh();
    }

    // ---------------------------------------------------------------- connection

    private void setUpConnection() {
        findViewById(R.id.test_connection).setOnClickListener(v -> testConnection(false));
        findViewById(R.id.save_settings).setOnClickListener(v -> {
            saveSettings();
            testConnection(false);
        });
        findViewById(R.id.pair_scan).setOnClickListener(v -> scanPairingCode());
        findViewById(R.id.pair_paste).setOnClickListener(v -> pastePairingLink());
        findViewById(R.id.tailscale_button).setOnClickListener(v -> TailscaleHelper.openOrInstall(this));
        MaterialSwitch adv = findViewById(R.id.advanced_switch);
        adv.setOnCheckedChangeListener((b, on) ->
                findViewById(R.id.advanced_box).setVisibility(on ? View.VISIBLE : View.GONE));
    }

    /** Scan the QR code on the PC's dashboard (Jar → Dashboard → "Pair a phone"). */
    private void scanPairingCode() {
        GmsBarcodeScannerOptions options = new GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE).build();
        GmsBarcodeScanning.getClient(this, options).startScan()
                .addOnSuccessListener(code -> applyPairing(code.getRawValue()))
                .addOnFailureListener(e -> testResult.setText(getString(R.string.pair_scan_failed,
                        e.getClass().getSimpleName())));
    }

    /** Copy the link from a message or the pairing page, then tap "Paste link". */
    private void pastePairingLink() {
        ClipboardManager cb = getSystemService(ClipboardManager.class);
        ClipData clip = cb == null ? null : cb.getPrimaryClip();
        CharSequence text = clip != null && clip.getItemCount() > 0 ? clip.getItemAt(0).getText() : null;
        applyPairing(text == null ? null : text.toString());
    }

    /** The link itself, opened from a message, a browser or the join page: jar://pair?... */
    private void handlePairingIntent(Intent intent) {
        if (intent != null && Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            applyPairing(intent.getData().toString());
            intent.setData(null);   // don't pair again on rotation
        }
    }

    private void applyPairing(String raw) {
        selectPage(0);
        PairingLink link = PairingLink.parse(raw);
        if (link == null) {
            testResult.setText(R.string.pair_bad);
            return;
        }
        if (!link.token.equals(prefs.token())) cache.clearAll();   // someone else's phone now
        prefs.setToken(link.token);
        prefs.setServerUrls(link.urls);
        tokenField.setText(link.token);
        urlField.setText(prefs.serverUrl());
        prefs.addHistory(getResources().getQuantityString(R.plurals.history_paired, link.urls.size(),
                Jar.localTime(), link.urls.size()));
        refresh();
        testConnection(false);   // find the address that works right now
    }

    private void selectPage(int page) {
        for (int i = 0; i < tabs.getTabCount(); i++) {
            TabLayout.Tab t = tabs.getTabAt(i);
            if (t != null && Integer.valueOf(page).equals(t.getTag())) t.select();
        }
    }

    private void saveSettings() {
        prefs.setServerUrl(text(urlField));
        if (!text(tokenField).equals(prefs.token())) cache.clearAll();
        prefs.setToken(text(tokenField));
        prefs.setDeviceId(text(deviceField).isEmpty() ? "phone-01" : text(deviceField));
        urlField.setText(prefs.serverUrl());
        testResult.setText(R.string.settings_saved);
        refresh();
        UploadWorker.enqueue(this);
    }

    private void testConnection(boolean saveFirst) {
        if (saveFirst) saveSettings();
        testResult.setText(R.string.testing);
        io.execute(() -> {
            Uploader.Check c = Uploader.testConnection(prefs);
            main.post(() -> {
                if (c.problem == null) {
                    testResult.setText(getString(ServerList.isPublic(c.url) ? R.string.test_ok_public
                            : ServerList.isTailscale(c.url) ? R.string.test_ok_tailscale
                            : R.string.test_ok_home, hostOf(c.url)));
                    urlField.setText(prefs.serverUrl());
                    UploadWorker.now(this);       // anything waiting can go now
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

    // ---------------------------------------------------------------- memos

    private void setUpMemos() {
        offlineSwitch.setOnCheckedChangeListener((b, on) -> {
            prefs.setOfflineSim(on);
            if (!on) UploadWorker.now(this);       // "Wi-Fi is back": flush the queue
            refresh();
        });
        findViewById(R.id.upload_now).setOnClickListener(v -> UploadWorker.now(this));
        findViewById(R.id.open_memos).setOnClickListener(v -> startActivity(new Intent(this, MemosActivity.class)));
        findViewById(R.id.clear_log).setOnClickListener(v -> {
            prefs.clearHistory();
            refresh();
        });
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

    // ---------------------------------------------------------------- PC (admin)

    private void setUpPc() {
        findViewById(R.id.pc_refresh).setOnClickListener(v -> loadPcStatus());
        findViewById(R.id.pc_update).setOnClickListener(v -> pcCommand("update", R.string.pc_update_confirm));
        findViewById(R.id.pc_restart).setOnClickListener(v -> pcCommand("restart", R.string.pc_restart_confirm));
        findViewById(R.id.pc_eval).setOnClickListener(v -> pcCommand("eval", R.string.pc_eval_confirm));
        findViewById(R.id.log_worker).setOnClickListener(v -> showLog("worker"));
        findViewById(R.id.log_server).setOnClickListener(v -> showLog("server"));
        findViewById(R.id.log_supervisor).setOnClickListener(v -> showLog("supervisor"));
        findViewById(R.id.log_eval).setOnClickListener(v -> showLog("eval"));
        findViewById(R.id.pc_dashboard).setOnClickListener(v -> io.execute(() -> {
            try {
                String url = TaskApi.dashboardLink(prefs);
                main.post(() -> startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))));
            } catch (IOException e) {
                toast(getString(R.string.dashboard_failed, e.getMessage()));
            }
        }));
        findViewById(R.id.pc_invite).setOnClickListener(v -> startActivity(new Intent(this, TasksActivity.class)
                .putExtra(TasksActivity.EXTRA_INVITE, true)));
    }

    private void loadPcStatus() {
        pcStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                JSONObject s = TaskApi.adminStatus(prefs);
                String text = describePc(s);
                main.post(() -> pcStatus.setText(text));
            } catch (IOException e) {
                main.post(() -> pcStatus.setText(getString(R.string.pc_unreachable, e.getMessage())));
            }
        });
    }

    private String describePc(JSONObject s) {
        StringBuilder b = new StringBuilder();
        JSONObject sup = s.optJSONObject("supervisor");
        JSONObject work = s.optJSONObject("worker");
        if (sup != null) {
            b.append(getString(sup.optBoolean("alive") ? R.string.pc_sup_alive : R.string.pc_sup_dead)).append('\n');
            String code = sup.optString("code");
            b.append(getString(R.string.pc_code, code.isEmpty() || "null".equals(code) ? "?" : code,
                    "git".equals(sup.optString("update_mode")) ? "git" : "zip")).append('\n');
            b.append(getString(R.string.pc_github, sup.optString("update", "?"))).append('\n');
            if (!sup.isNull("last_command") && !sup.optString("last_command").isEmpty()) {
                b.append(getString(R.string.pc_last_command, sup.optString("last_command"))).append('\n');
            }
        }
        if (work != null) {
            b.append(getString(work.optBoolean("alive") ? R.string.pc_worker_alive : R.string.pc_worker_dead,
                    work.optString("doing", "?"))).append('\n');
            b.append(getString(R.string.pc_models, work.optString("llm", "?"), work.optString("whisper", "?")))
                    .append('\n');
        }
        JSONObject memos = s.optJSONObject("memos");
        if (memos != null && memos.length() > 0) {
            List<String> parts = new ArrayList<>();
            for (Iterator<String> it = memos.keys(); it.hasNext(); ) {
                String k = it.next();
                parts.add(k + " " + memos.optInt(k));
            }
            b.append(getString(R.string.pc_memos, String.join(" · ", parts))).append('\n');
        }
        JSONObject ev = s.optJSONObject("eval");
        if (s.optBoolean("eval_running")) {
            b.append(getString(R.string.pc_eval_running)).append('\n');
        } else if (ev != null) {
            b.append(getString(R.string.pc_eval_last, ev.optInt("passed"), ev.optInt("total"), ev.optString("at")))
                    .append('\n');
        }
        JSONArray rej = s.optJSONArray("rejected");
        if (rej != null && rej.length() > 0) {
            b.append(getString(R.string.pc_rejected, rej.length())).append('\n');
        }
        return b.toString().trim();
    }

    private void pcCommand(String cmd, int confirm) {
        new MaterialAlertDialogBuilder(this)
                .setMessage(confirm)
                .setPositiveButton(android.R.string.ok, (d, w) -> io.execute(() -> {
                    try {
                        JSONObject r = TaskApi.adminCommand(prefs, cmd);
                        toast(r.optString("message", "ok"));
                        main.postDelayed(this::loadPcStatus, "restart".equals(cmd) ? 20000 : 6000);
                    } catch (IOException e) {
                        toast(getString(R.string.pc_unreachable, e.getMessage()));
                    }
                }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void showLog(String name) {
        io.execute(() -> {
            try {
                String text = TaskApi.adminLog(prefs, name).optString("text");
                main.post(() -> {
                    TextView tv = new TextView(this);
                    tv.setText(text);
                    tv.setTypeface(Typeface.MONOSPACE);
                    tv.setTextSize(11);
                    tv.setTextIsSelectable(true);
                    tv.setTextDirection(View.TEXT_DIRECTION_LTR);
                    int pad = (int) (12 * getResources().getDisplayMetrics().density);
                    tv.setPadding(pad, pad, pad, pad);
                    HorizontalScrollView h = new HorizontalScrollView(this);
                    h.addView(tv);
                    ScrollView sv = new ScrollView(this);
                    sv.addView(h);
                    sv.post(() -> sv.fullScroll(View.FOCUS_DOWN));     // newest lines at the bottom
                    new MaterialAlertDialogBuilder(this)
                            .setTitle(name)
                            .setView(sv)
                            .setPositiveButton(android.R.string.ok, null)
                            .setNeutralButton(R.string.copy, (d, w) -> {
                                ClipboardManager cb = getSystemService(ClipboardManager.class);
                                if (cb != null) cb.setPrimaryClip(ClipData.newPlainText(name, text));
                            })
                            .show();
                });
            } catch (IOException e) {
                toast(getString(R.string.pc_unreachable, e.getMessage()));
            }
        });
    }

    // ---------------------------------------------------------------- app

    private void setUpApp() {
        String ver = getString(R.string.app_version, BuildConfig.VERSION_NAME, BuildConfig.DEBUG ? "dev" : "release");
        String news = Updater.availableTag(this) == null ? "" : Updater.whatsNew(this);
        appVersion.setText(news.isEmpty() ? ver : ver + "\n" + getString(R.string.update_whats_new, news));
        findViewById(R.id.app_check_update).setOnClickListener(v -> checkForUpdate());
        findViewById(R.id.app_share).setOnClickListener(v -> {
            Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, getString(R.string.share_app_text, TasksActivity.downloadPage()));
            startActivity(Intent.createChooser(send, getString(R.string.share_app)));
        });
        checkNotifications.setOnClickListener(v -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !notificationsOn()) {
                permissions.launch(new String[] {Manifest.permission.POST_NOTIFICATIONS});
            }
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        });
        checkMic.setOnClickListener(v -> askPermissions());
        checkAlarms.setOnClickListener(v -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                startActivity(new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                        Uri.parse("package:" + getPackageName())));
            }
        });
        checkBattery.setOnClickListener(v -> askBattery());
        findViewById(R.id.add_mic_widget).setOnClickListener(v -> pinWidget(JarWidget.class));
        findViewById(R.id.add_tasks_widget).setOnClickListener(v -> pinWidget(TasksWidget.class));
    }

    private void checkForUpdate() {
        if (!Updater.enabled()) {
            toast(getString(R.string.update_dev_build, BuildConfig.VERSION_NAME));
            return;
        }
        io.execute(() -> {
            try {
                if (Updater.check(this, true)) {
                    // The task screen shows the "Update to …" bar with the install button.
                    main.post(() -> {
                        startActivity(new Intent(this, TasksActivity.class)
                                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                        finish();
                    });
                } else {
                    toast(getString(R.string.update_none, BuildConfig.VERSION_NAME));
                }
            } catch (IOException e) {
                toast(getString(R.string.update_check_failed, e.getMessage()));
            }
        });
    }

    /** Asks the launcher to put the widget on the home screen (Android 8+, most launchers). */
    private void pinWidget(Class<?> provider) {
        AppWidgetManager m = getSystemService(AppWidgetManager.class);
        if (m != null && m.isRequestPinAppWidgetSupported()) {
            m.requestPinAppWidget(new ComponentName(this, provider), null, null);
        } else {
            toast(getString(R.string.widgets_manual));
        }
    }

    @android.annotation.SuppressLint("BatteryLife")
    private void askBattery() {
        PowerManager pm = getSystemService(PowerManager.class);
        if (pm != null && pm.isIgnoringBatteryOptimizations(getPackageName())) {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        } else {
            startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:" + getPackageName())));
        }
    }

    private boolean notificationsOn() {
        return NotificationManagerCompat.from(this).areNotificationsEnabled();
    }

    private boolean exactAlarmsOn() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true;
        AlarmManager am = getSystemService(AlarmManager.class);
        return am == null || am.canScheduleExactAlarms();
    }

    private boolean batteryFree() {
        PowerManager pm = getSystemService(PowerManager.class);
        return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private void check(TextView v, boolean ok, int okText, int fixText) {
        v.setText((ok ? "✓  " : "⚠  ") + getString(ok ? okText : fixText));
        v.setClickable(!ok);
        v.setAlpha(ok ? 0.75f : 1f);
    }

    // ---------------------------------------------------------------- common

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
        int queued = Jar.queue(this).readyCount();
        String q = queued == 0 ? getString(R.string.queue_empty)
                : getResources().getQuantityString(R.plurals.queued_count, queued, queued);
        if (prefs.offlineSim() && queued > 0) q = q + " · " + getString(R.string.offline_on);
        queueText.setText(q);

        List<String> urls = prefs.serverUrls();
        int n = urls.size();
        pairInfo.setText(n > 1
                ? getResources().getQuantityString(R.plurals.pair_info_paired, n, n)
                : getString(R.string.pair_info_single));
        StringBuilder a = new StringBuilder();
        String good = prefs.lastGoodUrl();
        for (String u : ServerList.ordered(urls, good)) {
            String kind = ServerList.isPublic(u) ? getString(R.string.addr_public)
                    : ServerList.isTailscale(u) ? "Tailscale" : getString(R.string.addr_home);
            a.append(u.equals(good) ? "✓ " : "• ").append(hostOf(u)).append("  (").append(kind).append(")\n");
        }
        addressList.setText(a.toString().trim());

        TailscaleHelper.State ts = TailscaleHelper.state(this);
        findViewById(R.id.tailscale_row).setVisibility(ts == TailscaleHelper.State.NOT_INSTALLED ? View.GONE : View.VISIBLE);
        tailscaleStatus.setText(ts == TailscaleHelper.State.CONNECTED ? R.string.ts_connected : R.string.ts_off);

        String h = prefs.history();
        historyText.setText(h.isEmpty() ? getString(R.string.history_empty) : h);

        check(checkNotifications, notificationsOn(), R.string.check_notifications_ok, R.string.check_notifications_fix);
        check(checkMic, hasMic(), R.string.check_mic_ok, R.string.check_mic_fix);
        check(checkAlarms, exactAlarmsOn(), R.string.check_alarms_ok, R.string.check_alarms_fix);
        check(checkBattery, batteryFree(), R.string.check_battery_ok, R.string.check_battery_fix);
    }

    private void toast(String msg) {
        main.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }

    @Override
    protected void onStart() {
        super.onStart();
        ContextCompat.registerReceiver(this, stateReceiver, new IntentFilter(Jar.ACTION_STATE),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        refresh();
    }

    @Override
    protected void onStop() {
        unregisterReceiver(stateReceiver);
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
