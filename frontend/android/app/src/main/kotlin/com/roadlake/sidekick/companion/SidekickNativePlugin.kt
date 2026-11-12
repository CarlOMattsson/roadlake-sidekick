package com.roadlake.sidekick.companion

import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.roadlake.sidekick.SidekickRuntime
import com.roadlake.sidekick.SystemLinks
import com.roadlake.sidekick.push.PushChannels
import com.roadlake.sidekick.today.OutboxKind
import com.roadlake.sidekick.widget.TodaySync
import com.roadlake.sidekick.widget.WidgetLocale
import com.roadlake.sidekick.widget.WidgetLocaleStore
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * The Capacitor plugin `SidekickNative` (frontend/src/mobile/sidekick-native.ts is its TypeScript contract). It only
 * converts between the bridge's types and [CompanionClient], which holds the rules. Methods run on their own small
 * thread pool: Capacitor's shared plugin thread must not wait on the network.
 *
 * Nothing is logged here, and a rejection carries only a closed code, never a message built from request or response
 * content.
 *
 * Event `pairingLost`: the server refused the stored credential (401), here or in the widget's background work. The
 * credential is already removed, and so are the Today cache and the widget's outbox.
 *
 * The home-screen widget (com.roadlake.sidekick.widget) shares this plugin's [CompanionClient] through [SidekickRuntime]. The
 * page tells the widget that Today changed with `widgetRefresh`; the plugin also notices a completed or reopened Task
 * in `request` itself and when the app comes to the foreground. `setLocale` gives it the app's language.
 *
 * Offline (the shopping room in a shop without coverage): `request` answers a shopping, Agenda or Task detail read that got no answer from the
 * offline copy, with `cachedAt`; `queuePurchase` and `queueShoppingAdd` put a purchase, or items to add, that got no
 * answer in the shared outbox, which the widget's sync sends; event `queueChanged` fires after every run of that sync, so the page reads again.
 * A shopping write that expired or that the server refused stays in the outbox as failed (`queuedWrites().failed`); the page shows it
 * and the user retries it (`retryQueuedWrite`) or removes it (`removeQueuedWrite`).
 */
@CapacitorPlugin(name = "SidekickNative")
class SidekickNativePlugin : Plugin() {
    private lateinit var client: CompanionClient
    private var executor: ExecutorService? = null
    private val onPairingLost: () -> Unit = { notifyListeners(EVENT_PAIRING_LOST, JSObject()) }
    private val onOutboxRan: () -> Unit = { notifyListeners(EVENT_QUEUE_CHANGED, JSObject()) }

    override fun load() {
        val runtime = SidekickRuntime.get(context)
        client = runtime.client
        runtime.addPairingLostListener(onPairingLost)
        runtime.addOutboxListener(onOutboxRan)
        executor = Executors.newFixedThreadPool(THREADS) { task ->
            Thread(task, "sidekick-native").apply { isDaemon = true }
        }
    }

    override fun handleOnResume() {
        super.handleOnResume()
        // Push: a distributor may have been installed or the endpoint lost since the last time.
        SidekickRuntime.get(context).ensurePush()
        // Read Today again for the widget unless it was read a moment ago.
        TodaySync.onAppForeground(context)
    }

    override fun handleOnDestroy() {
        SidekickRuntime.get(context).removePairingLostListener(onPairingLost)
        SidekickRuntime.get(context).removeOutboxListener(onOutboxRan)
        executor?.shutdownNow()
        super.handleOnDestroy()
    }

    @PluginMethod
    fun request(call: PluginCall) = run(call) {
        val query = queryOf(call)
        val body = objectArgument(call, "body")?.toString()
        val method = call.getString("method")
        val path = call.getString("path")
        // Read before the request starts: a failure without an answer hands it to the page (see queuePurchase).
        val generation = SidekickRuntime.get(context).today.pairingGeneration()
        val answer = try {
            SidekickRuntime.get(context).offlineReads.request(
                method = method,
                path = path,
                query = query,
                bodyJson = body,
                idempotencyKey = call.getString("idempotencyKey"),
            )
        } catch (e: CompanionException) {
            throw if (e.code == "network" || e.code == "timeout") CompanionException(e.code, e.beforeSend, generation) else e
        }
        val response = answer.response
        if (method == "POST" && path != null && TASK_WRITE.matches(path) && response.status in 200..299) {
            TodaySync.requestSync(context)
        }
        val result = JSObject().put("status", response.status).put("body", parseJson(response.body))
        answer.cachedAtMillis?.let { result.put("cachedAt", it) }
        result
    }

    /**
     * Queues a shopping purchase the page could not send: `{ itemId, version, purchased, idempotencyKey }` (the key of
     * the attempt that got no answer) and the `generation` that attempt's rejection carried: the purchase is queued only
     * while that pairing is still the current one, so a late failure from before an unpair never reaches the queue of a
     * new pairing. Resolves `{ queued, purchased? }`: `purchased` is the state that will be sent (an
     * entry already queued for the item wins). The queue is sent as soon as a network exists, also with the app closed.
     */
    @PluginMethod
    fun queuePurchase(call: PluginCall) = run(call) {
        val itemId = call.getString("itemId")?.lowercase()
        val version = call.getInt("version")
        val purchased = call.getBoolean("purchased")
        val key = RequestPolicy.checkIdempotencyKey(call.getString("idempotencyKey"))
        val generation = call.data.optLong("generation", -1L)
        if (itemId == null || !UUID.matches(itemId) || version == null || version < 1 || purchased == null || key == null ||
            generation < 0
        ) {
            throw CompanionException("bad_request")
        }
        val queued = SidekickRuntime.get(context).today.enqueuePurchase(generation, itemId, version, purchased, key)
        val entry = queued.entry
        if (entry == null) {
            JSObject().put("queued", false)
        } else {
            TodaySync.requestSync(context)
            JSObject().put("queued", true).put("purchased", entry.purchased)
        }
    }

    /**
     * Queues items the page could not add: `{ listId, body: { items, merge_duplicates? }, idempotencyKey }` (the key of the
     * attempt that got no answer) and the `generation` that attempt's rejection carried, bound as for [queuePurchase].
     * Resolves `{ queued }`; the same key queued again is the same add.
     */
    @PluginMethod
    fun queueShoppingAdd(call: PluginCall) = run(call) {
        val listId = call.getString("listId")?.lowercase()
        val body = objectArgument(call, "body")
        val key = RequestPolicy.checkIdempotencyKey(call.getString("idempotencyKey"))
        val generation = call.data.optLong("generation", -1L)
        val items = body?.optJSONArray("items")
        if (listId == null || !UUID.matches(
                listId,
            ) || body == null || items == null || items.length() < 1 || items.length() > MAX_ADD_ITEMS ||
            key == null || generation < 0
        ) {
            throw CompanionException("bad_request")
        }
        val queued = SidekickRuntime.get(context).today.enqueueShoppingAdd(generation, listId, body.toString(), key)
        if (queued.entry == null) {
            JSObject().put("queued", false)
        } else {
            TodaySync.requestSync(context)
            JSObject().put("queued", true)
        }
    }

    /**
     * The writes waiting in the queue: `{ purchases: [{ itemId, purchased }], adds: [{ listId, key, queuedAt, items,
     * mergeDuplicates }], failed: [{ key, kind: "add" | "purchase", reason: "expired" | "rejected", queuedAt, listId? / items? for
     * an add, itemId? / purchased? for a purchase }] }`. `failed` are the writes that will not be sent unless the user retries
     * them ([retryQueuedWrite]) or removes them ([removeQueuedWrite]). `completions: [{ taskId, queuedAt }]` are the Task
     * ticks (from the widget or the app) not yet sent, so a room can draw those Tasks as done. No network.
     */
    @PluginMethod
    fun queuedWrites(call: PluginCall) = run(call) {
        val today = SidekickRuntime.get(context).today
        val purchases = JSONArray()
        for (entry in today.queuedPurchases()) {
            purchases.put(JSObject().put("itemId", entry.subjectId).put("purchased", entry.purchased))
        }
        val adds = JSONArray()
        for (entry in today.queuedShoppingAdds()) {
            val body = try {
                JSONObject(entry.payload ?: continue)
            } catch (_: JSONException) {
                continue // not ours to show; the drain still sends it and the server decides
            }
            adds.put(
                JSObject()
                    .put("listId", entry.subjectId)
                    .put("key", entry.idempotencyKey)
                    .put("queuedAt", entry.createdAtMillis)
                    .put("items", body.optJSONArray("items") ?: JSONArray())
                    .put("mergeDuplicates", body.optBoolean("merge_duplicates", false)),
            )
        }
        val failed = JSONArray()
        for (entry in today.failedShoppingWrites()) {
            val row = JSObject()
                .put("key", entry.idempotencyKey)
                .put("reason", entry.failure?.wire)
                .put("queuedAt", entry.createdAtMillis)
                .put("retryable", today.canRetryFailedWrite(entry))
            if (entry.kind == OutboxKind.SHOPPING_ADD) {
                val items = try {
                    JSONObject(entry.payload ?: "{}").optJSONArray("items")
                } catch (_: JSONException) {
                    null
                }
                row.put("kind", "add").put("listId", entry.subjectId).put("items", items ?: JSONArray())
            } else {
                row.put("kind", "purchase").put("itemId", entry.subjectId).put("purchased", entry.purchased)
            }
            failed.put(row)
        }
        val completions = JSONArray()
        for (entry in today.queuedCompletions()) {
            completions.put(JSObject().put("taskId", entry.subjectId).put("queuedAt", entry.createdAtMillis))
        }
        JSObject().put("purchases", purchases).put("adds", adds).put("failed", failed).put("completions", completions)
    }

    /** Puts a failed write (by its `key`) back in the queue to be sent again; resolves `{ retried }`. */
    @PluginMethod
    fun retryQueuedWrite(call: PluginCall) = run(call) {
        val key = RequestPolicy.checkIdempotencyKey(call.getString("key")) ?: throw CompanionException("bad_request")
        val retried = SidekickRuntime.get(context).today.retryFailedWrite(key)
        if (retried) TodaySync.requestSync(context)
        JSObject().put("retried", retried)
    }

    /** Removes a failed write (by its `key`) for good; resolves `{ removed }`. */
    @PluginMethod
    fun removeQueuedWrite(call: PluginCall) = run(call) {
        val key = RequestPolicy.checkIdempotencyKey(call.getString("key")) ?: throw CompanionException("bad_request")
        JSObject().put("removed", SidekickRuntime.get(context).today.discardFailedWrite(key))
    }

    /** The page says Today changed. Never fails: the widget is a convenience, not part of the page's work. */
    @PluginMethod
    fun widgetRefresh(call: PluginCall) {
        TodaySync.requestSync(context)
        call.resolve()
    }

    /**
     * The app's language ("sv" or "en", its own setting) for the widget's texts. Saved, then the widget is redrawn. Any
     * other tag is a bad request and changes nothing.
     */
    @PluginMethod
    fun setLocale(call: PluginCall) {
        val tag = WidgetLocale.parse(call.getString("tag"))
        if (tag == null) {
            call.reject("bad_request", "bad_request")
            return
        }
        WidgetLocaleStore(context).set(tag)
        PushChannels.create(context)
        TodaySync.redraw(context)
        call.resolve()
    }

    @PluginMethod
    fun pair(call: PluginCall) = run(call) {
        val status = statusObject(client.pair(call.getString("serverUrl"), call.getString("pairingSecret")))
        SidekickRuntime.get(context).ensurePush()
        status
    }

    /** Whether push can work: a distributor (the ntfy app) is installed, the server has the endpoint, the permission. */
    @PluginMethod
    fun pushStatus(call: PluginCall) = run(call) {
        val push = SidekickRuntime.get(context).push.status()
        JSObject()
            .put("distributor", push.distributor)
            .put("registered", push.registered)
            .put("permission", push.permission.name.lowercase())
    }

    /** Opens Android's notification settings for Sidekick (the permission was refused, so only the owner can turn it on). */
    @PluginMethod
    fun openNotificationSettings(call: PluginCall) = onMainThread(call) { SystemLinks.openNotificationSettings(it) }

    /** Asks for the notification permission and the distributor's endpoint again (the question is still open). */
    @PluginMethod
    fun requestNotificationPermission(call: PluginCall) {
        SidekickRuntime.get(context).ensurePush()
        call.resolve()
    }

    /** Opens the ntfy app's store page: the market app first, F-Droid's page in a browser as the fallback. */
    @PluginMethod
    fun openNtfyInstall(call: PluginCall) = onMainThread(call) {
        SystemLinks.openStore(it, SystemLinks.NTFY_PACKAGE, SystemLinks.NTFY_FALLBACK_URI)
    }

    /**
     * The device as the phone knows it: `{ paired, name?, pairedAt?, expiresAt?, enabledRooms?, ownerTimeZone?, pushEnabled? }` (ISO 8601). Read locally and refreshed
     * from `GET /device` when the server answers; without a network the stored values are returned.
     */
    @PluginMethod
    fun deviceStatus(call: PluginCall) = run(call) {
        val device = client.deviceStatus()
        val result = JSObject().put("paired", device.paired)
        device.name?.let { result.put("name", it) }
        device.pairedAt?.let { result.put("pairedAt", it) }
        device.expiresAt?.let { result.put("expiresAt", it) }
        device.enabledRooms?.let { result.put("enabledRooms", JSONArray(it)) }
        device.ownerTimeZone?.let { result.put("ownerTimeZone", it) }
        device.pushEnabled?.let { result.put("pushEnabled", it) }
        result
    }

    /**
     * Asks the server to push a test reminder to this phone: `{ outcome, retryAfterSeconds? }` with outcome one of
     * `queued | rate_limited | no_subscription | disabled | offline | unpaired`. Never rejects for those cases.
     */
    @PluginMethod
    fun sendTestPush(call: PluginCall) = run(call) {
        val result = client.sendTestPush()
        val answer = JSObject().put("outcome", result.outcome.wire)
        result.retryAfterSeconds?.let { answer.put("retryAfterSeconds", it) }
        answer
    }

    @PluginMethod
    fun status(call: PluginCall) = run(call) { statusObject(client.status()) }

    @PluginMethod
    fun unpair(call: PluginCall) = run(call) { JSObject().put("serverRevoked", client.unpair()) }

    private fun run(call: PluginCall, work: () -> JSObject) {
        val pool = executor
        if (pool == null) {
            call.reject("unavailable", "unavailable")
            return
        }
        pool.execute {
            try {
                call.resolve(work())
            } catch (e: CompanionException) {
                val generation = e.generation
                if (generation ==
                    null
                ) {
                    call.reject(e.code, e.code)
                } else {
                    call.reject(e.code, e.code, JSObject().put("generation", generation))
                }
            } catch (_: Exception) {
                call.reject("internal", "internal")
            }
        }
    }

    /** Starts an activity on the main thread; rejects with "unavailable" when no app could open it. */
    private fun onMainThread(call: PluginCall, open: (android.content.Context) -> Boolean) {
        bridge.executeOnMainThread {
            if (open(activity ?: context)) call.resolve() else call.reject("unavailable", "unavailable")
        }
    }

    private fun objectArgument(call: PluginCall, name: String): JSObject? {
        if (!call.data.has(name) || call.data.isNull(name)) return null
        return call.getObject(name) ?: throw CompanionException("bad_request")
    }

    /** `query`: strings or lists of strings by key; anything else is a bad request. */
    private fun queryOf(call: PluginCall): Map<String, List<String>>? {
        val raw = objectArgument(call, "query") ?: return null
        val query = LinkedHashMap<String, List<String>>()
        for (key in raw.keys()) {
            query[key] = when (val value = raw.opt(key)) {
                is String -> listOf(value)
                is JSONArray -> List(value.length()) { value.opt(it) as? String ?: throw CompanionException("bad_request") }
                else -> throw CompanionException("bad_request")
            }
        }
        return query
    }

    private fun parseJson(text: String): Any = if (text.isBlank()) {
        JSONObject.NULL
    } else {
        try {
            JSONTokener(text).nextValue() ?: JSONObject.NULL
        } catch (_: JSONException) {
            JSONObject.NULL
        }
    }

    private fun statusObject(status: PairingStatus): JSObject {
        val result = JSObject().put("paired", status.paired)
        status.serverHost?.let { result.put("serverHost", it) }
        status.deviceLabel?.let { result.put("deviceLabel", it) }
        status.enabledRooms?.let { result.put("enabledRooms", JSONArray(it)) }
        status.ownerTimeZone?.let { result.put("ownerTimeZone", it) }
        return result
    }

    private companion object {
        const val EVENT_PAIRING_LOST = "pairingLost"
        const val EVENT_QUEUE_CHANGED = "queueChanged"

        val UUID = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        const val THREADS = 4

        /** The server takes at most 50 items per add (`AddItemsBody`). */
        const val MAX_ADD_ITEMS = 50

        /** A completion or reopening of one Task, which changes what Today lists. */
        val TASK_WRITE = Regex("/companion/v1/tasks/[A-Za-z0-9_-]{1,64}/(complete|reopen)")
    }
}
