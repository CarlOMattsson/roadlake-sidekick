package com.roadlake.sidekick.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

private class MemoryStore(var pairing: Pairing? = null, var failSave: Boolean = false) : PairingStore {
    var clears = 0

    override fun load(): Pairing? = pairing

    override fun save(pairing: Pairing) {
        if (failSave) throw CompanionException("secure_storage")
        this.pairing = pairing
    }

    override fun clear() {
        clears++
        pairing = null
    }
}

private class ScriptedHttp(private val answer: (HttpCall) -> HttpResult) : HttpTransport {
    val calls = mutableListOf<HttpCall>()

    override fun execute(call: HttpCall): HttpResult {
        calls += call
        return answer(call)
    }
}

class CompanionClientTest {
    private val origin = "https://sidekick.example"
    private val token = "rsc_abcdefghijklmnopqrstuvwxyz0123456789"
    private val secret = "rspair_abcdefghijklmnopqrstuvwxyz012345"
    private val taskId = "3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e"

    private fun paired() = MemoryStore(Pairing(origin, token, "Samsung"))

    private fun code(block: () -> Unit): String = assertThrows(CompanionException::class.java, block).code

    private fun client(store: PairingStore, http: HttpTransport, lost: () -> Unit = {}, cleartext: Boolean = false) =
        CompanionClient(store, http, cleartext, lost)

    // --- request ---------------------------------------------------------------------------------------------

    @Test
    fun requestSendsTheBearerTokenToThePairedOriginOnly() {
        val http = ScriptedHttp { HttpResult(200, """{"ok":true}""") }
        val response = client(paired(), http).request(
            "GET",
            "/companion/v1/work/agenda",
            mapOf("limit" to listOf("20")),
            null,
            null,
        )
        assertEquals(200, response.status)
        assertEquals("""{"ok":true}""", response.body)
        val call = http.calls.single()
        assertEquals("GET", call.method)
        assertEquals("$origin/companion/v1/work/agenda?limit=20", call.url)
        assertEquals("Bearer $token", call.headers["Authorization"])
        assertFalse(call.headers.containsKey("Idempotency-Key"))
        assertNull(call.body)
    }

    @Test
    fun aPostCarriesTheBodyAndTheIdempotencyKeyByteForByte() {
        val http = ScriptedHttp { HttpResult(200, "{}") }
        client(paired(), http).request(
            "POST",
            "/companion/v1/tasks/$taskId/complete",
            null,
            """{"version":4}""",
            "key-0001-abcd",
        )
        val call = http.calls.single()
        assertEquals("application/json", call.headers["Content-Type"])
        assertEquals("key-0001-abcd", call.headers["Idempotency-Key"])
        assertEquals("""{"version":4}""", String(call.body!!))
    }

    @Test
    fun aRefusedRequestSendsNothingEvenWhenNotPaired() {
        val http = ScriptedHttp { HttpResult(200, "{}") }
        val client = client(MemoryStore(), http)
        assertEquals("path_refused", code { client.request("GET", "/api/v1/tasks", null, null, null) })
        assertEquals("path_refused", code { client.request("GET", "/companion/v1/pair", null, null, null) })
        assertEquals("bad_request", code { client.request("DELETE", "/companion/v1/work/agenda", null, null, null) })
        assertEquals("bad_request", code { client.request("GET", "/companion/v1/work/agenda", null, null, "key-0001-abcd") })
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun withoutAPairingARequestIsNotPaired() {
        val http = ScriptedHttp { HttpResult(200, "{}") }
        val error = code { client(MemoryStore(), http).request("GET", "/companion/v1/work/agenda", null, null, null) }
        assertEquals("not_paired", error)
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun otherStatusesAreAnswersAndKeepThePairing() {
        val store = paired()
        var lost = 0
        for (status in listOf(403, 404, 409, 422, 429, 500, 503)) {
            val http = ScriptedHttp { HttpResult(status, """{"code":"x"}""") }
            val response = client(store, http, { lost++ }).request("GET", "/companion/v1/work/agenda", null, null, null)
            assertEquals(status, response.status)
        }
        assertNotNull(store.pairing)
        assertEquals(0, lost)
    }

    @Test
    fun a401ClearsThePairingAndSignalsPairAgain() {
        val store = paired()
        var lost = 0
        val http = ScriptedHttp { HttpResult(401, """{"code":"unauthorized"}""") }
        val response = client(store, http, { lost++ }).request("GET", "/companion/v1/work/agenda", null, null, null)
        assertEquals(401, response.status)
        assertNull(store.pairing)
        assertEquals(1, lost)
        assertFalse(client(store, http).status().paired)
    }

    @Test
    fun aStale401DoesNotClearANewerPairing() {
        val store = paired()
        var lost = 0
        val http = ScriptedHttp {
            // While the request is in flight the phone is paired again with a new credential.
            store.pairing = Pairing(origin, "rsc_newer0000000000000000000000000000", "Samsung")
            HttpResult(401, "{}")
        }
        client(store, http, { lost++ }).request("GET", "/companion/v1/work/agenda", null, null, null)
        assertEquals("rsc_newer0000000000000000000000000000", store.pairing?.token)
        assertEquals(0, lost)
    }

    @Test
    fun noAnswerKeepsThePairing() {
        val store = paired()
        val http = ScriptedHttp { throw CompanionException("timeout") }
        assertEquals("timeout", code { client(store, http).request("GET", "/companion/v1/work/agenda", null, null, null) })
        assertNotNull(store.pairing)
    }

    // --- status ----------------------------------------------------------------------------------------------

    @Test
    fun statusShowsTheHostAndNeverASecret() {
        val http = ScriptedHttp { HttpResult(200, "{}") }
        assertEquals(PairingStatus.UNPAIRED, client(MemoryStore(), http).status())
        val status = client(paired(), http).status()
        assertTrue(status.paired)
        assertEquals("sidekick.example", status.serverHost)
        assertEquals("Samsung", status.deviceLabel)
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun aStoredCleartextOriginIsNotTrustedInAReleaseBuild() {
        val store = MemoryStore(Pairing("http://10.0.2.2:8101", token, null))
        val status = client(store, ScriptedHttp { HttpResult(200, "{}") }).status()
        assertFalse(status.paired)
        assertNull(store.pairing)
    }

    // --- pair ------------------------------------------------------------------------------------------------

    private fun pairedBody() = JSONObject()
        .put("access_token", token)
        .put("token_type", "Bearer")
        .put("device", JSONObject().put("label", "Samsung"))
        .toString()

    @Test
    fun pairExchangesTheSecretAndKeepsTheCredential() {
        val store = MemoryStore()
        val http = ScriptedHttp { HttpResult(201, pairedBody()) }
        val status = client(store, http).pair("https://Sidekick.Example/", secret)
        assertTrue(status.paired)
        assertEquals("sidekick.example", status.serverHost)
        assertEquals(token, store.pairing?.token)
        assertEquals(origin, store.pairing?.serverOrigin)
        val call = http.calls.single()
        assertEquals("POST", call.method)
        assertEquals("$origin/companion/v1/pair", call.url)
        assertEquals("""{"pairing_secret":"$secret"}""", String(call.body!!))
        assertFalse(call.headers.containsKey("Authorization"))
    }

    @Test
    fun pairRefusesBadInputBeforeAnyRequest() {
        val http = ScriptedHttp { HttpResult(201, pairedBody()) }
        val client = client(MemoryStore(), http)
        assertEquals("invalid_server_url", code { client.pair("http://sidekick.example", secret) })
        assertEquals("invalid_server_url", code { client.pair(null, secret) })
        assertEquals("invalid_pairing_secret", code { client.pair(origin, "short") })
        assertEquals("invalid_pairing_secret", code { client.pair(origin, null) })
        assertEquals("invalid_pairing_secret", code { client.pair(origin, "$secret\"}") })
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun pairRefusesWhenAlreadyPaired() {
        val http = ScriptedHttp { HttpResult(201, pairedBody()) }
        assertEquals("already_paired", code { client(paired(), http).pair(origin, secret) })
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun aRejectedSecretSurfacesTheServersClosedCode() {
        val store = MemoryStore()
        val http = ScriptedHttp { HttpResult(401, """{"code":"pairing_invalid","title":"x"}""") }
        assertEquals("pairing_invalid", code { client(store, http).pair(origin, secret) })
        assertNull(store.pairing)
        val limited = ScriptedHttp { HttpResult(429, """{"code":"rate_limited"}""") }
        assertEquals("rate_limited", code { client(store, limited).pair(origin, secret) })
        val odd = ScriptedHttp { HttpResult(502, "<html>bad gateway</html>") }
        assertEquals("http_502", code { client(store, odd).pair(origin, secret) })
        val hostile = ScriptedHttp { HttpResult(400, """{"code":"Not A Code!"}""") }
        assertEquals("http_400", code { client(store, hostile).pair(origin, secret) })
    }

    @Test
    fun aMalformedPairAnswerIsNotStored() {
        val store = MemoryStore()
        assertEquals("bad_response", code { client(store, ScriptedHttp { HttpResult(201, "nope") }).pair(origin, secret) })
        assertEquals(
            "bad_response",
            code { client(store, ScriptedHttp { HttpResult(201, """{"access_token":"bad token"}""") }).pair(origin, secret) },
        )
        assertNull(store.pairing)
    }

    @Test
    fun ifTheCredentialCannotBeStoredTheServerDeviceIsRevoked() {
        val store = MemoryStore(failSave = true)
        val http = ScriptedHttp { call -> if (call.method == "POST") HttpResult(201, pairedBody()) else HttpResult(204, "") }
        assertEquals("secure_storage", code { client(store, http).pair(origin, secret) })
        assertEquals(listOf("POST", "DELETE"), http.calls.map { it.method })
        assertEquals("Bearer $token", http.calls[1].headers["Authorization"])
        assertNull(store.pairing)
    }

    @Test
    fun cleartextPairingToTheEmulatorHostWorksOnlyInTheDebugBuild() {
        val http = ScriptedHttp { HttpResult(201, pairedBody()) }
        val debug = client(MemoryStore(), http, cleartext = true).pair("http://10.0.2.2:8101", secret)
        assertEquals("10.0.2.2", debug.serverHost)
        assertEquals("http://10.0.2.2:8101/companion/v1/pair", http.calls.single().url)
        val release = client(MemoryStore(), http).let { code { it.pair("http://10.0.2.2:8101", secret) } }
        assertEquals("invalid_server_url", release)
    }

    // --- unpair ----------------------------------------------------------------------------------------------

    @Test
    fun unpairRevokesOnTheServerAndClearsThePhone() {
        val store = paired()
        val http = ScriptedHttp { HttpResult(204, "") }
        assertTrue(client(store, http).unpair())
        val call = http.calls.single()
        assertEquals("DELETE", call.method)
        assertEquals("$origin/companion/v1/device", call.url)
        assertEquals("Bearer $token", call.headers["Authorization"])
        assertNull(store.pairing)
    }

    @Test
    fun unpairClearsThePhoneEvenWhenTheServerCannotBeReached() {
        val store = paired()
        assertFalse(client(store, ScriptedHttp { throw CompanionException("network") }).unpair())
        assertNull(store.pairing)
        val refused = paired()
        assertFalse(client(refused, ScriptedHttp { HttpResult(500, "{}") }).unpair())
        assertNull(refused.pairing)
    }

    @Test
    fun unpairWithAnAlreadyInvalidCredentialCountsAsRevoked() {
        val store = paired()
        assertTrue(client(store, ScriptedHttp { HttpResult(401, "{}") }).unpair())
        assertNull(store.pairing)
    }

    @Test
    fun unpairWithoutAPairingDoesNothing() {
        val http = ScriptedHttp { HttpResult(204, "") }
        assertFalse(client(MemoryStore(), http).unpair())
        assertTrue(http.calls.isEmpty())
    }
}
