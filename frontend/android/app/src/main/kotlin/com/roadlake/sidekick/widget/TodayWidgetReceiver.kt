package com.roadlake.sidekick.widget

import android.content.Context
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver

/** The system's entry to the Today widget: updates, resizes and the first/last widget being placed or removed. */
class TodayWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = TodayWidget()

    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        TodaySync.schedulePeriodic(context)
        TodaySync.requestSync(context)
    }

    override fun onUpdate(context: Context, appWidgetManager: android.appwidget.AppWidgetManager, appWidgetIds: IntArray) {
        super.onUpdate(context, appWidgetManager, appWidgetIds)
        // After a reboot or an app update the schedule is re-asserted; KEEP makes this free when it already exists.
        TodaySync.schedulePeriodic(context)
    }

    /** A resize: draw from the cache at once, so the new size does not keep the old layout until the next sync. */
    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: android.appwidget.AppWidgetManager,
        appWidgetId: Int,
        newOptions: android.os.Bundle,
    ) {
        super.onAppWidgetOptionsChanged(context, appWidgetManager, appWidgetId, newOptions)
        TodaySync.redraw(context)
    }

    override fun onDisabled(context: Context) {
        TodaySync.cancelPeriodic(context)
        super.onDisabled(context)
    }
}
