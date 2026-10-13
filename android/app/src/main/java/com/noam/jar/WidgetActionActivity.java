package com.noam.jar;

import android.app.Activity;
import android.content.Intent;
import android.widget.Toast;

/**
 * Invisible screen behind the tasks widget's rows: ticks a task done or accepts a request
 * and closes at once, or opens the app for "send" (WhatsApp) and "open" (the task's actions).
 */
public final class WidgetActionActivity extends Activity {
    static final String EXTRA_ID = "task_id";
    static final String EXTRA_DO = "do";

    @Override
    protected void onResume() {
        super.onResume();
        Intent in = getIntent();
        String id = in.getStringExtra(EXTRA_ID);
        String what = in.getStringExtra(EXTRA_DO);
        if (id != null && what != null) {
            switch (what) {
                case "done":
                case "accept":
                    TaskReceiver.apply(this, id, what, null);
                    Toast.makeText(this, "done".equals(what) ? R.string.widget_marked_done
                            : R.string.widget_accepted, Toast.LENGTH_SHORT).show();
                    break;
                case "send":
                    startActivity(new Intent(this, TasksActivity.class)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                            .putExtra(TasksActivity.EXTRA_SEND, id));
                    break;
                default:
                    startActivity(new Intent(this, TasksActivity.class)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                            .putExtra(TasksActivity.EXTRA_OPEN, id));
            }
        }
        finish();
        overridePendingTransitionCompat();
    }

    @SuppressWarnings("deprecation")
    private void overridePendingTransitionCompat() {
        overridePendingTransition(0, 0);
    }
}
