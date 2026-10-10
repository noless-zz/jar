package com.noam.jar;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.text.DateFormat;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * My recent memos: what Jar heard and what it did. Tap one to fix the words (a misheard name,
 * a wrong day) and file it again; the tasks it made last time are replaced.
 */
public final class MemosActivity extends AppCompatActivity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final List<JSONObject> memos = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    private Prefs prefs;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_memos);
        prefs = new Prefs(this);
        MaterialToolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setNavigationOnClickListener(v -> finish());
        toolbar.setOnMenuItemClickListener(item -> {
            load();
            return true;
        });
        status = findViewById(R.id.memos_status);
        RecyclerView list = findViewById(R.id.memos_list);
        list.setLayoutManager(new LinearLayoutManager(this));
        list.setAdapter(adapter);
        load();
    }

    @Override
    protected void onDestroy() {
        io.shutdown();
        super.onDestroy();
    }

    private void load() {
        status.setText(R.string.syncing);
        status.setVisibility(View.VISIBLE);
        io.execute(() -> {
            try {
                JSONArray arr = TaskApi.memos(prefs).optJSONArray("memos");
                List<JSONObject> got = new ArrayList<>();
                for (int i = 0; arr != null && i < arr.length(); i++) got.add(arr.getJSONObject(i));
                main.post(() -> {
                    memos.clear();
                    memos.addAll(got);
                    adapter.notifyDataSetChanged();
                    status.setText(R.string.memos_empty);
                    status.setVisibility(got.isEmpty() ? View.VISIBLE : View.GONE);
                });
            } catch (IOException | org.json.JSONException e) {
                main.post(() -> status.setText(getString(R.string.memos_failed, e.getMessage())));
            }
        });
    }

    private void edit(JSONObject m) {
        TextInputLayout layout = new TextInputLayout(this);
        layout.setHint(getString(R.string.memo_edit_hint));
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad / 2, pad, 0);
        TextInputEditText text = new TextInputEditText(layout.getContext());
        text.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        text.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        text.setMinLines(3);
        text.setText(m.optString("transcript"));
        layout.addView(text);
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.memo_edit_title)
                .setMessage(R.string.memo_edit_message)
                .setView(layout)
                .setPositiveButton(R.string.memo_save_refile, (d, w) -> {
                    String t = text.getText() == null ? "" : text.getText().toString().trim();
                    if (!t.isEmpty()) refile(m.optString("id"), t);
                })
                .setNeutralButton(R.string.memo_refile_as_is, (d, w) -> refile(m.optString("id"), null))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void refile(String id, String transcript) {
        io.execute(() -> {
            try {
                TaskApi.refile(prefs, id, transcript);
                main.post(() -> {
                    Toast.makeText(this, R.string.memo_refiled, Toast.LENGTH_LONG).show();
                    TaskSync.soon(this);       // the corrected tasks show up on the list shortly
                    load();
                });
            } catch (IOException e) {
                main.post(() -> Toast.makeText(this, getString(R.string.memos_failed, e.getMessage()),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    private String when(String iso) {
        try {
            SimpleDateFormat in = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);
            in.setTimeZone(TimeZone.getTimeZone("UTC"));
            Date d = in.parse(iso.replace("Z", ""));
            return DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(d);
        } catch (Exception e) {
            return iso;
        }
    }

    final class Adapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
        @Override
        public int getItemCount() {
            return memos.size();
        }

        @NonNull
        @Override
        public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int type) {
            return new RecyclerView.ViewHolder(LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_memo, parent, false)) { };
        }

        @Override
        public void onBindViewHolder(@NonNull RecyclerView.ViewHolder h, int pos) {
            JSONObject m = memos.get(pos);
            TextView meta = h.itemView.findViewById(R.id.memo_meta);
            TextView text = h.itemView.findViewById(R.id.memo_text);
            TextView did = h.itemView.findViewById(R.id.memo_actions);
            String st = m.optString("status");
            String line = when(m.optString("recorded_at"));
            if (!"done".equals(st)) line += " · " + getString(R.string.memo_in_progress);
            if (m.optBoolean("edited")) line += " · " + getString(R.string.memo_edited);
            meta.setText(line);
            String t = m.optString("transcript");
            text.setText(t.isEmpty() || "null".equals(t) ? getString(R.string.memo_no_text) : t);
            JSONArray acts = m.optJSONArray("actions");
            StringBuilder sb = new StringBuilder();
            for (int i = 0; acts != null && i < acts.length(); i++) {
                if (sb.length() > 0) sb.append('\n');
                sb.append("• ").append(acts.optString(i));
            }
            did.setText(sb);
            did.setVisibility(sb.length() == 0 ? View.GONE : View.VISIBLE);
            h.itemView.setOnClickListener(v -> {
                if (!t.isEmpty() && !"null".equals(t)) edit(m);
            });
        }
    }
}
