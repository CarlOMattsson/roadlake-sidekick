package com.roadlake.sidekick

import android.content.Context
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.roadlake.sidekick.companion.KeystorePairingStore
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStore
import com.roadlake.sidekick.companion.SidekickNativePlugin
import com.roadlake.sidekick.today.ClearingPairingStore
import com.roadlake.sidekick.today.FileTextStore
import com.roadlake.sidekick.today.Outbox
import com.roadlake.sidekick.today.TodayCache
import com.roadlake.sidekick.today.TodaySnapshot
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

/**
 * Smoke test on a device or emulator (not run by the JVM suite): the app starts, the Capacitor bridge has the
 * SidekickNative plugin with the methods the page calls, and a pair/unpair round trip against the app's own storage
 * ends with nothing left behind. There is no server and no network traffic: the pairing is written to local stores.
 *
 * Simulated, not real: this proves the wiring on one emulator image. It says nothing about a real phone's battery
 * management, a real server or a Claude host.
 */
@RunWith(AndroidJUnit4::class)
class PairingBridgeSmokeTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var scratch: File

    @Before
    fun setUp() {
        scratch = File(context.cacheDir, "smoke-${UUID.randomUUID()}").apply { mkdirs() }
    }

    @After
    fun tearDown() {
        scratch.deleteRecursively()
    }

    @Test
    fun bridgeRegistersTheSidekickNativePluginWithItsMethods() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val bridge = activity.bridge
                assertNotNull("the bridge is created", bridge)
                assertNotNull("the WebView is created", bridge.webView)

                val handle = bridge.getPlugin("SidekickNative")
                assertNotNull("SidekickNative is registered", handle)
                assertTrue(handle.instance is SidekickNativePlugin)

                val methods = handle.methods.map { it.name }.toSet()
                val expected = setOf("request", "pair", "unpair", "status", "deviceStatus", "setLocale", "widgetRefresh")
                assertTrue("missing plugin methods: ${expected - methods}", methods.containsAll(expected))

                assertNotNull("the Capacitor App plugin is registered", bridge.getPlugin("App"))
            }
        }
    }

    @Test
    fun pairingRoundTripThroughTheClearingStoreLeavesNothingBehind() {
        val generation = PairingGeneration()
        val cache = TodayCache(FileTextStore(File(scratch, "today-cache.json")))
        val outbox = Outbox(FileTextStore(File(scratch, "outbox.json")), clock = System::currentTimeMillis)
        val store = ClearingPairingStore(
            delegate = MemoryPairingStore(),
            clearLocalData = {
                cache.clear()
                outbox.clear()
            },
            changed = {},
            generation = generation,
        )
        val start = generation.current()

        store.save(PAIRING)
        assertEquals(start + 1, generation.current())
        assertEquals(PAIRING.serverOrigin, store.load()?.serverOrigin)

        // State of this pairing, which the end of the pairing has to remove.
        assertTrue(cache.save(TodaySnapshot(PAIRING.serverOrigin, 1L, emptyList(), 0)))
        assertNotNull(outbox.enqueue("task-1", 1, "key-1"))
        assertTrue(cache.hasData())
        assertTrue(outbox.hasData())

        store.clear()
        assertEquals(start + 2, generation.current())
        assertNull(store.load())
        assertFalse("the Today cache is gone", cache.hasData())
        assertFalse("the outbox is gone", outbox.hasData())
        assertTrue(outbox.pending().isEmpty())
    }

    @Test
    fun keystoreStoreKeepsAPairingAndClearsItAgain() {
        val store = KeystorePairingStore(context)
        // Never touch a pairing that is really there (a developer's phone running the debug build).
        assumeTrue("a pairing already exists on this device", store.load() == null)
        try {
            store.save(PAIRING)
            val loaded = store.load()
            assertNotNull(loaded)
            assertEquals(PAIRING.serverOrigin, loaded?.serverOrigin)
            assertEquals(PAIRING.token, loaded?.token)
            assertEquals(PAIRING.deviceLabel, loaded?.deviceLabel)
        } finally {
            store.clear()
        }
        assertNull("the pairing is removed", store.load())
    }

    private class MemoryPairingStore : PairingStore {
        private var current: Pairing? = null

        override fun load(): Pairing? = current

        override fun save(pairing: Pairing) {
            current = pairing
        }

        override fun clear() {
            current = null
        }
    }

    private companion object {
        val PAIRING = Pairing(
            serverOrigin = "https://sidekick.invalid",
            token = "smoke-test-token",
            deviceLabel = "Smoke test",
            pairedAt = "2026-01-01T00:00:00Z",
        )
    }
}
