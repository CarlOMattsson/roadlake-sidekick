package com.roadlake.sidekick.companion

import java.net.URLEncoder

/**
 * What the page may ask the native side to send: the closed shape of `SidekickNative.request`. JavaScript names a
 * route under `/companion/v1/`, a query and a JSON body; it never names a host, a header or a scheme. Anything that
 * is not plainly a companion route is refused before a connection is opened.
 */
object RequestPolicy {
    /** The allowed path prefixes. A list so that a later versioned prefix is added here, reviewed, and nowhere else. */
    val ALLOWED_PREFIXES: List<String> = listOf("/companion/v1/")

    /** Routes with their own plugin method; `request` never reaches them (pairing has no token yet, unpair is explicit). */
    private val DEDICATED_ROUTES: Set<String> = setOf("pair", "device")

    val METHODS: Set<String> = setOf("GET", "POST", "PUT")

    /** The only routes the page may PUT to: the license key (see docs/decisions/log.md D-083). Any other PUT is refused, however well formed. */
    val PUT_PATHS: Set<String> = setOf("/companion/v1/license")

    /**
     * Matches the largest body a companion route takes (journal writes, `MAX_JOURNAL_BODY_BYTES` in the backend); each
     * route keeps its own, lower cap there. The journal form measures its JSON body against this same number.
     */
    const val MAX_BODY_BYTES = 256 * 1024
    private const val MAX_PATH_LENGTH = 200
    private const val MAX_SEGMENTS = 6
    private const val MAX_QUERY_PAIRS = 40
    private const val MAX_QUERY_VALUE_LENGTH = 512

    /**
     * The longest pagination cursor the backend accepts and issues (`MAX_CURSOR_LENGTH` in `shared/types/core.py`):
     * a cursor seals a text sort key of up to 200 characters, 4 bytes each, so it is longer than any other value.
     */
    const val MAX_CURSOR_LENGTH = 2048

    private val SEGMENT = Regex("[A-Za-z0-9_-]{1,64}")
    private val QUERY_KEY = Regex("[A-Za-z0-9_]{1,40}")
    private val IDEMPOTENCY_KEY = Regex("[A-Za-z0-9._:-]{8,128}")

    /** The method, when it is GET or POST, or PUT to one of [PUT_PATHS] exactly; otherwise `bad_request`. */
    fun checkMethod(method: String?, path: String?): String {
        if (method == null || method !in METHODS) throw CompanionException("bad_request")
        if (method == "PUT" && path !in PUT_PATHS) throw CompanionException("bad_request")
        return method
    }

    /** The path itself, when it is a companion route with plain segments; otherwise `path_refused`. */
    fun checkPath(path: String?): String {
        if (path == null || path.length > MAX_PATH_LENGTH) throw CompanionException("path_refused")
        val prefix = ALLOWED_PREFIXES.firstOrNull { path.startsWith(it) } ?: throw CompanionException("path_refused")
        val segments = path.substring(prefix.length).split('/')
        if (segments.size > MAX_SEGMENTS || segments.any { !SEGMENT.matches(it) }) {
            throw CompanionException("path_refused")
        }
        if (segments.first() in DEDICATED_ROUTES) throw CompanionException("path_refused")
        return path
    }

    /** The query string including the leading "?", or "" when there is none. Values are percent-encoded here. */
    fun encodeQuery(query: Map<String, List<String>>?): String {
        if (query.isNullOrEmpty()) return ""
        val pairs = ArrayList<String>()
        for ((key, values) in query) {
            if (!QUERY_KEY.matches(key)) throw CompanionException("bad_request")
            for (value in values) {
                val limit = if (key == "cursor") MAX_CURSOR_LENGTH else MAX_QUERY_VALUE_LENGTH
                if (value.length > limit) throw CompanionException("bad_request")
                pairs += "$key=${URLEncoder.encode(value, "UTF-8").replace("+", "%20")}"
            }
        }
        if (pairs.size > MAX_QUERY_PAIRS) throw CompanionException("bad_request")
        return if (pairs.isEmpty()) "" else "?" + pairs.joinToString("&")
    }

    fun checkIdempotencyKey(key: String?): String? {
        if (key == null) return null
        if (!IDEMPOTENCY_KEY.matches(key)) throw CompanionException("bad_request")
        return key
    }

    /** The request body as bytes: a GET has none (a POST or PUT may), and a body larger than [MAX_BODY_BYTES] is refused. */
    fun checkBody(method: String, bodyJson: String?): ByteArray? {
        if (bodyJson == null) return null
        if (method != "POST" && method != "PUT") throw CompanionException("bad_request")
        val bytes = bodyJson.toByteArray(Charsets.UTF_8)
        if (bytes.size > MAX_BODY_BYTES) throw CompanionException("bad_request")
        return bytes
    }
}
