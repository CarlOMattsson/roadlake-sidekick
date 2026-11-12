package com.roadlake.sidekick.widget

import android.content.Context
import androidx.glance.appwidget.updateAll
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.roadlake.sidekick.SidekickRuntime
import com.roadlake.sidekick.companion.TokenRenewal
import com.roadlake.sidekick.today.SyncResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * When Today is read and the outbox is sent. The widget is refreshed
 *
 * - every 30 minutes by WorkManager (inexact: the system batches it, and it waits for a network),
 * - when the app comes to the foreground and after the page completed a Task ([requestSync]),
 * - once the undo window of a tap on a circle has passed, to send the completion ([scheduleHeldSend]), and again with
 *   back-off while the server cannot be reached, with the same idempotency key,
 * - when a wake push arrives ([com.roadlake.sidekick.push.SidekickPushService], D-078).
 *
 * Every run first lets [com.roadlake.sidekick.companion.TokenRenewal] renew the device credential when it is due, so app start,
 * resume and the periodic job all keep the pairing alive.
 */
object TodaySync {
    private const val PERIODIC = "sidekick-today-periodic"
    private const val ONCE = "sidekick-today-sync"
    private const val RENEWAL_RETRY = "sidekick-renewal-retry"
    private const val HELD_SEND = "sidekick-held-send"
    private const val HELD_REDRAW = "sidekick-held-redraw"
    private const val KEY_ONLY_IF_STALE = "only_if_stale"
    private const val PERIOD_MINUTES = 30L
    private const val STALE_AFTER_MILLIS = 60_000L
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val needsNetwork = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** Keeps the 30-minute refresh scheduled; calling it again changes nothing. */
    fun schedulePeriodic(context: Context) {
        val request = PeriodicWorkRequestBuilder<TodaySyncWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
            .setConstraints(needsNetwork)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun cancelPeriodic(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
    }

    /**
     * A pairing started or ended: syncs and renewal retries that were queued for the old one are dropped (a run that is
     * already going is stopped by the pairing generation, not by this). The caller queues the new pairing's own sync.
     */
    fun cancelQueued(context: Context) {
        val work = WorkManager.getInstance(context)
        work.cancelUniqueWork(ONCE)
        work.cancelUniqueWork(RENEWAL_RETRY)
    }

    /** Sends queued completions and reads Today now (as soon as a network exists). Several calls queue up in order. */
    fun requestSync(context: Context, onlyIfStale: Boolean = false) {
        val request = OneTimeWorkRequestBuilder<TodaySyncWorker>()
            .setConstraints(needsNetwork)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .setInputData(workDataOf(KEY_ONLY_IF_STALE to onlyIfStale))
            .build()
        WorkManager.getInstance(context)
            .enqueueUniqueWork(ONCE, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /**
     * A completion was ticked in the widget and waits out its undo window ([delayMillis]) in the outbox. When the window
     * has passed the outbox is drained (as soon as a network exists), and the widget is redrawn whether or not there is a
     * network, so "Done · Undo" never outlives the window. Each tap has its own pair, in order.
     */
    fun scheduleHeldSend(context: Context, delayMillis: Long) {
        val work = WorkManager.getInstance(context)
        val send = OneTimeWorkRequestBuilder<TodaySyncWorker>()
            .setInitialDelay(delayMillis, TimeUnit.MILLISECONDS)
            .setConstraints(needsNetwork)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .setInputData(workDataOf(KEY_ONLY_IF_STALE to false))
            .build()
        work.enqueueUniqueWork(HELD_SEND, ExistingWorkPolicy.APPEND_OR_REPLACE, send)
        val redraw = OneTimeWorkRequestBuilder<TodayRedrawWorker>().setInitialDelay(delayMillis, TimeUnit.MILLISECONDS).build()
        work.enqueueUniqueWork(HELD_REDRAW, ExistingWorkPolicy.APPEND_OR_REPLACE, redraw)
    }

    /**
     * A renewal whose request may have reached the server is asked again within the old token's short grace time, also
     * with the app in the background. A periodic job runs only every 15 minutes at best, so this is a one-time job with a
     * short delay; it runs [TodaySyncWorker], whose first step is the renewal.
     */
    fun scheduleRenewalRetry(context: Context) {
        val request = OneTimeWorkRequestBuilder<TodaySyncWorker>()
            .setInitialDelay(TokenRenewal.QUICK_RETRY_DELAY_MILLIS, TimeUnit.MILLISECONDS)
            .setConstraints(needsNetwork)
            .setInputData(workDataOf(KEY_ONLY_IF_STALE to true))
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(RENEWAL_RETRY, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** The app came to the foreground: read again unless Today was read a moment ago. */
    fun onAppForeground(context: Context) = requestSync(context, onlyIfStale = true)

    /** Redraws every Today widget from what is stored, without any network. */
    fun redraw(context: Context) {
        val app = context.applicationContext
        TodayWidgetBus.changed()
        scope.launch { TodayWidget().updateAll(app) }
    }

    /** The pairing started or ended: the widget shows "connect" or reads Today for the new pairing. */
    fun onPairingChanged(context: Context) {
        val app = context.applicationContext
        redraw(app)
        requestSync(app)
    }

    internal fun staleAfterMillis() = STALE_AFTER_MILLIS

    /** Draws the widget again from what is stored, with no network: the end of an undo window. */
    class TodayRedrawWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
        override suspend fun doWork(): Result {
            TodayWidgetBus.changed()
            TodayWidget().updateAll(applicationContext)
            return Result.success()
        }
    }

    class TodaySyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
        override suspend fun doWork(): Result {
            val runtime = SidekickRuntime.get(applicationContext)
            val onlyIfStale = inputData.getBoolean(KEY_ONLY_IF_STALE, false)
            val outcome = withContext(Dispatchers.IO) {
                TodaySyncRun(runtime.renewal, runtime.today, STALE_AFTER_MILLIS)
                    .run(onlyIfStale) { scheduleRenewalRetry(applicationContext) }
            }
            runtime.outboxRan()
            // A run that came before a hold ended (an early sync) leaves its completion queued: come back when it ends.
            withContext(Dispatchers.IO) { runtime.today.nextSendAtMillis() }?.let {
                scheduleHeldSend(applicationContext, (it - System.currentTimeMillis()).coerceAtLeast(0L))
            }
            TodayWidgetBus.changed()
            TodayWidget().updateAll(applicationContext)
            return if (outcome == SyncResult.RETRY) Result.retry() else Result.success()
        }
    }
}
