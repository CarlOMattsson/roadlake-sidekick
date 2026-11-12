package com.roadlake.sidekick.push

import org.json.JSONException
import org.json.JSONObject

/**
 * What a push message can say. The message never carries content (D-078): only a fixed kind, `{"k":"w"}`
 * (something changed elsewhere: sync quietly) or `{"k":"r"}` (there are reminders to show). The phone fetches the
 * content itself from the server with its own credential.
 */
enum class PushKind { WAKE, REMINDERS }

object PushPayload {
    /** A real message is nine bytes; anything much larger is not ours and is not even parsed. */
    private const val MAX_BYTES = 1024

    /** The kind of a message, or null for anything that is not a known one (it is ignored, never an error). */
    fun parse(content: ByteArray?): PushKind? {
        if (content == null || content.isEmpty() || content.size > MAX_BYTES) return null
        return try {
            val json = JSONObject(String(content, Charsets.UTF_8))
            when (json.opt("k")) {
                "w" -> PushKind.WAKE
                "r" -> PushKind.REMINDERS
                else -> null
            }
        } catch (_: JSONException) {
            null
        }
    }
}

/** Routes a message to what the app does about it. Pure, so the routing is tested on the JVM. */
class PushReceiver(private val onWake: () -> Unit, private val onReminders: () -> Unit) {
    fun handle(content: ByteArray?) {
        when (PushPayload.parse(content)) {
            PushKind.WAKE -> onWake()
            PushKind.REMINDERS -> onReminders()
            null -> Unit
        }
    }
}
