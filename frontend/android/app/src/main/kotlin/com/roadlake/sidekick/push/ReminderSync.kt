package com.roadlake.sidekick.push

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.roadlake.sidekick.SidekickRuntime
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * Runs [ReminderFlow.run] where there is a network and a retry. A push message (`{"k":"r"}`) arrives in a service that
 * may end at once, so it only queues this work. Several messages queue up in order; each run is idempotent (the
 * reminders are shown under their own ids and acknowledged).
 */
object ReminderSync {
    private const val WORK = "sidekick-reminders"

    fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<ReminderWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** The pairing ended: reminders still waiting to be fetched belonged to it. */
    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK)
    }

    class ReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
        override suspend fun doWork(): Result {
            val flow = SidekickRuntime.get(applicationContext).reminders
            return when (withContext(Dispatchers.IO) { flow.run() }) {
                SyncOutcome.RETRY -> Result.retry()
                SyncOutcome.DONE -> Result.success()
            }
        }
    }
}
