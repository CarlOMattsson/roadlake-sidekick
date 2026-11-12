package com.roadlake.sidekick.flow

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.RenewalOutcome
import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.support.JvmPhone
import com.roadlake.sidekick.today.TASK_A
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * The app's own HTTP transport, client and stores against a fake companion server on a real socket: pairing, renewal and
 * revocation as the phone sees them. Simulated server, real client side; no emulator and no real backend.
 */
class CompanionOverHttpTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val phone by lazy { JvmPhone(folder.newFolder()) }

    @After
    fun stopServer() = phone.close()

    private fun today() = phone.process.client.request("GET", "/companion/v1/work/today", null, null, null)

    @Test
    fun pairingExchangesTheSecretOverHttpAndKeepsTheServersCredential() {
        phone.pair()

        val kept = phone.process.store.load()!!
        assertEquals(phone.server.validToken, kept.token)
        assertEquals(phone.server.origin, kept.serverOrigin)
        assertEquals("Test phone", kept.deviceLabel)
        assertEquals("2026-10-08T12:00:00Z", kept.pairedAt)
        // Whether the server delivers push is kept with the pairing, for a cold start without a network.
        assertEquals(true, kept.pushEnabled)
        val status = phone.process.client.status()
        assertTrue(status.paired)
        assertEquals("127.0.0.1", status.serverHost)
        assertEquals(listOf("work"), status.enabledRooms)
        assertEquals(1, phone.process.widgetRedraws)
        // The secret travels once, in the body of the exchange; the exchange itself carries no credential.
        val exchange = phone.server.requestsTo("POST", "/companion/v1/pair").single()
        assertNull(exchange.headers["authorization"])
    }

    @Test
    fun aSpentPairingSecretIsRefusedAndNothingIsStored() {
        phone.pair()
        phone.process.client.unpair()

        val failure = try {
            phone.process.client.pair(phone.server.origin, JvmPhone.SECRET)
            null
        } catch (e: CompanionException) {
            e
        }

        // The server's `pairing_invalid`; the JDK's HttpURLConnection withholds the body of a 401 to a streamed POST, so
        // here only the status is left. The instrumented lifecycle test sees the platform's own client.
        assertTrue(failure?.code in setOf("pairing_invalid", "http_401"))
        assertNull(phone.process.store.load())
    }

    @Test
    fun anAuthenticatedRequestCarriesTheBearerToken() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")

        assertEquals(200, today().status)

        val sent = phone.server.requestsTo("GET", "/companion/v1/work/today").single()
        assertEquals("Bearer ${phone.server.validToken}", sent.headers["authorization"])
    }

    @Test
    fun renewalRotatesTheTokenAndTheNextRequestUsesTheNewOne() {
        phone.pair()
        val before = phone.server.validToken
        assertEquals("before renew_after nobody is asked", RenewalOutcome.NOT_DUE, phone.process.renewal.run())
        assertTrue(phone.server.requestsTo("POST", "/companion/v1/device/renew").isEmpty())
        phone.server.renewAfter = "2026-11-01T12:00:00Z"
        phone.clock = PAST_RENEW_AFTER

        assertEquals(RenewalOutcome.RENEWED, phone.process.renewal.run())

        val after = phone.server.validToken
        assertNotEquals(before, after)
        assertEquals(after, phone.process.store.load()!!.token)
        assertEquals(200, today().status)
        assertEquals("Bearer $after", phone.server.requestsTo("GET", "/companion/v1/work/today").last().headers["authorization"])
        // A renewal is not a new pairing: the widget is not disturbed and the page hears of no loss.
        assertEquals(1, phone.process.widgetRedraws)
        assertEquals(0, phone.process.pairingLosses)
    }

    @Test
    fun aRenewalTheServerRefusesAsNotDueMovesTheDateAndKeepsThePairing() {
        phone.pair()
        phone.server.renewAfter = "2026-12-20T12:00:00Z"
        phone.clock = PAST_RENEW_AFTER

        // The phone still holds the date from pairing time (2026-12-08): due, so it asks, and the server says "not yet".
        assertEquals(RenewalOutcome.NOT_DUE, phone.process.renewal.run())

        assertEquals("2026-12-20T12:00:00Z", phone.process.store.load()!!.renewAfter)
        assertEquals(1, phone.server.requestsTo("POST", "/companion/v1/device/renew").size)
        assertEquals(RenewalOutcome.NOT_DUE, phone.process.renewal.run())
        assertEquals("the second run asks nobody", 1, phone.server.requestsTo("POST", "/companion/v1/device/renew").size)
    }

    @Test
    fun unpairingRevokesTheDeviceOnTheServerAndClearsEverythingOnThePhone() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.process.today.sync()
        assertTrue(phone.process.cache.hasData())

        assertTrue("the server confirmed the revocation", phone.process.client.unpair())

        assertNull(phone.server.validToken)
        assertEquals(1, phone.server.requestsTo("DELETE", "/companion/v1/device").size)
        assertNull(phone.process.store.load())
        assertFalse(phone.process.cache.hasData())
        assertFalse(phone.process.outbox.hasData())
        assertEquals(2, phone.process.widgetRedraws)
        try {
            today()
            fail("a request without a pairing must not be sent")
        } catch (e: CompanionException) {
            assertEquals("not_paired", e.code)
        }
    }

    @Test
    fun unpairingWithTheServerUnreachableStillClearsThePhoneAndSaysSo() {
        phone.pair()
        phone.server.offline = true

        assertFalse("the page must tell the owner to revoke the device in Control", phone.process.client.unpair())

        assertNull(phone.process.store.load())
        assertNotNull("the server never heard of it", phone.server.validToken)
    }

    @Test
    fun aDeviceRevokedOnTheServerEndsThePairingAtTheNextRequest() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.process.today.sync()
        phone.server.revokeDevice()

        assertEquals(401, today().status)

        assertNull(phone.process.store.load())
        assertEquals(1, phone.process.pairingLosses)
        assertFalse("the cache of the lost pairing is gone", phone.process.cache.hasData())
    }

    @Test
    fun aRenewalOfARevokedDeviceEndsThePairingToo() {
        phone.pair()
        phone.server.revokeDevice()
        phone.clock = PAST_RENEW_AFTER

        assertEquals(RenewalOutcome.UNPAIRED, phone.process.renewal.run())

        assertNull(phone.process.store.load())
        assertEquals(1, phone.process.pairingLosses)
    }

    private companion object {
        /** After the 2026-12-08 `renew_after` the fake server gives at pairing. */
        val PAST_RENEW_AFTER = IsoInstant.parse("2026-12-09T00:00:00Z")!!
    }
}
