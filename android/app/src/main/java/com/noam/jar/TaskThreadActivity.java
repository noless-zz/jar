package com.noam.jar;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;
import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import org.json.JSONObject;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Notes and questions on one task, between whoever asked for it and whoever does it.
 * "Ask" sends the text as a question: the task pops up at the top of their list (and the widget)
 * with a notification until they answer. Any note from them answers it. ✨ asks the PC's AI for a
 * few short replies to pick from. Long-press your own note to change or remove it.
 */
public final class TaskThreadActivity extends AppCompatActivity {
    static final String EXTRA_ID = "task_id";

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private Prefs prefs;
    private TaskCache cache;
    private String taskId;
    private TextView taskTitle, taskMeta, banner;
    private LinearLayout list;
    private ScrollView scroll;
    private TextInputEditText input;
    private Button askButton, noteButton, suggestButton;
    private ChipGroup suggestions;
    private View suggestBox;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (LookPrefs.INSTANCE.newUi(this)) {        // the new design has its own notes screen
            startActivity(new android.content.Intent(this, HomeActivity.class)
                    .putExtra(HomeActivity.EXTRA_THREAD, getIntent().getStringExtra(EXTRA_ID)));
            finish();
            return;
        }
        setContentView(R.layout.activity_thread);
        prefs = new Prefs(this);
        cache = new TaskCache(this);
        taskId = getIntent().getStringExtra(EXTRA_ID);
        MaterialToolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setNavigationOnClickListener(v -> finish());
        taskTitle = findViewById(R.id.thread_task);
        taskMeta = findViewById(R.id.thread_meta);
        banner = findViewById(R.id.thread_banner);
        list = findViewById(R.id.thread_list);
        scroll = findViewById(R.id.thread_scroll);
        input = findViewById(R.id.thread_input);
        askButton = findViewById(R.id.thread_ask);
        noteButton = findViewById(R.id.thread_note);
        suggestButton = findViewById(R.id.thread_suggest);
        suggestions = findViewById(R.id.thread_suggestions);
        suggestBox = findViewById(R.id.thread_suggest_box);

        noteButton.setOnClickListener(v -> send(false));
        askButton.setOnClickListener(v -> send(true));
        suggestButton.setOnClickListener(v -> suggest());
        render();
        TaskSync.now(this);   // fetch the newest notes
    }

    @Override
    protected void onResume() {
        super.onResume();
        render();
    }

    @Override
    protected void onDestroy() {
        io.shutdown();
        super.onDestroy();
    }

    private Task task() {
        return taskId == null ? null : cache.find(taskId);
    }

    private void render() {
        Task t = task();
        if (t == null) {
            Toast.makeText(this, R.string.thread_gone, Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        String me = cache.myId();
        Map<String, String> names = cache.names();
        taskTitle.setText(t.title);
        taskMeta.setText(TaskFormat.meta(this, t, me, names));
        String other = t.counterpart(me);
        if (t.waitingOn(me)) {
            Task.Note q = t.lastNote();
            banner.setText(getString(R.string.thread_waiting_on_you,
                    TaskLists.name(names, q == null ? t.createdBy : q.by)));
            banner.setVisibility(View.VISIBLE);
        } else if (!t.waitingOn.isEmpty()) {
            banner.setText(getString(R.string.thread_waiting_on, TaskLists.name(names, t.waitingOn)));
            banner.setVisibility(View.VISIBLE);
        } else {
            banner.setVisibility(View.GONE);
        }
        noteButton.setText(t.waitingOn(me) ? R.string.thread_answer_button : R.string.thread_add_note);
        askButton.setVisibility(other.isEmpty() ? View.GONE : View.VISIBLE);
        askButton.setText(getString(R.string.thread_ask_name, TaskLists.name(names, other)));

        list.removeAllViews();
        if (t.thread.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText(other.isEmpty() ? R.string.thread_empty_own : R.string.thread_empty);
            empty.setTextColor(getColor(android.R.color.darker_gray));
            empty.setPadding(0, dp(24), 0, 0);
            empty.setGravity(Gravity.CENTER);
            list.addView(empty, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
        }
        for (Task.Note n : t.thread) list.addView(bubble(n, me, names));
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }

    private View bubble(Task.Note n, String me, Map<String, String> names) {
        boolean mine = me.equals(n.by);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundResource(n.ask ? R.drawable.bubble_question : mine ? R.drawable.bubble_mine : R.drawable.bubble_other);
        box.setPadding(dp(12), dp(8), dp(12), dp(8));
        TextView who = new TextView(this);
        String head = (mine ? getString(R.string.thread_me) : TaskLists.name(names, n.by))
                + " · " + TaskFormat.memoTime(n.at) + (n.ask ? " · " + getString(R.string.thread_question) : "")
                + (n.edited ? " · " + getString(R.string.memo_edited) : "");
        who.setText(head);
        who.setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_LabelSmall);
        TextView text = new TextView(this);
        text.setText(n.text);
        text.setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyLarge);
        text.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        text.setTextIsSelectable(!mine);
        box.addView(who);
        box.addView(text);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(8);
        lp.gravity = mine ? Gravity.END : Gravity.START;
        if (mine) {
            lp.setMarginStart(dp(48));
        } else {
            lp.setMarginEnd(dp(48));
        }
        box.setLayoutParams(lp);
        if (mine) {
            box.setOnLongClickListener(v -> {
                editNote(n);
                return true;
            });
        }
        return box;
    }

    private void send(boolean ask) {
        String text = input.getText() == null ? "" : input.getText().toString().trim();
        if (text.isEmpty()) {
            input.setError(getString(R.string.thread_write_first));
            return;
        }
        setBusy(true);
        io.execute(() -> {
            try {
                JSONObject t = TaskApi.addNote(prefs, taskId, text, ask);
                cache.upsert(t);
                main.post(() -> {
                    input.setText("");
                    suggestBox.setVisibility(View.GONE);
                    setBusy(false);
                    render();
                    Jar.notifyState(this);
                    if (ask) Toast.makeText(this, R.string.thread_asked, Toast.LENGTH_SHORT).show();
                });
            } catch (IOException e) {
                main.post(() -> {
                    setBusy(false);
                    Toast.makeText(this, getString(R.string.thread_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void editNote(Task.Note n) {
        TextInputLayout layout = new TextInputLayout(this);
        int pad = dp(20);
        layout.setPadding(pad, pad / 2, pad, 0);
        TextInputEditText field = new TextInputEditText(layout.getContext());
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        field.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        field.setText(n.text);
        layout.addView(field);
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.thread_edit_title)
                .setView(layout)
                .setPositiveButton(R.string.save, (d, w) -> saveEdit(n.id,
                        field.getText() == null ? "" : field.getText().toString().trim()))
                .setNeutralButton(R.string.action_delete, (d, w) -> saveEdit(n.id, ""))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void saveEdit(int noteId, String text) {
        io.execute(() -> {
            try {
                cache.upsert(TaskApi.editNote(prefs, taskId, noteId, text));
                main.post(this::render);
            } catch (IOException e) {
                main.post(() -> Toast.makeText(this, getString(R.string.thread_failed, e.getMessage()),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    /** ✨ The PC's AI suggests a few short replies; tap one to put it in the box (nothing is sent). */
    private void suggest() {
        suggestButton.setEnabled(false);
        suggestButton.setText(R.string.thread_suggesting);
        io.execute(() -> {
            try {
                List<String> replies = TaskApi.suggest(prefs, taskId);
                main.post(() -> {
                    suggestions.removeAllViews();
                    for (String r : replies) {
                        Chip chip = new Chip(this);
                        chip.setText(r);
                        chip.setOnClickListener(v -> {
                            input.setText(r);
                            input.setSelection(r.length());
                        });
                        suggestions.addView(chip);
                    }
                    suggestBox.setVisibility(replies.isEmpty() ? View.GONE : View.VISIBLE);
                    suggestButton.setEnabled(true);
                    suggestButton.setText(R.string.thread_suggest);
                });
            } catch (IOException e) {
                main.post(() -> {
                    suggestButton.setEnabled(true);
                    suggestButton.setText(R.string.thread_suggest);
                    Toast.makeText(this, getString(R.string.thread_failed, e.getMessage()), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void setBusy(boolean busy) {
        askButton.setEnabled(!busy);
        noteButton.setEnabled(!busy);
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }
}
