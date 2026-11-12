package com.roadlake.sidekick.companion

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

/**
 * The address of the paired Sidekick server: an origin (scheme, host, optional port) and nothing else. HTTPS only.
 * The debug build also accepts http for the hosts a developer machine is reached by from an emulator
 * ([LOCAL_CLEARTEXT_HOSTS]); the release build never does. Credentials in the URL, a path, a query or a fragment
 * are refused, so a token is never sent anywhere but to this origin's `/companion/v1/` routes.
 */
class ServerUrl private constructor(val origin: String, val host: String) {
    companion object {
        /** Reachable only from the same machine; http is allowed for these in the debug build. */
        val LOCAL_CLEARTEXT_HOSTS: Set<String> = setOf("10.0.2.2", "localhost", "127.0.0.1")

        private const val MAX_LENGTH = 200

        fun parse(raw: String, allowLocalCleartext: Boolean): ServerUrl {
            val text = raw.trim()
            if (text.isEmpty() || text.length > MAX_LENGTH) throw CompanionException("invalid_server_url")
            val uri = try {
                URI(text)
            } catch (_: URISyntaxException) {
                throw CompanionException("invalid_server_url")
            }
            val scheme = uri.scheme?.lowercase(Locale.ROOT)
            val host = uri.host?.lowercase(Locale.ROOT)
            if (host.isNullOrEmpty() || uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null) {
                throw CompanionException("invalid_server_url")
            }
            if (uri.rawPath != null && uri.rawPath != "" && uri.rawPath != "/") throw CompanionException("invalid_server_url")
            if (uri.port != -1 && uri.port !in 1..65535) throw CompanionException("invalid_server_url")
            val secure = when (scheme) {
                "https" -> true
                "http" -> false
                else -> throw CompanionException("invalid_server_url")
            }
            if (!secure && !(allowLocalCleartext && host in LOCAL_CLEARTEXT_HOSTS)) {
                throw CompanionException("invalid_server_url")
            }
            val port = if (uri.port == -1) "" else ":${uri.port}"
            return ServerUrl("$scheme://$host$port", host)
        }
    }
}
