package com.roadlake.sidekick.push

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.today.ClearingPairingStore
import com.roadlake.sidekick.today.MemoryPairingStore
import com.roadlake.sidekick.today.MemoryTextStore
import com.roadlake.sidekick.today.ScriptedHttp
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeDistributor(var installed: Boolean = true) : PushDistributor {
    var registers = 0
    var unregisters = 0
    var failUnregister = false

    override fun available() = installed

    override fun register() {
        registers++
    }

    override fun unregister() {
        unregisters++
        if (failUnregister) throw IllegalStateException("distributor gone")
    }
}

private class FakeGate(var current: PermissionState = PermissionState.PROMPT) : NotificationGate {
    var asked = 0

    override fun state() = current

    override fun ask() {
        asked++
        current = PermissionState.DENIED
    }
}

/** The push registrar over the real client and the app's wiring (ClearingPairingStore), with a scripted server. */
private class Harness(paired: Boolean = true) {
    val pairing = MemoryPairingStore(if (paired) MemoryPairingStore().pairing else null)
    val stateText = MemoryTextStore()
    val http = ScriptedHttp()
    val distributor = FakeDistributor()
    val gate = FakeGate()
    val state = PushState(stateText)
    val generation = PairingGeneration()
    lateinit var client: CompanionClient
    lateinit var clearing: ClearingPairingStore
    val push: PushRegistrar by lazy {
        PushRegistrar(
            api = object : PushApi {
                override fun put(endpoint: String): CompanionResponse = client.putPushSubscription(endpoint)

                override fun delete(): CompanionResponse = client.deletePushSubscription()
            },
            state = state,
            isPaired = { pairing.load() != null },
            distributor = distributor,
            notifications = gate,
            generation = generation,
        )
    }

    init {
        clearing = ClearingPairingStore(pairing, { push.clearLocal() }, {}, generation)
        client = CompanionClient(
            store = clearing,
            http = http,
            allowLocalCleartext = false,
            onBeforeUnpair = { push.beforeUnpair() },
            generation = generation,
        )
        http.on { if (it.url.endsWith("/push/subscription")) HttpResult(if (it.method == "PUT") 200 else 204, "") else null }
        http.on { if (it.url.endsWith("/device") && it.method == "DELETE") HttpResult(204, "") else null }
    }

    fun routes() = http.calls.map { "${it.method} ${it.url.removePrefix("https://sidekick.example")}" }
}

class PushRegistrarTest {
    private val endpoint = "https://ntfy.sh/up-AbCdEf123456"
    private val other = "https://ntfy.sh/up-ZyXwVu654321"

    // --- registration ----------------------------------------------------------------------------------------

    @Test
    fun aNewEndpointIsRegisteredWithPut() {
        val h = Harness()
        assertTrue(h.push.onNewEndpoint(endpoint))
        assertEquals(SyncOutcome.DONE, h.push.sync())

        val call = h.http.calls.single()
        assertEquals("PUT", call.method)
        assertEquals("https://sidekick.example/companion/v1/push/subscription", call.url)
        assertEquals("Bearer rsc_abcdefghijklmnopqrstuvwxyz0123456789", call.headers["Authorization"])
        assertEquals("application/json", call.headers["Content-Type"])
        assertEquals(endpoint, JSONObject(String(call.body!!)).getString("endpoint"))
        assertTrue(h.push.status().registered)
    }

    @Test
    fun theSameEndpointAgainIsNotSentAgain() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()

        assertFalse(h.push.onNewEndpoint(endpoint))
        assertEquals(SyncOutcome.DONE, h.push.sync())
        assertEquals(1, h.http.calls.size)
    }

    @Test
    fun aChangedEndpointReplacesTheOldWithAnotherPut() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()
        assertTrue(h.push.onNewEndpoint(other))
        h.push.sync()

        assertEquals(listOf("PUT", "PUT"), h.http.calls.map { it.method })
        assertEquals(other, JSONObject(String(h.http.calls.last().body!!)).getString("endpoint"))
    }

    @Test
    fun noAnswerAndServerErrorsAreRetriedAndThenSucceed() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.http.on { CompanionException("network") }
        assertEquals(SyncOutcome.RETRY, h.push.sync())
        assertFalse(h.push.status().registered)

        h.http.on { HttpResult(503, "") }
        assertEquals(SyncOutcome.RETRY, h.push.sync())

        h.http.on { HttpResult(200, "") }
        assertEquals(SyncOutcome.DONE, h.push.sync())
        assertTrue(h.push.status().registered)
    }

    @Test
    fun anEndpointTheServerRefusesIsNotRetriedInALoop() {
        val h = Harness()
        h.push.onNewEndpoint("https://elsewhere.example/up-x")
        h.http.on { HttpResult(422, """{"code":"validation_error"}""") }

        assertEquals(SyncOutcome.DONE, h.push.sync())
        assertFalse(h.push.status().registered)
    }

    @Test
    fun anEndpointThatArrivesDuringTheRequestStaysUnsynced() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.http.on {
            h.push.onNewEndpoint(other)
            HttpResult(200, "")
        }
        h.push.sync()

        assertFalse(h.push.status().registered)
        assertFalse(h.state.inSync())
    }

    // --- unregister ------------------------------------------------------------------------------------------

    @Test
    fun theDistributorUnregisteringTheAppGivesDelete() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()

        assertTrue(h.push.onUnregistered())
        assertEquals(SyncOutcome.DONE, h.push.sync())

        assertEquals(listOf("PUT", "DELETE"), h.http.calls.map { it.method })
        assertEquals("https://sidekick.example/companion/v1/push/subscription", h.http.calls.last().url)
        assertNull(h.http.calls.last().body)
        assertFalse(h.push.status().registered)
        // Nothing is left to remove: a second sync sends nothing.
        h.push.sync()
        assertEquals(2, h.http.calls.size)
    }

    @Test
    fun unregisteringWithoutAnAcceptedRegistrationSendsNothing() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        assertFalse(h.push.onUnregistered())
        assertEquals(SyncOutcome.DONE, h.push.sync())
        assertTrue(h.http.calls.isEmpty())
    }

    @Test
    fun aFailedDeleteIsRetried() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()
        h.push.onUnregistered()
        h.http.on { HttpResult(502, "") }
        assertEquals(SyncOutcome.RETRY, h.push.sync())
        h.http.on { HttpResult(204, "") }
        assertEquals(SyncOutcome.DONE, h.push.sync())
        assertTrue(h.state.inSync())
    }

    // --- no distributor --------------------------------------------------------------------------------------

    @Test
    fun noDistributorMeansNoRegistrationAndNoCrash() {
        val h = Harness()
        h.distributor.installed = false

        assertFalse(h.push.ensure())
        assertEquals(SyncOutcome.DONE, h.push.sync())

        assertEquals(0, h.distributor.registers)
        assertEquals(0, h.gate.asked)
        assertTrue(h.http.calls.isEmpty())
        val status = h.push.status()
        assertFalse(status.distributor)
        assertFalse(status.registered)
    }

    // --- start and permission --------------------------------------------------------------------------------

    @Test
    fun ensureAsksTheDistributorAndAsksForNotificationsOnce() {
        val h = Harness()
        h.push.ensure()
        h.push.ensure()

        assertEquals(2, h.distributor.registers)
        assertEquals(1, h.gate.asked)
    }

    @Test
    fun ensureDoesNotAskWhenGrantedOrWhenNotPaired() {
        val granted = Harness().apply { gate.current = PermissionState.GRANTED }
        granted.push.ensure()
        assertEquals(0, granted.gate.asked)
        assertEquals(1, granted.distributor.registers)

        val unpaired = Harness(paired = false)
        assertFalse(unpaired.push.ensure())
        assertEquals(0, unpaired.distributor.registers)
        assertEquals(0, unpaired.gate.asked)
    }

    @Test
    fun ensureReportsAnUnsyncedEndpointSoItIsSentAgain() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        assertTrue(h.push.ensure())
        h.push.sync()
        assertFalse(h.push.ensure())
    }

    @Test
    fun theNotificationPermissionRule() {
        val rules = NotificationPermissionRules
        assertEquals(PermissionState.GRANTED, rules.resolve(sdk = 34, enabled = true, asked = false))
        assertEquals(PermissionState.GRANTED, rules.resolve(sdk = 30, enabled = true, asked = true))
        assertEquals(PermissionState.PROMPT, rules.resolve(sdk = 34, enabled = false, asked = false))
        assertEquals(PermissionState.DENIED, rules.resolve(sdk = 34, enabled = false, asked = true))
        assertEquals(PermissionState.DENIED, rules.resolve(sdk = 30, enabled = false, asked = false))
    }

    // --- unpair ----------------------------------------------------------------------------------------------

    @Test
    fun unpairRemovesTheSubscriptionBeforeTheDeviceAndCleansUp() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()
        h.http.calls.clear()

        assertTrue(h.client.unpair())

        assertEquals(
            listOf("DELETE /companion/v1/push/subscription", "DELETE /companion/v1/device"),
            h.routes(),
        )
        assertNull(h.pairing.pairing)
        assertNull(h.stateText.text)
        assertEquals(1, h.distributor.unregisters)
        assertFalse(h.push.status().registered)
    }

    @Test
    fun unpairWithoutAPushSubscriptionOnlyRevokesTheDevice() {
        val h = Harness()
        assertTrue(h.client.unpair())

        assertEquals(listOf("DELETE /companion/v1/device"), h.routes())
        assertEquals(1, h.distributor.unregisters)
    }

    @Test
    fun unpairStillCleansWhenTheSubscriptionCannotBeRemovedOrTheDistributorIsGone() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()
        h.distributor.failUnregister = true
        h.http.on { if (it.url.endsWith("/push/subscription")) CompanionException("network") else null }

        assertTrue(h.client.unpair())

        assertNull(h.pairing.pairing)
        assertNull(h.stateText.text)
    }

    @Test
    fun aRefusedCredentialAlsoCleansThePushState() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()
        h.http.on { HttpResult(401, "") }

        h.push.onNewEndpoint(other)
        h.push.sync()

        assertNull(h.pairing.pairing)
        assertNull(h.stateText.text)
        assertEquals(1, h.distributor.unregisters)
    }

    @Test
    fun anAnswerOfAnEndedPairingDoesNotMarkTheNextPairingAsRegistered() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.http.on {
            if (it.method == "PUT") {
                // The pairing is replaced while the registration is in flight; the distributor then gives the same endpoint.
                h.clearing.clear()
                h.clearing.save(Pairing("https://sidekick.example", "rsc_newnewnewnewnewnewnewnew0123456789", null))
                h.push.onNewEndpoint(endpoint)
                HttpResult(200, "")
            } else {
                null
            }
        }

        assertEquals(SyncOutcome.DONE, h.push.sync())

        assertNull(h.state.syncedHash)
        assertFalse(h.push.status().registered)
        assertFalse(h.state.inSync())
    }

    @Test
    fun aNewPairingStartsWithoutTheEarlierEndpoint() {
        val h = Harness()
        h.push.onNewEndpoint(endpoint)
        h.push.sync()

        h.client.unpair()
        assertNull(h.state.endpoint)
        assertNull(h.state.syncedHash)
    }
}
