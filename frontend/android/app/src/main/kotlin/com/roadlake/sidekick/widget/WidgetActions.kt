package com.roadlake.sidekick.widget

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.glance.GlanceId
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.ActionCallback
import com.roadlake.sidekick.SidekickRuntime
import com.roadlake.sidekick.today.EnqueueResult
import com.roadlake.sidekick.today.TodayRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The circle of a row. The tap only writes the completion to the durable outbox, held for the undo window
 * ([TodayRepository.UNDO_WINDOW_MILLIS]), and redraws the row as "Done · Undo"; the request itself is sent by
 * [TodaySync] after the window (a callback of a widget has seconds, not a network timeout), and the row is redrawn when
 * the window has passed. A second tap on a queued row is not offered (the row has no circle), and the outbox holds one
 * entry per Task if it were.
 */
class CompleteTaskAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val taskId = parameters[TASK_ID] ?: return
        val result = withContext(Dispatchers.IO) {
            SidekickRuntime.get(context).today.enqueueCompletion(taskId, TodayRepository.UNDO_WINDOW_MILLIS)
        }
        TodayWidgetBus.changed()
        TodayWidget().update(context, glanceId)
        when (result) {
            EnqueueResult.QUEUED -> TodaySync.scheduleHeldSend(context, TodayRepository.UNDO_WINDOW_MILLIS)
            EnqueueResult.UNKNOWN_TASK -> TodaySync.requestSync(context)
            else -> Unit
        }
    }
}

/**
 * "Done · Undo" on a row inside its undo window: takes the completion back out of the outbox. It was not sent, so there is
 * nothing to undo on the server; if the window has just ended the call finds nothing to take back and the row simply
 * shows what it now is (sending).
 */
class UndoCompletionAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val taskId = parameters[TASK_ID] ?: return
        withContext(Dispatchers.IO) { SidekickRuntime.get(context).today.undoCompletion(taskId) }
        TodayWidgetBus.changed()
        TodayWidget().update(context, glanceId)
    }
}

/**
 * The refresh glyph in the header. With no network the sync would wait for one without a word, so the widget says
 * "Offline" at once (the cached list and its sync time stay); the sync is still queued and clears it when it gets through.
 */
class RefreshTodayAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        if (!hasNetwork(context)) {
            withContext(Dispatchers.IO) { SidekickRuntime.get(context).today.markOffline() }
            TodayWidgetBus.changed()
            TodayWidget().update(context, glanceId)
        }
        TodaySync.requestSync(context)
    }

    private fun hasNetwork(context: Context): Boolean {
        val manager = context.getSystemService(ConnectivityManager::class.java) ?: return true
        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork ?: return false) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }
}
