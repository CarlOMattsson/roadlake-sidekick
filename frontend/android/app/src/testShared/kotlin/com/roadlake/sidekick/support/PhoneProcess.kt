package com.roadlake.sidekick.support

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStore
import com.roadlake.sidekick.companion.RenewalApi
import com.roadlake.sidekick.companion.TokenRenewal
import com.roadlake.sidekick.companion.UrlConnectionTransport
import com.roadlake.sidekick.today.ClearingPairingStore
import com.roadlake.sidekick.today.Outbox
import com.roadlake.sidekick.today.TextStore
import com.roadlake.sidekick.today.TodayCache
import com.roadlake.sidekick.today.TodayRepository
import com.roadlake.sidekick.widget.TodaySyncRun

/**
 * One run of the app's process: the same objects `SidekickRuntime` builds, over the app's own transport and the given
 * stores, without Android's `Context`. A restart is a new [PhoneProcess] over the same [pairings] and the same
 * [textStore] names: everything held in memory is gone, everything that was written is read back.
 *
 * [widgetRedraws] counts what `TodaySync.onPairingChanged` does in the app (the widget redraws at every start and end of
 * a pairing); [pairingLosses] counts the page being told about a 401.
 */
class PhoneProcess(pairings: PairingStore, textStore: (String) -> TextStore, val now: () -> Long) {
    var widgetRedraws = 0
        private set
    var pairingLosses = 0
        private set

    val generation = PairingGeneration()
    val cache = TodayCache(textStore("today-cache.json"))
    val outbox = Outbox(textStore("outbox.json"), clock = now)
    private val renewalNote = textStore("renewal.json")

    val store = ClearingPairingStore(
        delegate = pairings,
        clearLocalData = {
            cache.clear()
            outbox.clear()
            renewal.clearLocal()
        },
        changed = { widgetRedraws++ },
        generation = generation,
    )

    val client = CompanionClient(
        store = store,
        http = UrlConnectionTransport(connectTimeoutMs = 2_000, readTimeoutMs = 2_000),
        allowLocalCleartext = true,
        onPairingLost = { pairingLosses++ },
        clock = now,
        generation = generation,
    )

    val renewal: TokenRenewal = TokenRenewal(store, RenewalApi { client.renew() }, renewalNote, generation, now)
    val today = TodayRepository(client, cache, outbox, now, generation = generation)
    val syncRun = TodaySyncRun(renewal, today, staleAfterMillis = 60_000L)
}
