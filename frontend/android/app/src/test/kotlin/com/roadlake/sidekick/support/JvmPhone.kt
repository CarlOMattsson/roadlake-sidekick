package com.roadlake.sidekick.support

import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingStore
import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.today.FileTextStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Stands in for the Keystore-encrypted store on the JVM, which has no Android Keystore: the same record in a file that
 * outlives a [PhoneProcess], so a restart reads back what was stored. The instrumented tests use the real store.
 */
class FilePairingStore(private val file: File) : PairingStore {
    override fun load(): Pairing? {
        if (!file.isFile) return null
        val json = JSONObject(file.readText())
        return Pairing(
            serverOrigin = json.getString("origin"),
            token = json.getString("token"),
            deviceLabel = json.optString("label"),
            pairedAt = json.optString("pairedAt"),
            expiresAt = json.optString("expiresAt"),
            renewAfter = json.optString("renewAfter"),
            enabledRooms = json.optJSONArray("rooms")?.let { rooms -> List(rooms.length()) { rooms.getString(it) } },
            ownerTimeZone = json.optString("zone").ifEmpty { null },
            pushEnabled = json.opt("push") as? Boolean,
        )
    }

    override fun save(pairing: Pairing) {
        file.writeText(
            JSONObject()
                .put("origin", pairing.serverOrigin)
                .put("token", pairing.token)
                .put("label", pairing.deviceLabel)
                .put("pairedAt", pairing.pairedAt)
                .put("expiresAt", pairing.expiresAt)
                .put("renewAfter", pairing.renewAfter)
                .put("rooms", pairing.enabledRooms?.let(::JSONArray))
                .put("zone", pairing.ownerTimeZone)
                .put("push", pairing.pushEnabled)
                .toString(),
        )
    }

    override fun clear() {
        file.delete()
    }
}

/** A phone on the JVM: a fake companion server, the phone's files in [directory], and a clock the test moves. */
class JvmPhone(private val directory: File) : AutoCloseable {
    val server = FakeCompanionServer()
    var clock: Long = IsoInstant.parse("2026-11-08T12:00:00Z")!!
    private val pairings = FilePairingStore(File(directory, "pairing.json"))

    /** While true the cache file's final rename fails, as a full or failing disk would: its write throws an IOException. */
    var failCacheWrites = false

    var process = start()
        private set

    /** The process was killed and started again: new objects over the files the old ones wrote. */
    fun restart(): PhoneProcess {
        process = start()
        return process
    }

    /** Issues a pairing secret on the server and exchanges it, as the owner does in the app. */
    fun pair() {
        server.issuePairing(SECRET)
        process.client.pair(server.origin, SECRET)
    }

    override fun close() = server.close()

    private fun start() = PhoneProcess(
        pairings,
        { name ->
            FileTextStore(
                File(directory, name),
                rename = { from, to -> !(failCacheWrites && name == "today-cache.json") && from.renameTo(to) },
                syncDirectory = {},
            )
        },
        { clock },
    )

    companion object {
        const val SECRET = "pairing_secret_0123456789"
    }
}
