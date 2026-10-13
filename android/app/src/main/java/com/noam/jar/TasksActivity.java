package com.noam.jar;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Paint;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.ItemTouchHelper;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.datepicker.MaterialDatePicker;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.floatingactionbutton.ExtendedFloatingActionButton;
import com.google.android.material.tabs.TabLayout;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.timepicker.MaterialTimePicker;
import com.google.android.material.timepicker.TimeFormat;
import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The family task list: what I have to do, what I asked others for, and (parents) the kids'.
 * Tick or swipe to finish, tap for snooze and more. The mic button records a memo, like the widget.
 */
public final class TasksActivity extends AppCompatActivity {
    private static final int TAB_MINE = 0, TAB_ASKED = 1, TAB_FAMILY = 2;
    /** From a notification: open this WhatsApp draft right away. */
    static final String EXTRA_SEND = "send_message";
    static final String EXTRA_INVITE = "invite";
    static final String EXTRA_OPEN = "open_task";       // from the tasks widget: show that task's actions

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private Prefs prefs;
    private TaskCache cache;
    private TabLayout tabs;
    private TextView syncStatus, emptyText;
    private View empty, emptyButton;
    private ExtendedFloatingActionButton recordFab, addFab;
    private MaterialToolbar toolbar;
    private final Adapter adapter = new Adapter();
    private View updateBar;
    private TextView updateText;
    private java.io.File pendingApk;     // downloaded update waiting for "allow installs from Jar"

    private final ActivityResultLauncher<String[]> permissions = registerForActivityResult(
            new ActivityResultContracts.RequestMultiplePermissions(), granted -> refresh());

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            refresh();
        }
    };

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            refreshRecord();
            if (RecorderService.isRecording()) main.postDelayed(this, 300);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_tasks);
        prefs = new Prefs(this);
        cache = new TaskCache(this);
        TaskNotify.channels(this);

        toolbar = findViewById(R.id.toolbar);
        tabs = findViewById(R.id.tabs);
        syncStatus = findViewById(R.id.sync_status);
        empty = findViewById(R.id.empty);
        emptyText = findViewById(R.id.empty_text);
        emptyButton = findViewById(R.id.empty_button);
        recordFab = findViewById(R.id.record_fab);
        updateBar = findViewById(R.id.update_bar);
        updateText = findViewById(R.id.update_text);
        findViewById(R.id.update_button).setOnClickListener(v -> installUpdate());
        addFab = findViewById(R.id.add_fab);

        RecyclerView list = findViewById(R.id.list);
        list.setLayoutManager(new LinearLayoutManager(this));
        list.setAdapter(adapter);
        new ItemTouchHelper(new SwipeToDone()).attachToRecyclerView(list);

        tabs.addTab(tabs.newTab().setText(R.string.tab_mine));
        tabs.addTab(tabs.newTab().setText(R.string.tab_asked));
        tabs.addTab(tabs.newTab().setText(R.string.tab_family));
        tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override public void onTabSelected(TabLayout.Tab tab) { refresh(); }
            @Override public void onTabUnselected(TabLayout.Tab tab) { }
            @Override public void onTabReselected(TabLayout.Tab tab) { }
        });

        toolbar.setOnMenuItemClickListener(item -> {
            int id = item.getItemId();
            if (id == R.id.menu_refresh) {
                syncStatus.setText(R.string.syncing);
                TaskSync.now(this);
            } else if (id == R.id.menu_dashboard) {
                openDashboard();
            } else if (id == R.id.menu_update) {
                checkForUpdate(true);
            } else if (id == R.id.menu_memos) {
                startActivity(new Intent(this, MemosActivity.class));
            } else if (id == R.id.menu_invite) {
                chooseInvite();
            } else if (id == R.id.menu_share_app) {
                shareAppLink();
            } else if (id == R.id.menu_settings) {
                startActivity(new Intent(this, MainActivity.class));
            }
            return true;
        });
        emptyButton.setOnClickListener(v -> startActivity(new Intent(this, MainActivity.class)));
        addFab.setOnClickListener(v -> showAddDialog());
        recordFab.setOnClickListener(v -> toggleRecording());

        TaskSync.schedule(this);
        askPermissions();
        handleSend(getIntent());
    }

    @Override
    protected void onStart() {
        super.onStart();
        ContextCompat.registerReceiver(this, stateReceiver, new IntentFilter(Jar.ACTION_STATE),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        refresh();
        if (!prefs.token().isEmpty()) TaskSync.now(this);
        checkForUpdate(false);
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

    // ---------------------------------------------------------------- screen

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleSend(intent);
    }

    private void handleSend(Intent intent) {
        if (intent != null && intent.getBooleanExtra(EXTRA_INVITE, false)) {
            intent.removeExtra(EXTRA_INVITE);
            chooseInvite();
        }
        String open = intent == null ? null : intent.getStringExtra(EXTRA_OPEN);
        if (open != null) {
            intent.removeExtra(EXTRA_OPEN);
            Task ot = cache.find(open);
            if (ot != null) showTaskMenu(ot);
        }
        String id = intent == null ? null : intent.getStringExtra(EXTRA_SEND);
        if (id == null) return;
        intent.removeExtra(EXTRA_SEND);
        Task t = cache.find(id);
        if (t != null && t.isMessage()) sendWhatsApp(t);
    }

    /** WhatsApp opens with the text (and the chat, if the number is known); the person presses Send. */
    private void sendWhatsApp(Task t) {
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(t.whatsappUrl()));
        for (String pkg : new String[] {"com.whatsapp", "com.whatsapp.w4b"}) {
            try {
                getPackageManager().getPackageInfo(pkg, 0);
                i.setPackage(pkg);
                break;
            } catch (android.content.pm.PackageManager.NameNotFoundException ignored) {
                // try the next one; without WhatsApp the link opens in the browser
            }
        }
        try {
            startActivity(i);
            act(t, "done", null);          // ticked as sent; "Not done yet" brings it back
        } catch (android.content.ActivityNotFoundException e) {
            Toast.makeText(this, R.string.whatsapp_missing, Toast.LENGTH_LONG).show();
        }
    }

    private void copyMessage(Task t) {
        android.content.ClipboardManager cb = getSystemService(android.content.ClipboardManager.class);
        if (cb != null) cb.setPrimaryClip(android.content.ClipData.newPlainText("Jar", t.message));
        Toast.makeText(this, R.string.message_copied, Toast.LENGTH_SHORT).show();
    }

    private void editMessage(Task t) {
        com.google.android.material.textfield.TextInputLayout layout =
                new com.google.android.material.textfield.TextInputLayout(this);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad / 2, pad, 0);
        TextInputEditText text = new TextInputEditText(layout.getContext());
        text.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        text.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        text.setMinLines(3);
        text.setText(t.message);
        layout.addView(text);
        new MaterialAlertDialogBuilder(this)
                .setTitle(t.title)
                .setView(layout)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.add_save, (d, w) -> {
                    String m = text.getText() == null ? "" : text.getText().toString().trim();
                    if (m.isEmpty()) return;
                    io.execute(() -> {
                        try {
                            TaskApi.editMessage(prefs, t.id, m);
                            main.post(() -> TaskSync.now(this));
                        } catch (IOException e) {
                            main.post(() -> Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()),
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Back from "allow installs from this source": carry on with the update.
        if (pendingApk != null && getPackageManager().canRequestPackageInstalls()) {
            java.io.File apk = pendingApk;
            pendingApk = null;
            Updater.install(this, apk);
        }
    }

    // ---------------------------------------------------------------- updates

    private void checkForUpdate(boolean force) {
        if (!Updater.enabled()) {
            if (force) Toast.makeText(this, getString(R.string.update_dev_build, BuildConfig.VERSION_NAME),
                    Toast.LENGTH_LONG).show();
            return;
        }
        io.execute(() -> {
            String msg;
            try {
                boolean newer = Updater.check(this, force);
                msg = newer ? null : getString(R.string.update_none, BuildConfig.VERSION_NAME);
            } catch (IOException e) {
                msg = getString(R.string.update_check_failed, e.getMessage());
            }
            String m = msg;
            main.post(() -> {
                refreshUpdate();
                if (!force || m == null) return;
                new MaterialAlertDialogBuilder(this)
                        .setTitle(R.string.menu_update)
                        .setMessage(m)
                        .setPositiveButton(R.string.update_open_page, (d, w) -> openDownloadPage())
                        .setNeutralButton(R.string.share_app, (d, w) -> shareAppLink())
                        .setNegativeButton(android.R.string.ok, null)
                        .show();
            });
        });
    }

    static String downloadPage() {
        return "https://github.com/" + BuildConfig.UPDATE_REPO + "/releases/latest";
    }

    private void openDownloadPage() {
        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(downloadPage())));
    }

    /** The admin picks a family member; the PC writes their personal "install and join" message. */
    private void chooseInvite() {
        java.util.List<String> ids = new java.util.ArrayList<>();
        java.util.List<String> labels = new java.util.ArrayList<>();
        for (java.util.Map.Entry<String, String> e : cache.names().entrySet()) {
            if (e.getKey().equals(cache.myId())) continue;
            ids.add(e.getKey());
            labels.add(e.getValue());
        }
        if (ids.isEmpty()) {
            Toast.makeText(this, R.string.invite_nobody, Toast.LENGTH_LONG).show();
            return;
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.menu_invite)
                .setItems(labels.toArray(new String[0]), (d, which) -> invite(ids.get(which)))
                .show();
    }

    private void invite(String personId) {
        Toast.makeText(this, R.string.invite_preparing, Toast.LENGTH_SHORT).show();
        io.execute(() -> {
            try {
                org.json.JSONObject r = TaskApi.invite(prefs, personId);
                Task t = new Task();
                t.message = r.optString("text");
                t.phone = r.optString("phone");
                main.post(() -> {
                    Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(t.whatsappUrl()));
                    for (String pkg : new String[] {"com.whatsapp", "com.whatsapp.w4b"}) {
                        try {
                            getPackageManager().getPackageInfo(pkg, 0);
                            i.setPackage(pkg);
                            break;
                        } catch (android.content.pm.PackageManager.NameNotFoundException ignored) {
                            // next one
                        }
                    }
                    try {
                        startActivity(i);
                    } catch (android.content.ActivityNotFoundException e) {
                        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain")
                                .putExtra(Intent.EXTRA_TEXT, t.message);
                        startActivity(Intent.createChooser(send, getString(R.string.menu_invite)));
                    }
                });
            } catch (IOException e) {
                main.post(() -> Toast.makeText(this, getString(R.string.invite_failed, e.getMessage()),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    /** WhatsApp & co.: "Get Jar: <link>" so the family can install it themselves. */
    private void shareAppLink() {
        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, getString(R.string.share_app_text, downloadPage()));
        startActivity(Intent.createChooser(send, getString(R.string.share_app)));
    }

    private void refreshUpdate() {
        String tag = Updater.availableTag(this);
        updateBar.setVisibility(tag == null ? View.GONE : View.VISIBLE);
        if (tag != null) updateText.setText(getString(R.string.update_available, tag, BuildConfig.VERSION_NAME));
    }

    private void installUpdate() {
        updateText.setText(R.string.update_downloading);
        io.execute(() -> {
            try {
                java.io.File apk = Updater.download(this);
                main.post(() -> {
                    refreshUpdate();
                    if (!Updater.install(this, apk)) {
                        pendingApk = apk;
                        Toast.makeText(this, R.string.update_allow_installs, Toast.LENGTH_LONG).show();
                    }
                });
            } catch (IOException e) {
                main.post(() -> {
                    refreshUpdate();
                    Toast.makeText(this, getString(R.string.update_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void refresh() {
        refreshRecord();
        refreshUpdate();
        boolean paired = !prefs.token().isEmpty();
        String me = cache.myId();
        boolean parent = cache.iAmParent();
        String name = cache.myName();
        toolbar.setTitle(name.isEmpty() ? getString(R.string.tasks_title) : getString(R.string.tasks_title_for, name));
        toolbar.getMenu().findItem(R.id.menu_dashboard).setVisible(cache.iAmAdmin());
        toolbar.getMenu().findItem(R.id.menu_invite).setVisible(cache.iAmAdmin());
        toolbar.getMenu().findItem(R.id.menu_update).setTitle(getString(R.string.menu_update_version,
                BuildConfig.VERSION_NAME));
        TabLayout.Tab familyTab = tabs.getTabAt(TAB_FAMILY);
        if (familyTab != null) familyTab.view.setVisibility(parent ? View.VISIBLE : View.GONE);
        if (!parent && tabs.getSelectedTabPosition() == TAB_FAMILY) tabs.selectTab(tabs.getTabAt(TAB_MINE));

        String problem = prefs.taskProblem();
        int pending = cache.pending().length();
        String status = problem.isEmpty() ? TaskFormat.syncedAgo(this, cache.syncedAt()) : problem;
        if (pending > 0) status += " · " + getResources().getQuantityString(R.plurals.pending_changes, pending, pending);
        syncStatus.setText(status);

        List<Task> all = cache.tasks();
        List<Row> rows = new ArrayList<>();
        int tab = tabs.getSelectedTabPosition();
        if (!paired || me.isEmpty()) {
            adapter.set(rows);
            empty.setVisibility(View.VISIBLE);
            emptyText.setText(paired ? R.string.tasks_first_sync : R.string.tasks_not_paired);
            emptyButton.setVisibility(paired ? View.GONE : View.VISIBLE);
            addFab.setVisibility(paired ? View.VISIBLE : View.GONE);
            return;
        }
        addFab.setVisibility(View.VISIBLE);
        if (tab == TAB_MINE) {
            List<Task> ok = TaskLists.needMyOk(all, me, parent);
            if (!ok.isEmpty()) {
                rows.add(Row.header(getString(R.string.header_need_ok)));
                for (Task t : ok) rows.add(Row.task(t));
                rows.add(Row.header(getString(R.string.header_mine)));
            }
            for (Task t : TaskLists.mine(all, me)) rows.add(Row.task(t));
        } else if (tab == TAB_ASKED) {
            for (Task t : TaskLists.asked(all, me)) rows.add(Row.task(t));
        } else {
            Map<String, String> names = cache.names();
            List<Task> fam = TaskLists.family(all, me);
            String current = null;
            fam.sort((a, b) -> a.assignee.equals(b.assignee) ? TaskLists.ORDER.compare(a, b)
                    : a.assignee.compareTo(b.assignee));
            for (Task t : fam) {
                if (!t.assignee.equals(current)) {
                    current = t.assignee;
                    rows.add(Row.header(TaskLists.name(names, current)));
                }
                rows.add(Row.task(t));
            }
        }
        adapter.set(rows);
        boolean none = rows.isEmpty();
        empty.setVisibility(none ? View.VISIBLE : View.GONE);
        emptyButton.setVisibility(View.GONE);
        emptyText.setText(tab == TAB_MINE ? R.string.empty_mine : tab == TAB_ASKED ? R.string.empty_asked
                : R.string.empty_family);
    }

    private void refreshRecord() {
        boolean rec = RecorderService.isRecording();
        if (rec) {
            long s = RecorderService.elapsedMs() / 1000;
            recordFab.setText(getString(R.string.fab_stop,
                    String.format(Locale.getDefault(), "%d:%02d", s / 60, s % 60)));
            recordFab.setIconResource(R.drawable.ic_stop);
            recordFab.setBackgroundTintList(ContextCompat.getColorStateList(this, R.color.recording));
            recordFab.setTextColor(ContextCompat.getColor(this, R.color.white));
            recordFab.setIconTint(ContextCompat.getColorStateList(this, R.color.white));
        } else {
            recordFab.setText(R.string.fab_record);
            recordFab.setIconResource(R.drawable.ic_mic);
            recordFab.setBackgroundTintList(ContextCompat.getColorStateList(this, R.color.accent));
            recordFab.setTextColor(ContextCompat.getColor(this, R.color.white));
            recordFab.setIconTint(ContextCompat.getColorStateList(this, R.color.white));
        }
    }

    private void toggleRecording() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            askPermissions();
            return;
        }
        if (prefs.token().isEmpty()) {
            Toast.makeText(this, R.string.tasks_not_paired, Toast.LENGTH_LONG).show();
            return;
        }
        boolean rec = RecorderService.isRecording();
        RecorderService.send(this, rec ? RecorderService.ACTION_STOP : RecorderService.ACTION_START);
        main.removeCallbacks(ticker);
        main.postDelayed(ticker, 200);
    }

    private void askPermissions() {
        List<String> needed = new ArrayList<>();
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.POST_NOTIFICATIONS);
        if (!needed.isEmpty()) permissions.launch(needed.toArray(new String[0]));
    }

    private void openDashboard() {
        io.execute(() -> {
            try {
                String url = TaskApi.dashboardLink(prefs);
                main.post(() -> startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))));
            } catch (IOException e) {
                main.post(() -> Toast.makeText(this, getString(R.string.dashboard_failed, e.getMessage()),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    // ---------------------------------------------------------------- task actions

    private void act(Task t, String action, String until) {
        TaskReceiver.apply(this, t.id, action, until);
    }

    private void showTaskMenu(Task t) {
        String me = cache.myId();
        long now = System.currentTimeMillis();
        TimeZone tz = TimeZone.getDefault();
        List<String> labels = new ArrayList<>();
        List<Runnable> actions = new ArrayList<>();
        if (t.isMessage() && t.isOpen()) {
            labels.add(getString(R.string.send_whatsapp));
            actions.add(() -> sendWhatsApp(t));
            labels.add(getString(R.string.message_edit));
            actions.add(() -> editMessage(t));
            labels.add(getString(R.string.message_copy));
            actions.add(() -> copyMessage(t));
        }
        if (t.isRequested() && cache.iAmParent() && !me.equals(t.createdBy)) {
            labels.add(getString(R.string.action_accept));
            actions.add(() -> act(t, "accept", null));
            labels.add(getString(R.string.action_decline));
            actions.add(() -> act(t, "decline", null));
        }
        if (t.isOpen()) {
            labels.add(getString(R.string.action_done));
            actions.add(() -> act(t, "done", null));
            labels.add(getString(R.string.snooze_hour));
            actions.add(() -> act(t, "snooze", TaskLists.inAnHour(now, tz)));
            String tonight = TaskLists.tonight(now, tz);
            if (tonight != null) {
                labels.add(getString(R.string.snooze_tonight));
                actions.add(() -> act(t, "snooze", tonight));
            }
            labels.add(getString(R.string.snooze_tomorrow));
            actions.add(() -> act(t, "snooze", TaskLists.tomorrowMorning(now, tz)));
            labels.add(getString(R.string.snooze_pick));
            actions.add(() -> pickDateTime(when -> act(t, "snooze", when)));
        } else if (t.isDone() || "declined".equals(t.status)) {
            labels.add(getString(R.string.action_reopen));
            actions.add(() -> act(t, "reopen", null));
        }
        if (!"declined".equals(t.status) && !t.isMessage()) {
            labels.add(getString(R.string.action_edit));
            actions.add(() -> showAddDialog(t));
        }
        if (me.equals(t.createdBy) || cache.iAmAdmin()) {
            labels.add(getString(R.string.action_delete));
            actions.add(() -> act(t, "delete", null));
        }
        String meta = TaskFormat.meta(this, t, me, cache.names());
        new MaterialAlertDialogBuilder(this)
                .setTitle(t.title + (meta.isEmpty() ? "" : "\n" + meta))
                .setItems(labels.toArray(new String[0]), (d, which) -> actions.get(which).run())
                .show();
    }

    interface WhenPicked {
        void picked(String localWhen);
    }

    /** Date, then time. Result "yyyy-MM-ddTHH:mm" in the phone's time zone. */
    private void pickDateTime(WhenPicked done) {
        MaterialDatePicker<Long> date = MaterialDatePicker.Builder.datePicker()
                .setTitleText(R.string.pick_day)
                .setSelection(MaterialDatePicker.todayInUtcMilliseconds()).build();
        date.addOnPositiveButtonClickListener(utcMidnight -> {
            Calendar utc = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
            utc.setTimeInMillis(utcMidnight);
            String day = String.format(Locale.US, "%04d-%02d-%02d", utc.get(Calendar.YEAR),
                    utc.get(Calendar.MONTH) + 1, utc.get(Calendar.DAY_OF_MONTH));
            MaterialTimePicker time = new MaterialTimePicker.Builder()
                    .setTimeFormat(TimeFormat.CLOCK_24H).setHour(8).setMinute(0)
                    .setTitleText(R.string.pick_time).build();
            time.addOnPositiveButtonClickListener(v -> done.picked(String.format(Locale.US, "%sT%02d:%02d",
                    day, time.getHour(), time.getMinute())));
            time.show(getSupportFragmentManager(), "time");
        });
        date.show(getSupportFragmentManager(), "date");
    }

    // ---------------------------------------------------------------- new task

    private void showAddDialog() {
        showAddDialog(null);
    }

    /** New task, or (existing != null) edit its title, person and time. */
    private void showAddDialog(Task existing) {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_add_task, null, false);
        TextInputEditText title = v.findViewById(R.id.add_title);
        ChipGroup people = v.findViewById(R.id.add_people);
        ChipGroup when = v.findViewById(R.id.add_when);
        TextView requestHint = v.findViewById(R.id.add_request_hint);
        String me = cache.myId();
        boolean parent = cache.iAmParent();

        Map<String, String> names = cache.names();
        if (names.isEmpty()) names.put(me, cache.myName());
        for (Map.Entry<String, String> e : names.entrySet()) {
            Chip c = chip(e.getKey().equals(me) ? getString(R.string.add_me) : e.getValue());
            c.setTag(e.getKey());
            people.addView(c);
            if (e.getKey().equals(existing == null ? me : existing.assignee)) people.check(c.getId());
        }
        people.setOnCheckedStateChangeListener((g, ids) -> {
            View sel = ids.isEmpty() ? null : g.findViewById(ids.get(0));
            boolean other = sel != null && !me.equals(sel.getTag());
            requestHint.setVisibility(!parent && other ? View.VISIBLE : View.GONE);
        });

        long now = System.currentTimeMillis();
        TimeZone tz = TimeZone.getDefault();
        final String[] picked = {null};
        Chip none = chip(getString(R.string.when_none));
        none.setTag("");
        when.addView(none);
        when.check(none.getId());
        if (existing != null && existing.due != null) {
            Chip keep = chip(TaskFormat.when(this, existing.due));
            keep.setTag(existing.due);
            when.addView(keep);
            when.check(keep.getId());
        }
        String tonight = TaskLists.tonight(now, tz);
        if (tonight != null) {
            Chip c = chip(getString(R.string.when_tonight));
            c.setTag(tonight);
            when.addView(c);
        }
        Chip tomorrow = chip(getString(R.string.when_tomorrow_morning));
        tomorrow.setTag(TaskLists.tomorrowMorning(now, tz));
        when.addView(tomorrow);
        Chip pick = chip(getString(R.string.when_pick));
        pick.setTag("pick");
        when.addView(pick);
        pick.setOnClickListener(x -> pickDateTime(w -> {
            picked[0] = w;
            pick.setText(TaskFormat.when(this, w));
        }));

        if (existing != null) {
            title.setText(existing.title);
            if (title.getText() != null) title.setSelection(title.getText().length());
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(existing == null ? R.string.add_title : R.string.edit_title)
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.add_save, (d, w) -> {
                    String text = title.getText() == null ? "" : title.getText().toString().trim();
                    if (text.isEmpty()) return;
                    View selPerson = people.findViewById(people.getCheckedChipId());
                    String who = selPerson == null ? me : (String) selPerson.getTag();
                    View selWhen = when.findViewById(when.getCheckedChipId());
                    String tag = selWhen == null ? "" : (String) selWhen.getTag();
                    String due = "pick".equals(tag) ? picked[0] : (tag.isEmpty() ? null : tag);
                    if (existing == null) create(text, who, due);
                    else edit(existing, text, who, due);
                })
                .show();
        title.requestFocus();
    }

    private void edit(Task t, String title, String assignee, String due) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.edit(prefs, t.id, title, assignee, due);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    refresh();
                });
            }
        });
    }

    private Chip chip(String text) {
        Chip c = new Chip(this);
        c.setText(text);
        c.setCheckable(true);
        c.setId(View.generateViewId());
        return c;
    }

    private void create(String title, String assignee, String due) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.create(prefs, title, assignee, due);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.add_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    refresh();
                });
            }
        });
    }

    // ---------------------------------------------------------------- list

    static final class Row {
        final String header;
        final Task task;

        private Row(String header, Task task) {
            this.header = header;
            this.task = task;
        }

        static Row header(String h) {
            return new Row(h, null);
        }

        static Row task(Task t) {
            return new Row(null, t);
        }
    }

    final class Adapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
        private List<Row> rows = new ArrayList<>();

        void set(List<Row> r) {
            rows = r;
            notifyDataSetChanged();
        }

        Task taskAt(int pos) {
            return pos >= 0 && pos < rows.size() ? rows.get(pos).task : null;
        }

        @Override
        public int getItemViewType(int position) {
            return rows.get(position).task == null ? 0 : 1;
        }

        @Override
        public int getItemCount() {
            return rows.size();
        }

        @NonNull
        @Override
        public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int type) {
            LayoutInflater inf = LayoutInflater.from(parent.getContext());
            View v = inf.inflate(type == 0 ? R.layout.item_header : R.layout.item_task, parent, false);
            return new RecyclerView.ViewHolder(v) { };
        }

        @Override
        public void onBindViewHolder(@NonNull RecyclerView.ViewHolder h, int position) {
            Row r = rows.get(position);
            if (r.task == null) {
                ((TextView) h.itemView).setText(r.header);
                return;
            }
            Task t = r.task;
            TextView title = h.itemView.findViewById(R.id.title);
            TextView meta = h.itemView.findViewById(R.id.meta);
            MaterialCheckBox check = h.itemView.findViewById(R.id.check);
            title.setText(t.isMessage() ? "💬 " + t.title : t.title);
            boolean done = t.isDone() || "declined".equals(t.status);
            title.setPaintFlags(done ? title.getPaintFlags() | Paint.STRIKE_THRU_TEXT_FLAG
                    : title.getPaintFlags() & ~Paint.STRIKE_THRU_TEXT_FLAG);
            title.setAlpha(done ? 0.55f : 1f);
            String m = TaskFormat.meta(TasksActivity.this, t, cache.myId(), cache.names());
            meta.setText(m);
            meta.setVisibility(m.isEmpty() ? View.GONE : View.VISIBLE);
            if (meta.getTag() == null) meta.setTag(meta.getTextColors());   // the theme's grey, kept for reuse
            if (TaskFormat.overdue(t)) meta.setTextColor(ContextCompat.getColor(TasksActivity.this, R.color.recording));
            else meta.setTextColor((android.content.res.ColorStateList) meta.getTag());
            check.setOnCheckedChangeListener(null);
            check.setChecked(t.isDone());
            check.setEnabled(t.isOpen() || t.isDone());
            check.setOnCheckedChangeListener((b, on) -> act(t, on ? "done" : "reopen", null));
            h.itemView.setOnClickListener(v -> showTaskMenu(t));
        }
    }

    /** Swipe a task sideways to mark it done (open tasks only). */
    final class SwipeToDone extends ItemTouchHelper.SimpleCallback {
        SwipeToDone() {
            super(0, ItemTouchHelper.START | ItemTouchHelper.END);
        }

        @Override
        public int getSwipeDirs(@NonNull RecyclerView rv, @NonNull RecyclerView.ViewHolder vh) {
            Task t = adapter.taskAt(vh.getBindingAdapterPosition());
            return t != null && t.isOpen() ? super.getSwipeDirs(rv, vh) : 0;
        }

        @Override
        public boolean onMove(@NonNull RecyclerView rv, @NonNull RecyclerView.ViewHolder a,
                              @NonNull RecyclerView.ViewHolder b) {
            return false;
        }

        @Override
        public void onSwiped(@NonNull RecyclerView.ViewHolder vh, int direction) {
            Task t = adapter.taskAt(vh.getBindingAdapterPosition());
            if (t != null) act(t, "done", null);
            else refresh();
        }
    }
}
