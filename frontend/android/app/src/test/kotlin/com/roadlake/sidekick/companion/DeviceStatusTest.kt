package com.roadlake.sidekick.companion

import com.roadlake.sidekick.today.MemoryPairingStore
import com.roadlake.sidekick.today.ScriptedHttp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private const val TOKEN = "rsc_abcdefghijklmnopqrstuvwxyz0123456789"
private const val SECRET = "rspair_abcdefghijklmnopqrstuvwxyz012345"

class DeviceInfoTest {
    @Test
    fun readsTheDatesOfADeviceObject() {
        val info = DeviceInfo.ofBody(
            """{"device":{"label":"Pixel","created_at":"2026-10-08T12:00:00Z","expires_at":"2027-01-08T12:00:00Z","renew_after":"2026-12-08T12:00:00Z"}}""",
        )
        assertEquals("Pixel", info.label)
        assertEquals("2026-10-08T12:00:00Z", info.createdAt)
        assertEquals("2027-01-08T12:00:00Z", info.expiresAt)
        assertEquals("2026-12-08T12:00:00Z", info.renewAfter)
    }

    @Test
    fun aDateThatIsNotAnInstantIsDropped() {
        val info = DeviceInfo.ofBody("""{"device":{"expires_at":"soon","renew_after":5}}""")
        assertNull(info.expiresAt)
        assertNull(info.renewAfter)
    }

    @Test
    fun brokenBodiesGiveNothing() {
        assertNull(DeviceInfo.ofBody("not json").expiresAt)
        assertNull(DeviceInfo.ofBody("{}").label)
    }

    @Test
    fun readsTheRoomsTheInstanceShows() {
        val info = DeviceInfo.ofBody("""{"device":{},"enabled_rooms":["work","journal"]}""")
        assertEquals(listOf("work", "journal"), info.enabledRooms)
    }

    @Test
    fun aServerThatDoesNotSayLeavesTheRoomsUnknown() {
        assertNull(DeviceInfo.ofBody("""{"device":{"label":"Pixel"}}""").enabledRooms)
    }

    @Test
    fun roomsThatAreNotPlainNamesAreNotKept() {
        assertNull(DeviceInfo.ofBody("""{"enabled_rooms":[]}""").enabledRooms)
        assertNull(DeviceInfo.ofBody("""{"enabled_rooms":["work",5]}""").enabledRooms)
        assertNull(DeviceInfo.ofBody("""{"enabled_rooms":["Work Room"]}""").enabledRooms)
        assertNull(DeviceInfo.ofBody("""{"enabled_rooms":"work"}""").enabledRooms)
    }
}

class DeviceStatusTest {
    private val device =
        """{"device":{"id":"d1","label":"Pixel","created_at":"2026-10-08T12:00:00Z","expires_at":"2027-01-08T12:00:00Z","renew_after":"2026-12-08T12:00:00Z"}}"""

    private fun stored() = Pairing("https://sidekick.example", TOKEN, "Stored", "2026-09-01T00:00:00Z", "2026-12-31T00:00:00Z", null)

    @Test
    fun refreshesTheStoredValuesFromTheServer() {
        val store = MemoryPairingStore(stored())
        val http = ScriptedHttp().apply { on { HttpResult(200, device) } }
        val status = CompanionClient(store, http, false).deviceStatus()
        assertTrue(status.paired)
        assertEquals("Pixel", status.name)
        assertEquals("2026-10-08T12:00:00Z", status.pairedAt)
        assertEquals("2027-01-08T12:00:00Z", status.expiresAt)
        assertEquals("2026-12-08T12:00:00Z", store.pairing!!.renewAfter)
        assertEquals(TOKEN, store.pairing!!.token)
        assertEquals("GET", http.calls.single().method)
        assertTrue(http.calls.single().url.endsWith("/companion/v1/device"))
    }

    @Test
    fun withoutNetworkTheStoredValuesAreUsed() {
        val http = ScriptedHttp().apply { on { CompanionException("network") } }
        val status = CompanionClient(MemoryPairingStore(stored()), http, false).deviceStatus()
        assertTrue(status.paired)
        assertEquals("Stored", status.name)
        assertEquals("2026-09-01T00:00:00Z", status.pairedAt)
        assertEquals("2026-12-31T00:00:00Z", status.expiresAt)
    }

    @Test
    fun aServerErrorKeepsTheStoredValuesToo() {
        val http = ScriptedHttp().apply { on { HttpResult(503, "") } }
        assertEquals("Stored", CompanionClient(MemoryPairingStore(stored()), http, false).deviceStatus().name)
    }

    @Test
    fun aMissingFieldKeepsTheStoredOne() {
        val http = ScriptedHttp().apply { on { HttpResult(200, """{"device":{"expires_at":"2027-02-01T00:00:00Z"}}""") } }
        val status = CompanionClient(MemoryPairingStore(stored()), http, false).deviceStatus()
        assertEquals("Stored", status.name)
        assertEquals("2027-02-01T00:00:00Z", status.expiresAt)
        assertEquals("2026-09-01T00:00:00Z", status.pairedAt)
    }

    @Test
    fun theRoomsOfTheInstanceAreRefreshedAndKeptForOffline() {
        val store = MemoryPairingStore(stored())
        val http = ScriptedHttp().apply {
            on { HttpResult(200, """{"device":{"label":"Pixel"},"enabled_rooms":["work","shopping"]}""") }
        }
        val client = CompanionClient(store, http, false)
        assertEquals(listOf("work", "shopping"), client.deviceStatus().enabledRooms)
        assertEquals(listOf("work", "shopping"), store.pairing!!.enabledRooms)
        // Offline: the page still gets them, from the pairing record (also through status()).
        val offline = CompanionClient(store, ScriptedHttp().apply { on { CompanionException("network") } }, false)
        assertEquals(listOf("work", "shopping"), offline.deviceStatus().enabledRooms)
        assertEquals(listOf("work", "shopping"), offline.status().enabledRooms)
    }

    @Test
    fun anOlderServerThatSaysNothingKeepsWhatWasStored() {
        val store = MemoryPairingStore(
            Pairing("https://sidekick.example", TOKEN, "Stored", enabledRooms = listOf("work", "journal")),
        )
        val http = ScriptedHttp().apply { on { HttpResult(200, device) } }
        assertEquals(listOf("work", "journal"), CompanionClient(store, http, false).deviceStatus().enabledRooms)
    }

    @Test
    fun theOwnersZoneIsReadFromTheAnswerAndOnlyWhenThePlatformKnowsIt() {
        assertEquals("America/New_York", DeviceInfo.ofBody("""{"device":{},"timezone":"America/New_York"}""").ownerTimeZone)
        assertNull(DeviceInfo.ofBody("""{"device":{}}""").ownerTimeZone)
        assertNull(DeviceInfo.ofBody("""{"device":{},"timezone":"Mars/Olympus_Mons"}""").ownerTimeZone)
        assertNull(DeviceInfo.ofBody("""{"device":{},"timezone":42}""").ownerTimeZone)
    }

    @Test
    fun theOwnersZoneIsRefreshedAndKeptForOfflineAndAnOlderServerDoesNotEraseIt() {
        val store = MemoryPairingStore(stored())
        val http = ScriptedHttp().apply { on { HttpResult(200, """{"device":{"label":"Pixel"},"timezone":"America/New_York"}""") } }
        assertEquals("America/New_York", CompanionClient(store, http, false).deviceStatus().ownerTimeZone)
        assertEquals("America/New_York", store.pairing!!.ownerTimeZone)
        val offline = CompanionClient(store, ScriptedHttp().apply { on { CompanionException("network") } }, false)
        assertEquals("America/New_York", offline.deviceStatus().ownerTimeZone)
        assertEquals("America/New_York", offline.status().ownerTimeZone)
        // An answer that leaves the zone out (older server) keeps what was stored.
        val older = CompanionClient(store, ScriptedHttp().apply { on { HttpResult(200, device) } }, false)
        assertEquals("America/New_York", older.deviceStatus().ownerTimeZone)
    }

    @Test
    fun pairingKeepsTheOwnersZoneTheServerGave() {
        val store = MemoryPairingStore(null)
        val http = ScriptedHttp().apply {
            on { HttpResult(201, """{"access_token":"$TOKEN","timezone":"Asia/Tokyo",""" + device.substring(1)) }
        }
        val status = CompanionClient(store, http, false).pair("https://sidekick.example", SECRET)
        assertEquals("Asia/Tokyo", store.pairing!!.ownerTimeZone)
        assertEquals("Asia/Tokyo", status.ownerTimeZone)
    }

    @Test
    fun whetherTheServerDeliversPushIsReadOnlyWhenItIsABoolean() {
        assertEquals(true, DeviceInfo.ofBody("""{"device":{},"push_enabled":true}""").pushEnabled)
        assertEquals(false, DeviceInfo.ofBody("""{"device":{},"push_enabled":false}""").pushEnabled)
        assertNull(DeviceInfo.ofBody("""{"device":{}}""").pushEnabled)
        assertNull(DeviceInfo.ofBody("""{"device":{},"push_enabled":"yes"}""").pushEnabled)
        assertNull(DeviceInfo.ofBody("""{"device":{},"push_enabled":1}""").pushEnabled)
    }

    @Test
    fun pushEnabledIsRefreshedKeptForOfflineAndAnOlderServerDoesNotEraseIt() {
        val store = MemoryPairingStore(stored())
        assertNull(CompanionClient(store, ScriptedHttp().apply { on { HttpResult(200, device) } }, false).deviceStatus().pushEnabled)
        val off = ScriptedHttp().apply { on { HttpResult(200, """{"device":{"label":"Pixel"},"push_enabled":false}""") } }
        assertEquals(false, CompanionClient(store, off, false).deviceStatus().pushEnabled)
        assertEquals(false, store.pairing!!.pushEnabled)
        val on = ScriptedHttp().apply { on { HttpResult(200, """{"device":{"label":"Pixel"},"push_enabled":true}""") } }
        assertEquals(true, CompanionClient(store, on, false).deviceStatus().pushEnabled)
        // Offline: the stored value is still there; an answer that leaves it out (older server) keeps it too.
        val offline = CompanionClient(store, ScriptedHttp().apply { on { CompanionException("network") } }, false)
        assertEquals(true, offline.deviceStatus().pushEnabled)
        val older = CompanionClient(store, ScriptedHttp().apply { on { HttpResult(200, device) } }, false)
        assertEquals(true, older.deviceStatus().pushEnabled)
    }

    @Test
    fun pairingKeepsWhetherTheServerDeliversPush() {
        val store = MemoryPairingStore(null)
        val http = ScriptedHttp().apply {
            on { HttpResult(201, """{"access_token":"$TOKEN","push_enabled":true,""" + device.substring(1)) }
        }
        CompanionClient(store, http, false).pair("https://sidekick.example", SECRET)
        assertEquals(true, store.pairing!!.pushEnabled)
    }

    @Test
    fun aPairingWithoutRoomsHasNone() {
        assertNull(CompanionClient(MemoryPairingStore(stored()), ScriptedHttp(), false).status().enabledRooms)
    }

    @Test
    fun pairingKeepsTheRoomsTheServerGave() {
        val store = MemoryPairingStore(null)
        val http = ScriptedHttp().apply {
            on { HttpResult(201, """{"access_token":"$TOKEN","enabled_rooms":["work","journal"],""" + device.substring(1)) }
        }
        val status = CompanionClient(store, http, false).pair("https://sidekick.example", SECRET)
        assertEquals(listOf("work", "journal"), store.pairing!!.enabledRooms)
        assertEquals(listOf("work", "journal"), status.enabledRooms)
    }

    @Test
    fun aRefusedCredentialIsUnpaired() {
        val store = MemoryPairingStore(stored())
        val http = ScriptedHttp().apply { on { HttpResult(401, "{}") } }
        val status = CompanionClient(store, http, false).deviceStatus()
        assertFalse(status.paired)
        assertNull(status.name)
        assertNull(store.pairing)
    }

    @Test
    fun notPairedAsksNobodyAndHasNothing() {
        val http = ScriptedHttp()
        val status = CompanionClient(MemoryPairingStore(null), http, false).deviceStatus()
        assertFalse(status.paired)
        assertNull(status.expiresAt)
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun pairingKeepsTheDatesTheServerGave() {
        val store = MemoryPairingStore(null)
        val http = ScriptedHttp().apply {
            on { HttpResult(201, """{"access_token":"$TOKEN",""" + device.substring(1)) }
        }
        CompanionClient(store, http, false).pair("https://sidekick.example", SECRET)
        val kept = store.pairing!!
        assertEquals("Pixel", kept.deviceLabel)
        assertEquals("2026-10-08T12:00:00Z", kept.pairedAt)
        assertEquals("2027-01-08T12:00:00Z", kept.expiresAt)
        assertEquals("2026-12-08T12:00:00Z", kept.renewAfter)
    }

    @Test
    fun pairingWithoutADeviceDateUsesThePhonesClock() {
        val store = MemoryPairingStore(null)
        val http = ScriptedHttp().apply { on { HttpResult(201, """{"access_token":"$TOKEN","device":{"label":"P"}}""") } }
        CompanionClient(store, http, false, clock = { 0L }).pair("https://sidekick.example", SECRET)
        assertEquals("1970-01-01T00:00:00Z", store.pairing!!.pairedAt)
        assertNull(store.pairing!!.renewAfter)
    }
}

class SendTestPushTest {
    private fun outcome(status: Int, body: String = "{}", retryAfter: Int? = null): TestPushResult {
        val http = ScriptedHttp().apply { on { HttpResult(status, body, retryAfter) } }
        return CompanionClient(MemoryPairingStore(), http, false).sendTestPush()
    }

    @Test
    fun a202IsQueued() {
        val result = outcome(202)
        assertEquals("queued", result.outcome.wire)
        assertNull(result.retryAfterSeconds)
    }

    @Test
    fun a429IsRateLimitedWithTheWait() {
        val result = outcome(429, retryAfter = 42)
        assertEquals("rate_limited", result.outcome.wire)
        assertEquals(42, result.retryAfterSeconds)
    }

    @Test
    fun a429WithoutAHeaderHasNoWait() {
        assertNull(outcome(429).retryAfterSeconds)
    }

    @Test
    fun a409NoSubscription() {
        assertEquals("no_subscription", outcome(409, """{"code":"conflict","reason":"no_subscription"}""").outcome.wire)
    }

    @Test
    fun anotherConflictIsNotNoSubscription() {
        assertEquals("offline", outcome(409, """{"reason":"other"}""").outcome.wire)
    }

    @Test
    fun a404IsDisabled() {
        assertEquals("disabled", outcome(404).outcome.wire)
    }

    @Test
    fun aServerErrorIsOffline() {
        assertEquals("offline", outcome(502).outcome.wire)
    }

    @Test
    fun noNetworkIsOffline() {
        val http = ScriptedHttp().apply { on { CompanionException("network") } }
        assertEquals("offline", CompanionClient(MemoryPairingStore(), http, false).sendTestPush().outcome.wire)
    }

    @Test
    fun a401IsUnpairedAndEndsThePairing() {
        val store = MemoryPairingStore()
        val http = ScriptedHttp().apply { on { HttpResult(401, "{}") } }
        assertEquals("unpaired", CompanionClient(store, http, false).sendTestPush().outcome.wire)
        assertNull(store.pairing)
    }

    @Test
    fun notPairedIsUnpairedWithoutACall() {
        val http = ScriptedHttp()
        assertEquals("unpaired", CompanionClient(MemoryPairingStore(null), http, false).sendTestPush().outcome.wire)
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun postsToTheTestRouteWithTheBearerTokenAndNoBody() {
        val http = ScriptedHttp().apply { on { HttpResult(202, "{}") } }
        CompanionClient(MemoryPairingStore(), http, false).sendTestPush()
        val call = http.calls.single()
        assertEquals("POST", call.method)
        assertTrue(call.url.endsWith("/companion/v1/push/test"))
        assertEquals("Bearer $TOKEN", call.headers["Authorization"])
        assertNull(call.body)
    }
}
