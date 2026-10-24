package com.noam.jar;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
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
        for (int id : ids) m.updateAppWidget(id, views(c, m, id));
    }

    /** Resized on the home screen: as many rows as fit now. */
    @Override
    public void onAppWidgetOptionsChanged(Context c, AppWidgetManager m, int id, Bundle options) {
        m.updateAppWidget(id, views(c, m, id));
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
        for (int id : ids) m.updateAppWidget(id, views(c, m, id));
    }

    static List<Task> items(Context c) {
        TaskCache cache = new TaskCache(c);
        return TaskLists.forWidget(cache.tasks(), cache.myId(), cache.iAmParent(), MAX_ITEMS);
    }

    /** Drawn in the person's look (WidgetBuilder), at the size it has on the home screen (portrait: min width, max height). */
    private static RemoteViews views(Context c, AppWidgetManager m, int id) {
        Bundle o = m.getAppWidgetOptions(id);
        int w = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 0);
        int h = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 0);
        return WidgetBuilder.build(c, w > 0 ? w : 300, h > 0 ? h : 260);
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
