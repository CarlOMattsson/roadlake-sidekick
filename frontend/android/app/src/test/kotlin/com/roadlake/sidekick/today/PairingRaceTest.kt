package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStore
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

private const val SECRET = "rspair_abcdefghijklmnopqrstuvwxyz012345"
private const val ORIGIN = "https://sidekick.example"
private val EXISTING = Pairing(ORIGIN, "rsc_abcdefghijklmnopqrstuvwxyz0123456789", "Pixel", "2026-11-01T10:00:00Z")

/**
 * The pre-check before a pairing code is spent must never remove a pairing that exists: the check for a pairing and the wipe
 * are one step under the pairing lock, the same lock that guards the save.
 */
class PairingRaceTest {
    private val record = MemoryPairingStore(EXISTING)
    private val cacheText = MemoryTextStore().apply { text = """{"titles":["Call the dentist"]}""" }
    private val outboxText = MemoryTextStore().apply { text = """[{"task":"t1"}]""" }
    private val generation = PairingGeneration()

    private fun store() = ClearingPairingStore(
        record,
        clearLocalData = { runAllOrThrow({ cacheText.text = null }, { outboxText.text = null }) },
        changed = {},
        generation = generation,
    )

    private fun body(token: String) = JSONObject().put("access_token", token).put("device", JSONObject().put("label", "Samsung")).toString()

    private fun assertExistingPairingIntact() {
        assertEquals(EXISTING.token, record.pairing?.token)
        assertNotNull(cacheText.text)
        assertNotNull(outboxText.text)
    }

    private fun code(block: () -> Unit): String = try {
        block()
        fail("expected a CompanionException")
        ""
    } catch (e: CompanionException) {
        e.code
    }

    /** A store whose first [load] answers "unpaired": the client looked before another attempt saved its pairing. */
    private fun staleFirstLoad(clearing: ClearingPairingStore): PairingStore {
        var first = true
        return object : PairingStore by clearing {
            override fun load(): Pairing? {
                if (first) {
                    first = false
                    return null
                }
                return clearing.load()
            }
        }
    }

    @Test
    fun readyForPairingRefusesAndKeepsAnExistingPairing() {
        val store = store()

        assertEquals("already_paired", code { store.readyForPairing() })

        assertExistingPairingIntact()
        assertEquals(0L, generation.current()) // background work of the existing pairing is not refused either
    }

    @Test
    fun aPairingThatAppearsAfterTheClientLookedIsNotWiped() {
        val http = ScriptedHttp()
        val client = CompanionClient(staleFirstLoad(store()), http, allowLocalCleartext = false, generation = generation)

        assertEquals("already_paired", code { client.pair(ORIGIN, SECRET) })

        assertExistingPairingIntact()
        assertTrue(http.calls.isEmpty()) // the code was not spent
    }

    @Test
    fun anInvalidCodeNeverRemovesAnExistingPairing() {
        val http = ScriptedHttp()
        val client = CompanionClient(staleFirstLoad(store()), http, allowLocalCleartext = false, generation = generation)

        assertEquals("invalid_pairing_secret", code { client.pair(ORIGIN, "short") })
        assertExistingPairingIntact()

        val again = CompanionClient(staleFirstLoad(store()), http, allowLocalCleartext = false, generation = generation)
        assertEquals("invalid_server_url", code { again.pair("http://sidekick.example", SECRET) })
        assertExistingPairingIntact()
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun twoConcurrentPairingsKeepExactlyOne() {
        repeat(50) { round ->
            record.pairing = null
            cacheText.text = null
            outboxText.text = null
            val clearing = store()
            val tokenA = "rsc_" + "a".repeat(36)
            val tokenB = "rsc_" + "b".repeat(36)
            val clients = listOf(tokenA, tokenB).map { token ->
                val http = ScriptedHttp().apply {
                    on { call -> if (call.method == "POST") HttpResult(201, body(token)) else HttpResult(204, "") }
                }
                CompanionClient(clearing, http, allowLocalCleartext = false, generation = generation)
            }
            val start = CountDownLatch(1)
            val succeeded = AtomicInteger()
            val refused = AtomicInteger()
            val pool = Executors.newFixedThreadPool(2)
            try {
                val futures = clients.map { client ->
                    pool.submit {
                        start.await()
                        try {
                            client.pair(ORIGIN, SECRET)
                            succeeded.incrementAndGet()
                        } catch (e: CompanionException) {
                            if (e.code == "already_paired") refused.incrementAndGet() else throw e
                        }
                    }
                }
                start.countDown()
                futures.forEach { it.get(10, TimeUnit.SECONDS) }
            } finally {
                pool.shutdownNow()
            }

            assertEquals("round $round", 1, succeeded.get())
            assertEquals("round $round", 1, refused.get())
            assertNotNull("round $round", record.pairing)
        }
    }
}
