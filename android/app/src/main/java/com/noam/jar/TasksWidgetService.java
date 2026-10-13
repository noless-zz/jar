package com.noam.jar;

import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import com.noam.jar.core.Task;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Rows of the tasks widget, read from the phone's copy of the task list. */
public final class TasksWidgetService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Rows(getApplicationContext());
    }

    static final class Rows implements RemoteViewsFactory {
        private final Context c;
        private List<Task> items = new ArrayList<>();
        private String me = "";
        private Map<String, String> names;

        Rows(Context c) {
            this.c = c;
        }

        @Override public void onCreate() { }

        @Override
        public void onDataSetChanged() {
            TaskCache cache = new TaskCache(c);
            me = cache.myId();
            names = cache.names();
            items = TasksWidget.items(c);
        }

        @Override public void onDestroy() { items.clear(); }

        @Override public int getCount() { return items.size(); }

        @Override
        public RemoteViews getViewAt(int pos) {
            RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_task_item);
            if (pos >= items.size()) return v;
            Task t = items.get(pos);
            String title = t.title;
            String action;
            int icon;
            if (t.waitingOn(me)) {
                action = "open";
                icon = R.drawable.ic_widget_ok;
                Task.Note n = t.lastNote();
                title = "❓ " + t.title + (n == null ? "" : ": " + n.text);
            } else if (t.isRequested()) {
                action = "accept";
                icon = R.drawable.ic_widget_ok;
                title = c.getString(R.string.widget_asks, com.noam.jar.core.TaskLists.name(names, t.createdBy), t.title);
            } else if (t.isMessage()) {
                action = "send";
                icon = R.drawable.ic_widget_send;
            } else {
                action = "done";
                icon = R.drawable.ic_widget_check;
            }
            v.setTextViewText(R.id.twi_title, title);
            String meta = TaskFormat.meta(c, t, me, names);
            if (TaskFormat.overdue(t)) meta = "⚠ " + meta;
            if (t.coins > 0 && !t.isMessage()) meta = meta.isEmpty() ? "🪙 " + t.coins : "🪙 " + t.coins + " · " + meta;
            v.setTextViewText(R.id.twi_meta, meta);
            v.setImageViewResource(R.id.twi_action, icon);
            v.setContentDescription(R.id.twi_action, c.getString("accept".equals(action) ? R.string.action_accept
                    : "send".equals(action) ? R.string.send_whatsapp : R.string.action_done));
            v.setOnClickFillInIntent(R.id.twi_action, new Intent()
                    .putExtra(WidgetActionActivity.EXTRA_ID, t.id)
                    .putExtra(WidgetActionActivity.EXTRA_DO, action));
            v.setOnClickFillInIntent(R.id.twi_text, new Intent()
                    .putExtra(WidgetActionActivity.EXTRA_ID, t.id)
                    .putExtra(WidgetActionActivity.EXTRA_DO, "open"));
            return v;
        }

        @Override public RemoteViews getLoadingView() { return null; }

        @Override public int getViewTypeCount() { return 1; }

        @Override
        public long getItemId(int pos) {
            return pos < items.size() ? items.get(pos).id.hashCode() : pos;
        }

        @Override public boolean hasStableIds() { return true; }
    }
}
