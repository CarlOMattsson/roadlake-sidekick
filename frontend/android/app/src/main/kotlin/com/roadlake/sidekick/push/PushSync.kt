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
 * Runs [PushRegistrar.sync] where there is a network and a retry: a push event (a new endpoint, an unregistration) is
 * handled in a service that may end at once, so it only records the state and queues this work.
 */
object PushSync {
    private const val WORK = "sidekick-push-sync"

    fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<PushSyncWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** The pairing ended: a registration still waiting to be sent belonged to it. */
    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK)
    }

    class PushSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
        override suspend fun doWork(): Result {
            val registrar = SidekickRuntime.get(applicationContext).push
            return when (withContext(Dispatchers.IO) { registrar.sync() }) {
                SyncOutcome.RETRY -> Result.retry()
                SyncOutcome.DONE -> Result.success()
            }
        }
    }
}
