package com.noam.jar;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

/**
 * Home-screen widget: one tap starts a memo, another tap stops it — the
 * phone's version of the pendant button. It also shows how many memos wait.
 */
public final class JarWidget extends AppWidgetProvider {

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) manager.updateAppWidget(id, views(context));
    }

    public static void updateAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, JarWidget.class));
        if (ids.length > 0) m.updateAppWidget(ids, views(c));
    }

    private static RemoteViews views(Context c) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_jar);
        boolean rec = RecorderService.isRecording();
        int queued = Jar.queue(c).readyCount();

        v.setImageViewResource(R.id.widget_icon, rec ? R.drawable.ic_widget_stop : R.drawable.ic_widget_mic);
        v.setInt(R.id.widget_button, "setBackgroundResource",
                rec ? R.drawable.widget_button_recording : R.drawable.widget_button);
        v.setTextViewText(R.id.widget_title,
                c.getString(rec ? R.string.widget_recording : R.string.widget_tap_to_record));
        v.setTextViewText(R.id.widget_subtitle, queued == 0
                ? c.getString(R.string.widget_all_sent)
                : c.getResources().getQuantityString(R.plurals.queued_count, queued, queued));

        Intent tap = new Intent(c, RecordActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        v.setOnClickPendingIntent(R.id.widget_root, PendingIntent.getActivity(c, 0, tap,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        return v;
    }
}
