package com.noam.jar;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.view.View;
import android.widget.RemoteViews;

/**
 * Mic widget: one tap starts a memo, the next tap stops it (the phone's pendant button).
 * A small badge counts memos still waiting to upload; no badge means everything was sent.
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
        v.setViewVisibility(R.id.widget_badge, queued > 0 ? View.VISIBLE : View.GONE);
        v.setTextViewText(R.id.widget_badge, queued > 9 ? "9+" : String.valueOf(queued));
        String desc = rec ? c.getString(R.string.widget_recording)
                : queued == 0 ? c.getString(R.string.widget_tap_to_record)
                : c.getString(R.string.widget_tap_to_record) + " · "
                        + c.getResources().getQuantityString(R.plurals.queued_count, queued, queued);
        v.setContentDescription(R.id.widget_root, desc);

        Intent tap = new Intent(c, RecordActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        v.setOnClickPendingIntent(R.id.widget_root, PendingIntent.getActivity(c, 0, tap,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        return v;
    }
}
