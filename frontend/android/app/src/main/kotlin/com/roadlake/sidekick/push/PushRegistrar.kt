package com.roadlake.sidekick.push

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.today.TextStore
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest

/** The two server routes of the push registration (`/companion/v1/push/subscription`). */
interface PushApi {
    fun put(endpoint: String): CompanionResponse

    fun delete(): CompanionResponse
}

/** The UnifiedPush distributor (the ntfy app) as the registrar sees it; the Android side is [UnifiedPushDistributor]. */
interface PushDistributor {
    /** Whether a distributor app is installed. */
    fun available(): Boolean

    /** Asks the distributor for an endpoint; it answers later through the push service (`onNewEndpoint`). */
    fun register()

    /** Tells the distributor this app no longer wants messages. */
    fun unregister()
}

enum class PermissionState { GRANTED, DENIED, PROMPT }

/** The notification permission (POST_NOTIFICATIONS, Android 13+): read it, and ask once. */
interface NotificationGate {
    fun state(): PermissionState

    /** Shows the system question and remembers that it was asked. */
    fun ask()
}

/** What `pushStatus()` tells the page. */
class PushStatus(val distributor: Boolean, val registered: Boolean, val permission: PermissionState)

enum class SyncOutcome { DONE, RETRY }

/**
 * The endpoint of this phone: the one the distributor gave, and the hash of the one the server last accepted. The
 * endpoint is a capability to wake this phone, so it is kept like the Today cache (the app's no-backup directory) and
 * is never logged; the server side only ever gets a hash comparison here.
 */
class PushState(private val store: TextStore) {
    @get:Synchronized
    val endpoint: String?
        get() = read().first

    @get:Synchronized
    val syncedHash: String?
        get() = read().second

    @Synchronized
    fun setEndpoint(endpoint: String?) = write(endpoint, read().second)

    @Synchronized
    fun setSynced(hash: String?) = write(read().first, hash)

    @Synchronized
    fun clear() = store.delete()

    /** [clear] that proves the endpoint note is gone: throws [IOException] when anything of it remains. */
    @Synchronized
    fun erase() = store.erase()

    @Synchronized
    fun inSync(): Boolean {
        val (endpoint, synced) = read()
        return if (endpoint == null) synced == null else hash(endpoint) == synced
    }

    private fun read(): Pair<String?, String?> {
        return try {
            val text = store.read() ?: return null to null
            val json = JSONObject(text)
            json.optString("endpoint").ifEmpty { null } to json.optString("synced").ifEmpty { null }
        } catch (_: JSONException) {
            null to null
        } catch (_: IOException) {
            null to null // unreadable counts as unknown: the registration is redone, which is idempotent
        }
    }

    private fun write(endpoint: String?, synced: String?) {
        if (endpoint == null && synced == null) {
            store.delete()
            return
        }
        try {
            store.write(JSONObject().put("endpoint", endpoint ?: "").put("synced", synced ?: "").toString())
        } catch (_: IOException) {
            // Not saved: the next start asks the distributor again and the registration is redone.
        }
    }

    companion object {
        fun hash(endpoint: String): String = MessageDigest.getInstance("SHA-256").digest(endpoint.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}

/**
 * Keeps the server's idea of this phone's push endpoint equal to the distributor's. The logic is a reconciliation,
 * [sync]: wanted state (the endpoint the distributor gave, or none) against what the server last accepted. A new
 * endpoint gives `PUT`; no endpoint (the distributor unregistered the app) or an ended pairing gives `DELETE`. Events
 * only record the wanted state and ask for a [sync], which runs where a network and retry exist (a worker).
 *
 * Free of Android types and logging, so it is unit tested on the JVM. Nothing here names an endpoint in a message.
 *
 * A [sync] belongs to the pairing it began under ([PairingGeneration]): its requests are pinned to it, and "the server
 * accepted this endpoint" is recorded only while that pairing is current, so the answer of an old pairing's server never
 * marks the next pairing as registered.
 */
class PushRegistrar(
    private val api: PushApi,
    private val state: PushState,
    private val isPaired: () -> Boolean,
    private val distributor: PushDistributor,
    private val notifications: NotificationGate,
    private val generation: PairingGeneration = PairingGeneration(),
) {
    /**
     * At start and after pairing: if paired and a distributor exists, ask once for the notification permission and ask
     * the distributor for an endpoint. With no distributor nothing happens (the page shows a calm note).
     *
     * @return whether a [sync] is needed now (an earlier registration is not yet accepted by the server).
     */
    fun ensure(): Boolean {
        if (!isPaired()) return false
        if (distributor.available()) {
            if (notifications.state() == PermissionState.PROMPT) notifications.ask()
            distributor.register()
        }
        return !state.inSync()
    }

    /** The distributor gave this app an endpoint. Returns whether a [sync] is needed. */
    fun onNewEndpoint(endpoint: String): Boolean {
        state.setEndpoint(endpoint)
        return !state.inSync()
    }

    /** The distributor ended the registration (the user removed the app from it, or the distributor was removed). */
    fun onUnregistered(): Boolean {
        state.setEndpoint(null)
        return !state.inSync()
    }

    fun sync(): SyncOutcome {
        val captured = generation.current()
        return generation.pinned(captured) { syncFor(captured) }
    }

    private fun syncFor(captured: Long): SyncOutcome {
        if (!isPaired()) {
            generation.runIfCurrent(captured) { state.setSynced(null) }
            return SyncOutcome.DONE
        }
        val endpoint = state.endpoint
        return try {
            if (endpoint == null) syncRemoval(captured) else syncEndpoint(captured, endpoint)
        } catch (e: CompanionException) {
            // No pairing any more is final; no answer from the server is tried again.
            if (e.code == "not_paired") SyncOutcome.DONE else SyncOutcome.RETRY
        }
    }

    private fun syncEndpoint(captured: Long, endpoint: String): SyncOutcome {
        val hash = PushState.hash(endpoint)
        if (state.syncedHash == hash) return SyncOutcome.DONE
        val status = api.put(endpoint).status
        return when {
            status in 200..299 -> {
                // The hash of what was sent, not of the current endpoint: a newer one that arrived meanwhile stays unsynced.
                generation.runIfCurrent(captured) { state.setSynced(hash) }
                SyncOutcome.DONE
            }

            // 401: the pairing is gone (the client has already cleared everything). Other 4xx: the server refuses this
            // endpoint (a host it does not allow); trying the same again changes nothing, the next start tries anew.
            status in 400..499 -> SyncOutcome.DONE

            else -> SyncOutcome.RETRY
        }
    }

    private fun syncRemoval(captured: Long): SyncOutcome {
        if (state.syncedHash == null) return SyncOutcome.DONE
        val status = api.delete().status
        if (status >= 500) return SyncOutcome.RETRY
        // 204, 404 (nothing there) and 401 (no pairing) all mean the server has nothing for this phone.
        generation.runIfCurrent(captured) { state.setSynced(null) }
        return SyncOutcome.DONE
    }

    /** Unpair: the subscription is removed first, with the credential still valid. Best effort; the server also ends it with the pairing. */
    fun beforeUnpair() {
        if (state.syncedHash == null) return
        try {
            api.delete()
        } catch (_: CompanionException) {
            // The phone is cleared in any case; the server drops the subscription when it revokes the device.
        }
    }

    /** Every end of a pairing (unpair, a 401, a new pairing): the endpoint belongs to the pairing, so it goes. */
    @Throws(IOException::class)
    fun clearLocal() {
        state.erase()
        try {
            distributor.unregister()
        } catch (_: RuntimeException) {
            // A distributor that is gone has nothing to unregister from.
        }
    }

    fun status(): PushStatus {
        val endpoint = state.endpoint
        return PushStatus(
            distributor = distributor.available(),
            registered = endpoint != null && state.syncedHash == PushState.hash(endpoint),
            permission = notifications.state(),
        )
    }
}
