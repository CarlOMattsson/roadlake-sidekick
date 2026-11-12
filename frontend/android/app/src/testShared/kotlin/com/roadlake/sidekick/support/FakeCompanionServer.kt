package com.roadlake.sidekick.support

import com.roadlake.sidekick.today.item
import com.roadlake.sidekick.today.todayPage
import org.json.JSONObject

/**
 * The routes of the companion API the phone uses (`/companion/v1/...`), with the server's rules that matter to the app:
 * a pairing secret is single use, every other route needs the current bearer token (an older one is valid only until the
 * new one is first used, as the real server's grace time), a completion is applied once per idempotency key, and a
 * version that changed elsewhere is a 409. Over a [LocalHttpServer], so the app's own transport talks to it.
 *
 * Simulated, not the real backend: it proves the app's side of the contract, nothing about the server.
 */
class FakeCompanionServer : AutoCloseable {
    class Task(val id: String, val title: String, var version: Int = 1, var done: Boolean = false)

    /** Every route answers by closing the connection without a word while this is true (an unreachable server). */
    @Volatile
    var offline = false

    /**
     * Requests to this path are handled, but their answers are lost (the connection closes before one is sent). Not one-shot:
     * the JDK client resends a body-less POST once on an empty answer, and a phone cannot tell either.
     */
    @Volatile
    var loseAnswersTo: String? = null

    /** The `renew_after` the server gives out; a renewal before it (the phone's clock is 2026-11-08T12:00:00Z) is a 409 `renewal_not_due`. */
    @Volatile
    var renewAfter = NOT_DUE

    /** The license state `GET /companion/v1/license` answers (`licensed`, `expired`, `unlicensed`); null is a server without the route (404). */
    @Volatile
    var licenseState: String? = null

    private val secrets = mutableSetOf<String>()
    private val tasks = LinkedHashMap<String, Task>()
    private val appliedKeys = mutableSetOf<String>()
    private var current: String? = null
    private var previous: String? = null
    private var issued = 0
    private var applied = 0
    private val http = LocalHttpServer(::handle).start()

    val origin: String get() = http.origin
    val requests get() = http.requests

    /** Makes a pairing secret the phone can exchange once. */
    @Synchronized
    fun issuePairing(secret: String) {
        secrets += secret
    }

    @Synchronized
    fun addTask(id: String, title: String) {
        tasks[id] = Task(id, title)
    }

    /** Someone else changed the task (a new version): a completion sent with the old one is a conflict. */
    @Synchronized
    fun editElsewhere(id: String) {
        tasks.getValue(id).version++
    }

    /** The token the phone must send now. */
    @get:Synchronized
    val validToken: String? get() = current

    /** How many completions took effect (a replay under the same key does not count). */
    @get:Synchronized
    val completionsApplied: Int get() = applied

    @get:Synchronized
    val openTasks: List<String> get() = tasks.values.filterNot { it.done }.map { it.id }

    /** The owner revokes the device in Control: every token stops working. */
    @Synchronized
    fun revokeDevice() {
        current = null
        previous = null
    }

    /** Requests of [method] to [path] (without the query), oldest first. */
    fun requestsTo(method: String, path: String) = requests.filter { it.method == method && it.path == path }

    override fun close() = http.close()

    @Synchronized
    private fun handle(request: ServerRequest): ServerReply? {
        if (offline) return null
        val reply = route(request)
        if (loseAnswersTo == request.path) return null
        return reply
    }

    private fun route(request: ServerRequest): ServerReply {
        if (request.method == "POST" && request.path == "/companion/v1/pair") return pair(request)
        if (!authorized(request.headers["authorization"])) return problem(401, "unauthorized")
        return when {
            request.method == "GET" && request.path == "/companion/v1/device" -> ServerReply(200, deviceAnswer())

            request.method == "DELETE" && request.path == "/companion/v1/device" -> {
                revokeDevice()
                ServerReply(204)
            }

            request.method == "POST" && request.path == "/companion/v1/device/renew" -> renew()

            request.method == "GET" && request.path == "/companion/v1/work/today" -> today()

            request.method == "GET" && request.path == "/companion/v1/license" -> license()

            request.method == "POST" && COMPLETE.matches(request.path) -> complete(request)

            else -> problem(404, "not_found")
        }
    }

    private fun pair(request: ServerRequest): ServerReply {
        val secret = JSONObject(request.body).optString("pairing_secret")
        if (!secrets.remove(secret)) return problem(401, "pairing_invalid")
        rotate()
        return ServerReply(201, deviceAnswer())
    }

    private fun renew(): ServerReply {
        if (renewAfter >
            NOW_ISO
        ) {
            return ServerReply(409, JSONObject().put("reason", "renewal_not_due").put("renew_after", renewAfter).toString())
        }
        rotate()
        renewAfter = NOT_DUE
        return ServerReply(200, deviceAnswer())
    }

    private fun today(): ServerReply =
        ServerReply(200, todayPage(*tasks.values.filterNot { it.done }.map { item(it.id, it.title, it.version) }.toTypedArray()))

    private fun license(): ServerReply =
        licenseState?.let { ServerReply(200, JSONObject().put("api_version", "1").put("state", it).toString()) }
            ?: problem(404, "not_found")

    private fun complete(request: ServerRequest): ServerReply {
        val id = COMPLETE.matchEntire(request.path)!!.groupValues[1]
        val key = request.headers["idempotency-key"] ?: return problem(400, "idempotency_key_required")
        val task = tasks[id] ?: return problem(404, "not_found")
        if (key in appliedKeys) return ServerReply(200, "{}")
        if (JSONObject(request.body).getInt("version") != task.version) return problem(409, "version_conflict")
        task.done = true
        applied++
        appliedKeys += key
        return ServerReply(200, "{}")
    }

    private fun authorized(header: String?): Boolean {
        val token = header?.removePrefix("Bearer ")?.takeIf { header.startsWith("Bearer ") } ?: return false
        if (token == current) {
            previous = null // the new token is in use: the old one is done
            return true
        }
        return token == previous
    }

    private fun rotate() {
        previous = current
        current = "rsc_fake_token_%04d_abcdefghijklmnop".format(++issued)
    }

    private fun deviceAnswer(): String = JSONObject()
        .put("token_type", "Bearer")
        .put("access_token", current)
        .put(
            "device",
            JSONObject().put("id", "d1").put("label", "Test phone").put("created_at", "2026-10-08T12:00:00Z")
                .put("expires_at", "2027-02-08T12:00:00Z").put("renew_after", renewAfter),
        )
        .put("enabled_rooms", org.json.JSONArray(listOf("work")))
        .put("push_enabled", true)
        .toString()

    private fun problem(status: Int, code: String) = ServerReply(status, JSONObject().put("code", code).toString())

    private companion object {
        val COMPLETE = Regex("/companion/v1/tasks/([0-9a-f-]{36})/complete")
        const val NOW_ISO = "2026-11-08T12:00:00Z"
        const val NOT_DUE = "2026-12-08T12:00:00Z"
    }
}
