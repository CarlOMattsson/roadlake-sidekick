package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.HttpCall
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.companion.HttpTransport
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStore
import java.io.IOException

class MemoryTextStore : TextStore {
    var text: String? = null
    var failWrites = false
    var failReads = false
    var writes = 0

    override fun read(): String? {
        if (failReads) throw IOException("read error")
        return text
    }

    override fun write(text: String) {
        if (failWrites) throw IOException("disk full")
        writes++
        this.text = text
    }

    override fun delete() {
        text = null
    }

    var quarantined: String? = null
    var failQuarantine = false

    override fun quarantine() {
        if (failQuarantine) throw IOException("cannot move")
        quarantined = text
        text = null
    }
}

class MemoryPairingStore(var pairing: Pairing? = Pairing("https://sidekick.example", "rsc_abcdefghijklmnopqrstuvwxyz0123456789", "Pixel")) :
    PairingStore {
    override fun load() = pairing

    override fun save(pairing: Pairing) {
        this.pairing = pairing
    }

    override fun clear() {
        pairing = null
    }
}

/** Answers calls from a script; a [Throwable] entry is "no answer came" (a [CompanionException]). */
class ScriptedHttp : HttpTransport {
    val calls = mutableListOf<HttpCall>()
    private val handlers = mutableListOf<(HttpCall) -> Any?>()

    /** The newest handler is asked first; a handler that returns null passes the call on. */
    fun on(handler: (HttpCall) -> Any?) {
        handlers.add(0, handler)
    }

    override fun execute(call: HttpCall): HttpResult {
        calls += call
        for (handler in handlers) {
            val answer = handler(call) ?: continue
            if (answer is CompanionException) throw answer
            return answer as HttpResult
        }
        error("no scripted answer for ${call.method} ${call.url}")
    }

    fun posts() = calls.filter { it.method == "POST" }
}

/** The pieces of a TodayRepository over fakes, with the same wiring the app uses: a 401 ends up in clearAll. */
class Harness(paired: Boolean = true) {
    val pairing = MemoryPairingStore(if (paired) MemoryPairingStore().pairing else null)
    val cacheText = MemoryTextStore()
    val outboxText = MemoryTextStore()
    val http = ScriptedHttp()
    var now = 1_000_000L
    val cache = TodayCache(cacheText)
    val outbox = Outbox(outboxText) { now }
    var keys = 0
    val generation = PairingGeneration()
    val clearing = ClearingPairingStore(pairing, {
        cache.clear()
        outbox.clear()
    }, {}, generation)
    val client = CompanionClient(clearing, http, allowLocalCleartext = false, generation = generation)
    val repo = TodayRepository(client, cache, outbox, { now }, { "widget-key-${++keys}" }, generation)
}
