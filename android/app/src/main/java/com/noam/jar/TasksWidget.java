package com.noam.jar;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.view.View;
import android.widget.RemoteViews;

import com.noam.jar.core.Task;
import com.noam.jar.core.TaskLists;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * Tasks widget: requests waiting for my OK, my open tasks and messages to send, and what Jar did
 * with the last memo. Tick a task done, accept a request or send a message right from the home
 * screen. Works offline from the phone's copy; changes go to the PC on the next sync.
 */
public final class TasksWidget extends AppWidgetProvider {
    static final String REFRESH = "com.noam.jar.WIDGET_REFRESH";
    static final int MAX_ITEMS = 30;

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) m.updateAppWidget(id, views(c, id));
        m.notifyAppWidgetViewDataChanged(ids, R.id.tw_list);
    }

    @Override
    public void onReceive(Context c, Intent intent) {
        super.onReceive(c, intent);
        if (REFRESH.equals(intent.getAction())) {
            TaskSync.now(c);
            updateAll(c);
        }
    }

    public static void updateAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, TasksWidget.class));
        if (ids.length == 0) return;
        for (int id : ids) m.updateAppWidget(id, views(c, id));
        m.notifyAppWidgetViewDataChanged(ids, R.id.tw_list);
    }

    static List<Task> items(Context c) {
        TaskCache cache = new TaskCache(c);
        return TaskLists.forWidget(cache.tasks(), cache.myId(), cache.iAmParent(), MAX_ITEMS);
    }

    private static RemoteViews views(Context c, int widgetId) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_tasks);
        TaskCache cache = new TaskCache(c);
        Prefs prefs = new Prefs(c);
        String me = cache.myId();
        String name = cache.myName();

        int open = TaskLists.openCount(cache.tasks(), me);
        v.setTextViewText(R.id.tw_title, name.isEmpty() ? c.getString(R.string.tasks_title)
                : c.getString(R.string.widget_title_for, name, open));
        String status = prefs.token().isEmpty() ? c.getString(R.string.widget_not_paired)
                : !prefs.taskProblem().isEmpty() ? prefs.taskProblem()
                : TaskFormat.syncedAgo(c, cache.syncedAt());
        int queued = Jar.queue(c).readyCount();
        if (queued > 0) status += " · " + c.getResources().getQuantityString(R.plurals.queued_count, queued, queued);
        v.setTextViewText(R.id.tw_status, status);
        v.setTextViewText(R.id.tw_last_memo, lastMemoLine(c, cache.lastMemo()));
        v.setViewVisibility(R.id.tw_last_memo, cache.lastMemo().length() == 0 ? View.GONE : View.VISIBLE);

        // The list's rows come from TasksWidgetService; a different data URI per widget keeps them apart.
        Intent svc = new Intent(c, TasksWidgetService.class)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        svc.setData(Uri.parse(svc.toUri(Intent.URI_INTENT_SCHEME)));
        v.setRemoteAdapter(R.id.tw_list, svc);
        v.setEmptyView(R.id.tw_list, R.id.tw_empty);

        // Rows fill in which task and what to do; an invisible screen does it and closes.
        Intent act = new Intent(c, WidgetActionActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        v.setPendingIntentTemplate(R.id.tw_list, PendingIntent.getActivity(c, 1, act,
                PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));

        Intent openApp = new Intent(c, TasksActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent openPi = PendingIntent.getActivity(c, 2, openApp,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        v.setOnClickPendingIntent(R.id.tw_title, openPi);
        v.setOnClickPendingIntent(R.id.tw_empty, openPi);
        Intent memos = new Intent(c, MemosActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        v.setOnClickPendingIntent(R.id.tw_last_memo, PendingIntent.getActivity(c, 3, memos,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        Intent refresh = new Intent(c, TasksWidget.class).setAction(REFRESH);
        v.setOnClickPendingIntent(R.id.tw_refresh, PendingIntent.getBroadcast(c, 4, refresh,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        return v;
    }

    /** "Last memo 12:40: task “call the plumber” · email draft …" */
    static String lastMemoLine(Context c, JSONObject m) {
        if (m.length() == 0) return "";
        String when = TaskFormat.memoTime(m.optString("recorded_at"));
        String st = m.optString("status");
        if (!"done".equals(st)) {
            return c.getString(R.string.widget_last_memo, when, c.getString("failed".equals(st)
                    ? R.string.widget_memo_failed : R.string.memo_in_progress));
        }
        JSONArray acts = m.optJSONArray("actions");
        StringBuilder b = new StringBuilder();
        for (int i = 0; acts != null && i < acts.length(); i++) {
            if (b.length() > 0) b.append(" · ");
            b.append(acts.optString(i));
        }
        if (b.length() == 0) b.append(m.optString("summary", ""));
        return c.getString(R.string.widget_last_memo, when, b.toString());
    }
}
