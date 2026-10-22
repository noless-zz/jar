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
import com.noam.jar.core.Area;
import com.noam.jar.core.Award;
import com.noam.jar.core.Board;
import com.noam.jar.core.Series;
import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import java.io.IOException;
import org.json.JSONArray;
import org.json.JSONObject;
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
    private static final int TAB_MINE = 0, TAB_ASKED = 1, TAB_FAMILY = 2, TAB_BOARD = 3, TAB_IDEAS = 4;
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
        tabs.addTab(tabs.newTab().setText(R.string.tab_board));
        tabs.addTab(tabs.newTab().setText(R.string.tab_ideas));
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
            } else if (id == R.id.menu_recurring) {
                showSeriesList();
            } else if (id == R.id.menu_areas) {
                showAreas();
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
        addFab.setOnClickListener(v -> {
            if (tabs.getSelectedTabPosition() == TAB_IDEAS) showIdeaDialog();
            else showAddDialog();
        });
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
        if (tag != null) {
            String news = Updater.whatsNew(this);
            String text = getString(R.string.update_available, tag, BuildConfig.VERSION_NAME);
            updateText.setText(news.isEmpty() ? text : text + "\n" + getString(R.string.update_whats_new, news));
        }
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
        TaskFormat.setAreas(cache.areas());
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
        } else if (tab == TAB_BOARD) {
            rows.addAll(boardRows(parent));
        } else if (tab == TAB_IDEAS) {
            for (Task t : TaskLists.ideas(all)) rows.add(Row.task(t));
        } else {
            Map<String, String> names = cache.names();
            List<Task> fam = TaskLists.family(all, me);
            String current = null;
            // Shared tasks get their own group at the end ("~" sorts after the ids).
            java.util.function.Function<Task, String> group = x -> x.isShared() ? "~shared" : x.assignee;
            fam.sort((a, b) -> group.apply(a).equals(group.apply(b)) ? TaskLists.ORDER.compare(a, b)
                    : group.apply(a).compareTo(group.apply(b)));
            for (Task t : fam) {
                if (!group.apply(t).equals(current)) {
                    current = group.apply(t);
                    rows.add(Row.header(t.isShared() ? getString(R.string.header_shared)
                            : TaskLists.name(names, current)));
                }
                rows.add(Row.task(t));
            }
        }
        adapter.set(rows);
        boolean none = rows.isEmpty();
        empty.setVisibility(none ? View.VISIBLE : View.GONE);
        emptyButton.setVisibility(View.GONE);
        emptyText.setText(tab == TAB_MINE ? R.string.empty_mine : tab == TAB_ASKED ? R.string.empty_asked
                : tab == TAB_IDEAS ? R.string.empty_ideas : R.string.empty_family);
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
        if (t.isIdea()) {
            showIdeaMenu(t);
            return;
        }
        String me = cache.myId();
        long now = System.currentTimeMillis();
        TimeZone tz = TimeZone.getDefault();
        List<String> labels = new ArrayList<>();
        List<Runnable> actions = new ArrayList<>();
        if (!t.isMessage()) {
            labels.add(t.waitingOn(me) ? getString(R.string.thread_answer)
                    : t.thread.isEmpty() ? getString(R.string.thread_open_empty)
                    : getString(R.string.thread_open, t.thread.size()));
            actions.add(() -> startActivity(new Intent(this, TaskThreadActivity.class)
                    .putExtra(TaskThreadActivity.EXTRA_ID, t.id)));
        }
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
        // Areas of responsibility: offer the move to the area's owner; approve or decline a waiting move.
        Map<String, String> names = cache.names();
        if (t.mayApproveHandover(me, cache.iAmParent())) {
            labels.add(getString(R.string.handover_accept, TaskLists.name(names, t.handoverTo)));
            actions.add(() -> act(t, "handover_accept", null));
            labels.add(getString(R.string.handover_decline));
            actions.add(() -> act(t, "handover_decline", null));
        } else if (t.hasHandover() && me.equals(t.handoverBy)) {
            labels.add(getString(R.string.handover_cancel));
            actions.add(() -> act(t, "handover_decline", null));
        } else if (!t.areaSuggest.isEmpty() && (t.isFor(me) || me.equals(t.createdBy))) {
            Area area = TaskFormat.area(this, t.area);
            labels.add(getString(R.string.handover_ask, TaskLists.name(names, t.areaSuggest),
                    area == null ? "" : area.label()));
            actions.add(() -> act(t, "handover", null));
            labels.add(getString(R.string.handover_keep));
            actions.add(() -> act(t, "dismiss_suggest", null));
        }
        if (t.openFor(me)) {
            labels.add(getString(t.eachMust() && t.isFor(me) ? R.string.action_my_part_done : R.string.action_done));
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
        } else if (t.doneFor(me) || "declined".equals(t.status)) {
            labels.add(getString(R.string.action_reopen));
            actions.add(() -> act(t, "reopen", null));
        }
        if (cache.iAmParent() && t.canRate()) {
            labels.add(getString(R.string.effort_menu));
            actions.add(() -> showEffortDialog(t));
        }
        if (!"declined".equals(t.status) && !t.isMessage()) {
            labels.add(getString(R.string.action_edit));
            actions.add(() -> showAddDialog(t));
        }
        if (canMakeRepeat(t)) {
            labels.add(getString(R.string.make_repeat));
            actions.add(() -> showAddDialog(t, true));
        }
        Series series = t.isRecurring() ? findSeries(t.seriesId) : null;
        boolean seriesMine = series != null
                && series.canChange(me, cache.iAmAdmin(), cache.iAmParent(), cache.parents());
        if (seriesMine) {
            labels.add("🔁 " + getString(R.string.recurring_stop));
            actions.add(() -> confirmStopSeries(series));
        }
        if (me.equals(t.createdBy) || cache.iAmAdmin()) {
            labels.add(getString(R.string.action_delete));
            actions.add(() -> {
                if (!seriesMine) {
                    act(t, "delete", null);
                    return;
                }
                new MaterialAlertDialogBuilder(this)
                        .setTitle(getString(R.string.delete_recurring_title, t.title))
                        .setItems(new String[]{getString(R.string.delete_only_this),
                                getString(R.string.delete_whole_series)}, (d, which) -> {
                            if (which == 0) act(t, "delete", null);
                            else seriesAct(series.id, "stop");
                        })
                        .show();
            });
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

    private void showAddDialog(Task existing) {
        showAddDialog(existing, false);
    }

    /** May I turn this one-time task into a recurring one? (the PC checks the same) */
    private boolean canMakeRepeat(Task t) {
        if (t.isRecurring() || t.isMessage() || t.isIdea() || t.isLesson() || !(t.isOpen() || t.isRequested()))
            return false;
        String me = cache.myId();
        if (me.equals(t.createdBy) || cache.iAmAdmin()) return true;
        if (!cache.iAmParent()) return false;
        java.util.Set<String> parents = cache.parents();
        for (String o : t.owners()) if (parents.contains(o)) return false;
        return true;
    }

    /**
     * New task, or (existing != null) edit its title, person and time — and make a one-time task repeat
     * ({@code repeatNow}: opened from "Make it repeat", with "every day" picked).
     */
    private void showAddDialog(Task existing, boolean repeatNow) {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_add_task, null, false);
        TextInputEditText title = v.findViewById(R.id.add_title);
        ChipGroup people = v.findViewById(R.id.add_people);
        ChipGroup when = v.findViewById(R.id.add_when);
        TextView requestHint = v.findViewById(R.id.add_request_hint);
        View modeBox = v.findViewById(R.id.add_mode_box);
        ChipGroup mode = v.findViewById(R.id.add_mode);
        if (existing != null && existing.eachMust()) mode.check(R.id.add_mode_all);
        String me = cache.myId();
        boolean parent = cache.iAmParent();

        Map<String, String> names = cache.names();
        if (names.isEmpty()) names.put(me, cache.myName());
        for (Map.Entry<String, String> e : names.entrySet()) {
            Chip c = chip(e.getKey().equals(me) ? getString(R.string.add_me) : e.getValue());
            c.setTag(e.getKey());
            people.addView(c);
            if (existing == null ? e.getKey().equals(me) : existing.isFor(e.getKey())) people.check(c.getId());
        }
        java.util.function.Consumer<List<Integer>> onPeople = ids -> {
            boolean other = false;
            for (int id : ids) {
                View sel = people.findViewById(id);
                if (sel != null && !me.equals(sel.getTag())) other = true;
            }
            requestHint.setVisibility(!parent && other ? View.VISIBLE : View.GONE);
            modeBox.setVisibility(ids.size() > 1 ? View.VISIBLE : View.GONE);
        };
        onPeople.accept(people.getCheckedChipIds());
        people.setOnCheckedStateChangeListener((g, ids) -> onPeople.accept(ids));

        // Repeats? (new tasks only): every day / on chosen days / every week / every month, optionally at a time.
        View repeatBox = v.findViewById(R.id.add_repeat_box);
        ChipGroup repeat = v.findViewById(R.id.add_repeat);
        ChipGroup days = v.findViewById(R.id.add_days);
        Chip repeatTime = v.findViewById(R.id.add_repeat_time);
        Chip turns = v.findViewById(R.id.add_mode_turns);
        View whenLabel = v.findViewById(R.id.add_when_label);
        final String[] repeatAt = {""};
        boolean mayRepeat = existing == null || canMakeRepeat(existing);
        repeatBox.setVisibility(mayRepeat ? View.VISIBLE : View.GONE);
        if (repeatNow) repeat.check(R.id.add_repeat_daily);
        String[] dayKeys = {"sun", "mon", "tue", "wed", "thu", "fri", "sat"};
        String[] dayNames = getResources().getStringArray(R.array.week_days_short);
        for (int i = 0; i < dayKeys.length; i++) {
            Chip c = chip(dayNames[i]);
            c.setTag(dayKeys[i]);
            days.addView(c);
        }
        Runnable onRepeat = () -> {
            int rid = repeat.getCheckedChipId();
            boolean on = mayRepeat && rid != View.NO_ID && rid != R.id.add_repeat_once;
            days.setVisibility(on && rid == R.id.add_repeat_days ? View.VISIBLE : View.GONE);
            repeatTime.setVisibility(on ? View.VISIBLE : View.GONE);
            when.setVisibility(on ? View.GONE : View.VISIBLE);
            whenLabel.setVisibility(on ? View.GONE : View.VISIBLE);
            turns.setVisibility(on ? View.VISIBLE : View.GONE);
            if (!on && mode.getCheckedChipId() == R.id.add_mode_turns) mode.check(R.id.add_mode_any);
        };
        repeat.setOnCheckedStateChangeListener((g, ids) -> onRepeat.run());
        onRepeat.run();
        repeatTime.setOnClickListener(x -> {
            MaterialTimePicker tp = new MaterialTimePicker.Builder()
                    .setTimeFormat(TimeFormat.CLOCK_24H).setHour(20).setMinute(0)
                    .setTitleText(R.string.pick_time).build();
            tp.addOnPositiveButtonClickListener(b -> {
                repeatAt[0] = String.format(Locale.US, "%02d:%02d", tp.getHour(), tp.getMinute());
                repeatTime.setText(getString(R.string.repeat_at, repeatAt[0]));
            });
            tp.show(getSupportFragmentManager(), "repeat_time");
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
                    // In the order the family list shows them; the first is the "main" one for older apps.
                    List<String> who = new ArrayList<>();
                    for (int i = 0; i < people.getChildCount(); i++) {
                        View c = people.getChildAt(i);
                        if (c instanceof Chip && ((Chip) c).isChecked()) who.add((String) c.getTag());
                    }
                    if (who.isEmpty()) who.add(me);
                    boolean each = who.size() > 1 && mode.getCheckedChipId() == R.id.add_mode_all;
                    String rule = mayRepeat ? repeatRule(repeat.getCheckedChipId(), days) : null;
                    boolean rotate = who.size() > 1 && mode.getCheckedChipId() == R.id.add_mode_turns;
                    if (rule != null && existing == null) {
                        createRecurring(text, who, each, rule, repeatAt[0], rotate);
                        return;
                    }
                    View selWhen = when.findViewById(when.getCheckedChipId());
                    String tag = selWhen == null ? "" : (String) selWhen.getTag();
                    String due = "pick".equals(tag) ? picked[0] : (tag.isEmpty() ? null : tag);
                    if (existing == null) create(text, who, each, due);
                    else if (rule != null) editAndRepeat(existing, text, who, each, due, rule, repeatAt[0], rotate);
                    else edit(existing, text, who, each, due);
                })
                .show();
        title.requestFocus();
    }

    /** The PC's rule for the chosen "Repeats?" chip, or null for a one-time task. */
    private static String repeatRule(int chipId, ChipGroup days) {
        if (chipId == R.id.add_repeat_daily) return "daily";
        if (chipId == R.id.add_repeat_weekly) return "weekly";
        if (chipId == R.id.add_repeat_monthly) return "monthly";
        if (chipId != R.id.add_repeat_days) return null;
        List<String> picked = new ArrayList<>();
        for (int i = 0; i < days.getChildCount(); i++) {
            View c = days.getChildAt(i);
            if (c instanceof Chip && ((Chip) c).isChecked()) picked.add((String) c.getTag());
        }
        return picked.isEmpty() ? "weekly" : "weekly:" + String.join(",", picked);
    }

    private void createRecurring(String title, List<String> owners, boolean each, String rule, String time,
                                 boolean rotate) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.createRecurring(prefs, title, owners, each, rule, time, rotate);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.add_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    refresh();
                });
            }
        });
    }

    // ---------------------------------------------------------------- recurring tasks

    private Series findSeries(String id) {
        for (Series s : cache.series()) if (s.id.equals(id)) return s;
        return null;
    }

    /** Toolbar → "Recurring tasks": every series I can see; tap one to pause, resume or stop it. */
    private void showSeriesList() {
        List<Series> all = cache.series();
        if (all.isEmpty()) {
            Toast.makeText(this, R.string.recurring_none, Toast.LENGTH_LONG).show();
            return;
        }
        Map<String, String> names = cache.names();
        String[] items = new String[all.size()];
        for (int i = 0; i < all.size(); i++) {
            Series s = all.get(i);
            StringBuilder b = new StringBuilder(s.title).append("\n🔁 ").append(s.label)
                    .append(" · ").append(TaskFormat.people(names, s.owners));
            if (s.rotate && !s.nextTurn.isEmpty())
                b.append(" · ").append(getString(R.string.recurring_turn, TaskLists.name(names, s.nextTurn)));
            if (s.isPaused()) b.append(" · ").append(getString(R.string.recurring_paused));
            items[i] = b.toString();
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.menu_recurring)
                .setItems(items, (d, which) -> showSeriesMenu(all.get(which)))
                .show();
    }

    private void showSeriesMenu(Series s) {
        if (!s.canChange(cache.myId(), cache.iAmAdmin(), cache.iAmParent(), cache.parents())) {
            Toast.makeText(this, R.string.recurring_not_yours, Toast.LENGTH_LONG).show();
            return;
        }
        String[] items = {getString(s.isPaused() ? R.string.recurring_resume : R.string.recurring_pause),
                getString(R.string.recurring_stop)};
        new MaterialAlertDialogBuilder(this)
                .setTitle(s.title + "\n🔁 " + s.label)
                .setItems(items, (d, which) -> {
                    if (which == 0) seriesAct(s.id, s.isPaused() ? "resume" : "pause");
                    else confirmStopSeries(s);
                })
                .show();
    }

    private void confirmStopSeries(Series s) {
        new MaterialAlertDialogBuilder(this)
                .setMessage(getString(R.string.recurring_stop_confirm, s.title))
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.recurring_stop, (d, w) -> seriesAct(s.id, "stop"))
                .show();
    }

    private void seriesAct(String seriesId, String action) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.seriesAct(prefs, seriesId, action);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    refresh();
                });
            }
        });
    }

    // ---------------------------------------------------------------- areas of responsibility

    /** Toolbar → "Areas": who is in charge of what. Parents tap one to change it, or add a new one. */
    private void showAreas() {
        List<Area> all = cache.areas();
        Map<String, String> names = cache.names();
        boolean parent = cache.iAmParent();
        List<String> items = new ArrayList<>();
        for (Area a : all) items.add(a.label() + " — " + TaskLists.name(names, a.owner));
        if (parent) items.add(getString(R.string.areas_add));
        if (items.isEmpty()) {
            Toast.makeText(this, R.string.areas_none, Toast.LENGTH_LONG).show();
            return;
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.menu_areas)
                .setItems(items.toArray(new String[0]), (d, which) -> {
                    if (!parent) return;
                    if (which == all.size()) showAreaEditor(null);
                    else showAreaMenu(all.get(which));
                })
                .show();
    }

    private void showAreaMenu(Area a) {
        String[] items = {getString(R.string.areas_change_owner), getString(R.string.areas_edit),
                getString(R.string.areas_delete)};
        new MaterialAlertDialogBuilder(this)
                .setTitle(a.label())
                .setItems(items, (d, which) -> {
                    if (which == 0) pickPerson(getString(R.string.areas_change_owner), a.owner,
                            id -> areaCall(() -> TaskApi.editArea(prefs, a.id, new JSONObject().put("owner", id))));
                    else if (which == 1) showAreaEditor(a);
                    else new MaterialAlertDialogBuilder(this)
                                .setMessage(getString(R.string.areas_delete_confirm, a.label()))
                                .setNegativeButton(android.R.string.cancel, null)
                                .setPositiveButton(R.string.areas_delete, (x, y) -> areaCall(() -> TaskApi.deleteArea(prefs, a.id)))
                                .show();
                })
                .show();
    }

    interface PersonPicked {
        void picked(String id);
    }

    private void pickPerson(String title, String current, PersonPicked done) {
        Map<String, String> names = cache.names();
        List<String> ids = new ArrayList<>(names.keySet());
        String[] labels = new String[ids.size()];
        int checked = -1;
        for (int i = 0; i < ids.size(); i++) {
            labels[i] = names.get(ids.get(i));
            if (ids.get(i).equals(current)) checked = i;
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(title)
                .setSingleChoiceItems(labels, checked, (d, which) -> {
                    d.dismiss();
                    done.picked(ids.get(which));
                })
                .show();
    }

    /** New area (a == null) or change name, emoji and the words that put a task in it. */
    private void showAreaEditor(Area a) {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_area, null, false);
        TextInputEditText name = v.findViewById(R.id.area_name);
        TextInputEditText emoji = v.findViewById(R.id.area_emoji);
        TextInputEditText words = v.findViewById(R.id.area_keywords);
        if (a != null) {
            name.setText(a.name);
            emoji.setText(a.emoji);
            words.setText(String.join(", ", a.keywords));
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(a == null ? R.string.areas_add : R.string.areas_edit)
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.add_save, (d, w) -> {
                    String n = name.getText() == null ? "" : name.getText().toString().trim();
                    String e = emoji.getText() == null ? "" : emoji.getText().toString().trim();
                    List<String> kw = new ArrayList<>();
                    for (String k : (words.getText() == null ? "" : words.getText().toString()).split("[,،\\n]+")) {
                        if (!k.trim().isEmpty()) kw.add(k.trim());
                    }
                    if (n.isEmpty()) return;
                    if (a == null) {
                        pickPerson(getString(R.string.areas_owner), cache.myId(),
                                id -> areaCall(() -> TaskApi.addArea(prefs, n, e.isEmpty() ? "📌" : e, id, kw)));
                    } else {
                        areaCall(() -> TaskApi.editArea(prefs, a.id, new JSONObject().put("name", n)
                                .put("emoji", e.isEmpty() ? a.emoji : e).put("keywords", new JSONArray(kw))));
                    }
                })
                .show();
        name.requestFocus();
    }

    interface AreaCall {
        void run() throws IOException, org.json.JSONException;
    }

    private void areaCall(AreaCall call) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                call.run();
                main.post(() -> TaskSync.now(this));
            } catch (IOException | org.json.JSONException e) {
                main.post(() -> Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    // ---------------------------------------------------------------- Jar ideas

    private void showIdeaDialog() {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_idea, null, false);
        TextInputEditText title = v.findViewById(R.id.idea_title);
        TextInputEditText details = v.findViewById(R.id.idea_details);
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.idea_new)
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.add_save, (d, w) -> {
                    String text = title.getText() == null ? "" : title.getText().toString().trim();
                    String more = details.getText() == null ? "" : details.getText().toString().trim();
                    if (text.isEmpty()) return;
                    syncStatus.setText(R.string.syncing);
                    io.execute(() -> {
                        try {
                            TaskApi.createIdea(prefs, text, more);
                            main.post(() -> TaskSync.now(this));
                        } catch (IOException e) {
                            main.post(() -> Toast.makeText(this, getString(R.string.idea_failed, e.getMessage()),
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .show();
        title.requestFocus();
    }

    /** An idea: everyone can open its notes (and add one); the admin decides; whoever suggested it can delete it. */
    private void showIdeaMenu(Task t) {
        String me = cache.myId();
        boolean admin = cache.iAmAdmin();
        List<String> labels = new ArrayList<>();
        List<Runnable> actions = new ArrayList<>();
        labels.add(t.thread.isEmpty() ? getString(R.string.thread_open_empty) : getString(R.string.thread_open, t.thread.size()));
        actions.add(() -> startActivity(new Intent(this, TaskThreadActivity.class)
                .putExtra(TaskThreadActivity.EXTRA_ID, t.id)));
        if (admin && t.isRequested()) {
            labels.add(getString(R.string.idea_accept));
            actions.add(() -> act(t, "accept", null));
            labels.add(getString(R.string.idea_decline));
            actions.add(() -> declineIdea(t));
        } else if (admin && t.isOpen()) {
            labels.add(getString(R.string.idea_shipped));
            actions.add(() -> act(t, "done", null));
        } else if (admin && t.isDone()) {
            labels.add(getString(R.string.idea_reopen));
            actions.add(() -> act(t, "reopen", null));
        }
        if (me.equals(t.createdBy) || admin) {
            labels.add(getString(R.string.action_delete));
            actions.add(() -> act(t, "delete", null));
        }
        String meta = TaskFormat.meta(this, t, me, cache.names());
        new MaterialAlertDialogBuilder(this)
                .setTitle("💡 " + t.title + (meta.isEmpty() ? "" : "\n" + meta)
                        + (t.notes.isEmpty() ? "" : "\n\n" + t.notes))
                .setItems(labels.toArray(new String[0]), (d, which) -> actions.get(which).run())
                .show();
    }

    private void declineIdea(Task t) {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_idea, null, false);
        v.findViewById(R.id.idea_hint).setVisibility(View.GONE);
        v.findViewById(R.id.idea_details_box).setVisibility(View.GONE);
        ((com.google.android.material.textfield.TextInputLayout) v.findViewById(R.id.idea_title_box))
                .setHint(R.string.idea_decline_note);
        TextInputEditText note = v.findViewById(R.id.idea_title);
        new MaterialAlertDialogBuilder(this)
                .setTitle(t.title)
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.idea_decline, (d, w) -> {
                    String text = note.getText() == null ? "" : note.getText().toString().trim();
                    syncStatus.setText(R.string.syncing);
                    io.execute(() -> {
                        try {
                            TaskApi.declineIdea(prefs, t.id, text);
                            main.post(() -> TaskSync.now(this));
                        } catch (IOException e) {
                            main.post(() -> Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()),
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .show();
    }

    /** Save the edit, then make the task repeat (it stays as the first time). */
    private void editAndRepeat(Task t, String title, List<String> owners, boolean each, String due, String rule,
                               String time, boolean rotate) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.edit(prefs, t.id, title, owners, each, due);
                TaskApi.makeRecurring(prefs, t.id, rule, time, rotate);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.edit_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    TaskSync.now(this);
                });
            }
        });
    }

    private void edit(Task t, String title, List<String> owners, boolean each, String due) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.edit(prefs, t.id, title, owners, each, due);
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

    private void create(String title, List<String> owners, boolean each, String due) {
        syncStatus.setText(R.string.syncing);
        io.execute(() -> {
            try {
                TaskApi.create(prefs, title, owners, each, due);
                main.post(() -> TaskSync.now(this));
            } catch (IOException e) {
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.add_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                    refresh();
                });
            }
        });
    }

    // ---------------------------------------------------------------- points

    /** The Board tab: my action (work day / lesson note), this week, all time, lessons learned lately. */
    private List<Row> boardRows(boolean parent) {
        Board b = cache.board();
        List<Row> rows = new ArrayList<>();
        if (parent) {
            rows.add(Row.line(getString(R.string.board_work_day, b.workDayCoins), null, "", this::logWorkDay));
        } else {
            rows.add(Row.line(getString(R.string.board_learned), null, "", this::showLessonDialog));
        }
        if (b.people.isEmpty()) {
            rows.add(Row.header(getString(R.string.board_empty)));
            return rows;
        }
        rows.add(Row.header(getString(R.string.board_week, TaskFormat.shortDay(b.weekStart),
                TaskFormat.shortDay(b.weekEnd))));
        String[] medals = {"🥇", "🥈", "🥉"};
        for (int i = 0; i < b.people.size(); i++) {
            Board.Person p = b.people.get(i);
            int rank = i;
            while (rank > 0 && b.people.get(rank - 1).week == p.week) rank--;     // a tie shares the medal
            String medal = p.week > 0 && rank < medals.length ? medals[rank] + " " : "";
            List<String> sub = new ArrayList<>();
            sub.add(getResources().getQuantityString(R.plurals.board_tasks, p.tasksWeek, p.tasksWeek));
            if (p.streak >= 2) sub.add(getString(R.string.board_streak, p.streak));
            if (p.bestCoins > 0 && p.bestTitle != null) sub.add(getString(R.string.board_best, p.bestTitle));
            rows.add(Row.line(medal + p.name, String.join(" · ", sub), String.valueOf(p.week),
                    () -> showLedger(p)));
        }
        rows.add(Row.header(getString(R.string.board_all_time)));
        List<Board.Person> all = new ArrayList<>(b.people);
        all.sort((x, y) -> y.allTime != x.allTime ? Integer.compare(y.allTime, x.allTime) : x.name.compareTo(y.name));
        for (Board.Person p : all) {
            rows.add(Row.line(p.name, null, getString(R.string.coins_label, p.allTime), () -> showLedger(p)));
        }
        rows.add(Row.header(getString(R.string.board_tap_hint)));
        if (!b.lessons.isEmpty()) {
            rows.add(Row.header(getString(R.string.board_lessons)));
            for (Board.Lesson l : b.lessons) {
                String title = l.title.isEmpty() ? l.name : l.name + " · " + l.title;
                rows.add(Row.line(title, l.note, "+" + l.coins, null));
            }
        }
        return rows;
    }

    /** Where a person's coins came from, newest first (private tasks show only as "a private task"). */
    private void showLedger(Board.Person p) {
        List<Board.Line> lines = cache.board().ledger(p.id);
        List<String> items = new ArrayList<>();
        for (Board.Line l : lines) {
            String title = l.title == null ? getString(R.string.ledger_private)
                    : "work_day".equals(l.kind) ? getString(R.string.ledger_work_day) : l.title;
            String day = l.at.length() >= 10 ? TaskFormat.shortDay(l.at.substring(0, 10)) : "";
            items.add(l.reversed ? getString(R.string.ledger_reversed, title)
                    : getString(R.string.ledger_line, l.coins, title, day));
        }
        MaterialAlertDialogBuilder d = new MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.ledger_title, p.name))
                .setPositiveButton(android.R.string.ok, null);
        if (items.isEmpty()) d.setMessage(R.string.ledger_empty);
        else d.setItems(items.toArray(new String[0]), null);
        d.show();
    }

    /** A parent says what a task is worth: a slider 1-10 and "no coins for this one". */
    private void showEffortDialog(Task t) {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_effort, null, false);
        TextView value = v.findViewById(R.id.effort_value);
        android.widget.SeekBar bar = v.findViewById(R.id.effort_bar);
        MaterialCheckBox none = v.findViewById(R.id.effort_none);
        int start = t.effort > 0 ? t.effort : 3;
        bar.setProgress(start - 1);
        none.setChecked(t.noCoins);
        Runnable show = () -> {
            int e = bar.getProgress() + 1;
            value.setText(getString(R.string.effort_value, e, e * 5));
            bar.setEnabled(!none.isChecked());
        };
        bar.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(android.widget.SeekBar s, int p, boolean user) { show.run(); }
            @Override public void onStartTrackingTouch(android.widget.SeekBar s) { }
            @Override public void onStopTrackingTouch(android.widget.SeekBar s) { }
        });
        none.setOnCheckedChangeListener((b, on) -> show.run());
        show.run();
        new MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.effort_title, t.title))
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(android.R.string.ok, (d, w) -> {
                    int effort = bar.getProgress() + 1;
                    boolean noCoins = none.isChecked();
                    io.execute(() -> {
                        try {
                            TaskApi.setPoints(prefs, t.id, noCoins ? 0 : effort, noCoins == t.noCoins ? null : noCoins);
                            main.post(() -> {
                                Toast.makeText(this, R.string.effort_saved, Toast.LENGTH_SHORT).show();
                                TaskSync.now(this);
                            });
                        } catch (IOException e) {
                            main.post(() -> Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .show();
    }

    /** A child writes what they learned; the PC's AI rates the note (can take a few seconds). */
    private void showLessonDialog() {
        View v = LayoutInflater.from(this).inflate(R.layout.dialog_lesson, null, false);
        TextInputEditText subject = v.findViewById(R.id.lesson_subject);
        TextInputEditText learned = v.findViewById(R.id.lesson_learned);
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.lesson_title)
                .setView(v)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.lesson_send, (d, w) -> {
                    String note = learned.getText() == null ? "" : learned.getText().toString().trim();
                    String title = subject.getText() == null ? "" : subject.getText().toString().trim();
                    if (note.length() < 12) {
                        Toast.makeText(this, R.string.lesson_too_short, Toast.LENGTH_LONG).show();
                        return;
                    }
                    Toast.makeText(this, R.string.lesson_rating, Toast.LENGTH_SHORT).show();
                    io.execute(() -> {
                        try {
                            Award a = TaskApi.parseAward(TaskApi.lesson(prefs, title, note));
                            main.post(() -> {
                                PointsUi.toast(this, a);
                                TaskSync.now(this);
                            });
                        } catch (TaskApi.HttpError e) {
                            String msg = e.code == 429 ? getString(R.string.lesson_limit)
                                    : getString(R.string.lesson_failed, e.getMessage());
                            main.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
                        } catch (IOException e) {
                            main.post(() -> Toast.makeText(this, getString(R.string.lesson_failed, e.getMessage()),
                                    Toast.LENGTH_LONG).show());
                        }
                    });
                })
                .show();
    }

    /** A parent: "I worked today" pays the fixed work-day base, once a day. */
    private void logWorkDay() {
        io.execute(() -> {
            try {
                Award a = TaskApi.parseAward(TaskApi.workDay(prefs));
                main.post(() -> {
                    Toast.makeText(this, getString(R.string.workday_logged, a == null ? 0 : a.coins),
                            Toast.LENGTH_LONG).show();
                    TaskSync.now(this);
                });
            } catch (TaskApi.HttpError e) {
                String msg = e.code == 409 ? getString(R.string.workday_already) : e.getMessage();
                main.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
            } catch (IOException e) {
                main.post(() -> Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show());
            }
        });
    }

    // ---------------------------------------------------------------- list

    static final class Row {
        final String header;
        final Task task;
        // a line of the Board tab
        String title, sub, right;
        Runnable click;

        private Row(String header, Task task) {
            this.header = header;
            this.task = task;
        }

        boolean isLine() {
            return title != null;
        }

        static Row header(String h) {
            return new Row(h, null);
        }

        static Row task(Task t) {
            return new Row(null, t);
        }

        static Row line(String title, String sub, String right, Runnable click) {
            Row r = new Row(null, null);
            r.title = title;
            r.sub = sub == null ? "" : sub;
            r.right = right == null ? "" : right;
            r.click = click;
            return r;
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
            Row r = rows.get(position);
            return r.isLine() ? 2 : r.task == null ? 0 : 1;
        }

        @Override
        public int getItemCount() {
            return rows.size();
        }

        @NonNull
        @Override
        public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int type) {
            LayoutInflater inf = LayoutInflater.from(parent.getContext());
            View v = inf.inflate(type == 0 ? R.layout.item_header : type == 2 ? R.layout.item_board
                    : R.layout.item_task, parent, false);
            return new RecyclerView.ViewHolder(v) { };
        }

        @Override
        public void onBindViewHolder(@NonNull RecyclerView.ViewHolder h, int position) {
            Row r = rows.get(position);
            if (r.isLine()) {
                ((TextView) h.itemView.findViewById(R.id.line_title)).setText(r.title);
                TextView sub = h.itemView.findViewById(R.id.line_sub);
                sub.setText(r.sub);
                sub.setVisibility(r.sub.isEmpty() ? View.GONE : View.VISIBLE);
                ((TextView) h.itemView.findViewById(R.id.line_right)).setText(r.right);
                h.itemView.setOnClickListener(r.click == null ? null : v -> r.click.run());
                h.itemView.setClickable(r.click != null);
                return;
            }
            if (r.task == null) {
                ((TextView) h.itemView).setText(r.header);
                return;
            }
            Task t = r.task;
            TextView title = h.itemView.findViewById(R.id.title);
            TextView meta = h.itemView.findViewById(R.id.meta);
            MaterialCheckBox check = h.itemView.findViewById(R.id.check);
            title.setText(t.isMessage() ? "💬 " + t.title : t.isIdea() ? "💡 " + t.title : t.title);
            String me = cache.myId();
            boolean done = t.doneFor(me) || "declined".equals(t.status);
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
            check.setChecked(t.doneFor(me));
            check.setEnabled(t.isIdea() ? cache.iAmAdmin() && (t.isOpen() || t.isDone()) : t.isOpen() || t.isDone());
            check.setOnCheckedChangeListener((b, on) -> act(t, on ? "done" : "reopen", null));
            TextView coins = h.itemView.findViewById(R.id.coins);
            boolean showCoins = t.coins > 0 && !t.isMessage() && !"declined".equals(t.status);
            coins.setVisibility(showCoins ? View.VISIBLE : View.GONE);
            if (showCoins) {
                coins.setText(getString(R.string.coins_label, t.coins));
                coins.setAlpha(t.paid ? 1f : 0.6f);        // a preview until it is done
            }
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
            return t != null && t.openFor(cache.myId()) ? super.getSwipeDirs(rv, vh) : 0;
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
