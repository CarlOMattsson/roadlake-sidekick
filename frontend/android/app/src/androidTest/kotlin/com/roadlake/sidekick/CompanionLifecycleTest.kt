package com.roadlake.sidekick

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.KeystorePairingStore
import com.roadlake.sidekick.companion.RenewalOutcome
import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.support.FakeCompanionServer
import com.roadlake.sidekick.support.PhoneProcess
import com.roadlake.sidekick.today.EnqueueResult
import com.roadlake.sidekick.today.FileTextStore
import com.roadlake.sidekick.today.SyncResult
import com.roadlake.sidekick.today.TASK_A
import com.roadlake.sidekick.today.TodayState
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
 * On a device or emulator (not run by the JVM suite): the app's own objects over the real Android Keystore store, real
 * files with a real directory fsync and the platform's HTTP client, against a fake companion server on the device's
 * loopback (the debug build allows cleartext to 127.0.0.1). A "restart" is a new [PhoneProcess] over the same Keystore
 * entry and the same files, which is what a killed process leaves; the OS process itself is not killed.
 *
 * Simulated, not real: the server is a fake and the device is one emulator image. It proves the app's side of pairing,
 * renewal, revocation and the outbox, and says nothing about a real server, a real phone's battery management or a
 * launcher widget (Glance rendering and WorkManager scheduling are not driven here).
 */
@RunWith(AndroidJUnit4::class)
class CompanionLifecycleTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val keystore = KeystorePairingStore(context)
    private lateinit var directory: File
    private lateinit var server: FakeCompanionServer
    private var clock = IsoInstant.parse("2026-11-08T12:00:00Z")!!
    private var keystoreIsOurs = false

    @Before
    fun setUp() {
        // Never touch a pairing that is really there (a developer's phone running the debug build).
        assumeTrue("a pairing already exists on this device", keystore.load() == null)
        keystoreIsOurs = true
        directory = File(context.cacheDir, "lifecycle-${UUID.randomUUID()}").apply { mkdirs() }
        server = FakeCompanionServer()
    }

    @After
    fun tearDown() {
        if (::server.isInitialized) server.close()
        if (::directory.isInitialized) directory.deleteRecursively()
        if (keystoreIsOurs) keystore.clear()
    }

    private fun startProcess() = PhoneProcess(
        keystore,
        { name -> FileTextStore(File(directory, name)) },
        { clock },
    )

    private fun pair(process: PhoneProcess) {
        server.issuePairing(SECRET)
        process.client.pair(server.origin, SECRET)
    }

    @Test
    fun pairingAndARenewedCredentialAreRestoredFromTheKeystoreAfterARestart() {
        val first = startProcess()
        pair(first)
        assertEquals(server.validToken, keystore.load()?.token)
        server.renewAfter = "2026-11-01T12:00:00Z"
        clock = IsoInstant.parse("2026-12-09T00:00:00Z")!!
        assertEquals(RenewalOutcome.RENEWED, first.renewal.run())

        val restarted = startProcess()

        assertEquals(server.validToken, restarted.store.load()?.token)
        assertEquals("Test phone", restarted.client.status().deviceLabel)
        assertEquals(200, restarted.client.request("GET", "/companion/v1/work/today", null, null, null).status)
    }

    @Test
    fun aSpentPairingSecretIsRefusedAndNothingReachesTheKeystore() {
        val process = startProcess()
        pair(process)
        process.client.unpair()

        val failure = try {
            process.client.pair(server.origin, SECRET)
            null
        } catch (e: CompanionException) {
            e
        }

        // The server's `pairing_invalid`, or `http_401` when the HTTP client withholds the body of a 401 to a streamed POST.
        assertTrue(failure?.code in setOf("pairing_invalid", "http_401"))
        assertNull(keystore.load())
    }

    @Test
    fun aCompletionQueuedWhileOfflineIsSentAfterARestartWithTheSameKey() {
        val first = startProcess()
        pair(first)
        server.addTask(TASK_A, "Köp mjölk")
        assertEquals(SyncResult.UPDATED, first.today.sync())
        server.offline = true
        assertEquals(EnqueueResult.QUEUED, first.today.enqueueCompletion(TASK_A))
        val key = first.outbox.pending().single().idempotencyKey
        assertEquals(SyncResult.RETRY, first.today.sync())

        val restarted = startProcess()
        assertEquals(key, restarted.outbox.pending().single().idempotencyKey)
        assertEquals(setOf(TASK_A), (restarted.today.state() as TodayState.Ready).pendingTaskIds)
        server.offline = false
        assertEquals(SyncResult.UPDATED, restarted.today.sync())

        assertEquals(1, server.completionsApplied)
        assertEquals(key, server.requestsTo("POST", "/companion/v1/tasks/$TASK_A/complete").last().headers["idempotency-key"])
        assertTrue(restarted.outbox.pending().isEmpty())
        assertTrue((restarted.today.state() as TodayState.Ready).snapshot.tasks.isEmpty())
    }

    @Test
    fun unpairingRevokesOnTheServerAndLeavesNothingOnThePhone() {
        val process = startProcess()
        pair(process)
        server.addTask(TASK_A, "Köp mjölk")
        process.today.sync()
        process.today.enqueueCompletion(TASK_A)
        assertTrue(process.cache.hasData() && process.outbox.hasData())

        assertTrue(process.client.unpair())

        assertNull(server.validToken)
        assertNull(keystore.load())
        assertFalse(process.cache.hasData())
        assertFalse(process.outbox.hasData())
        assertEquals(TodayState.NotPaired, startProcess().today.state())
    }

    @Test
    fun aDeviceRevokedOnTheServerEndsThePairingAcrossARestart() {
        val first = startProcess()
        pair(first)
        server.addTask(TASK_A, "Köp mjölk")
        first.today.sync()
        val restarted = startProcess()
        assertNotNull(restarted.store.load())
        server.revokeDevice()

        assertEquals(SyncResult.NOT_PAIRED, restarted.today.sync())

        assertNull(keystore.load())
        assertFalse(restarted.cache.hasData())
        assertEquals(1, restarted.pairingLosses)
    }

    private companion object {
        const val SECRET = "pairing_secret_0123456789"
    }
}
