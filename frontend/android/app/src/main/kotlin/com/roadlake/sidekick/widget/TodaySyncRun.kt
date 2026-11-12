package com.roadlake.sidekick.widget

import com.roadlake.sidekick.companion.RenewalOutcome
import com.roadlake.sidekick.companion.TokenRenewal
import com.roadlake.sidekick.today.SyncResult
import com.roadlake.sidekick.today.TodayRepository

/**
 * The work of one [TodaySync.TodaySyncWorker] run, free of Android types so the order of its steps is tested on the JVM:
 * the credential is renewed first when its date has come (cheap otherwise), then the queued completions are sent and
 * Today is read with whichever credential is current.
 */
class TodaySyncRun(private val renewal: TokenRenewal, private val repository: TodayRepository, private val staleAfterMillis: Long) {
    /**
     * A renewal that fails must not stop Today; it has its own pause and tries again at a later run. When its request may
     * have reached the server the old token is valid only minutes more, so [scheduleRenewalRetry] asks for an early run.
     * Returns how Today's read ended, or null when [onlyIfStale] found it fresh and nothing queued.
     */
    fun run(onlyIfStale: Boolean, scheduleRenewalRetry: () -> Unit): SyncResult? {
        if (runCatching { renewal.run() }.getOrNull() == RenewalOutcome.RETRY_SOON) scheduleRenewalRetry()
        return if (onlyIfStale) repository.syncIfStale(staleAfterMillis) else repository.sync()
    }
}
