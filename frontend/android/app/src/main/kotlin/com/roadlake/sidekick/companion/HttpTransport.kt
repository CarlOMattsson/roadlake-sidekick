package com.roadlake.sidekick.companion

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class HttpCall(val method: String, val url: String, val headers: Map<String, String>, val body: ByteArray?)

/** [retryAfterSeconds] is the `Retry-After` header when it is a whole number of seconds. */
class HttpResult(val status: Int, val body: String, val retryAfterSeconds: Int? = null)

/** One HTTP exchange. A server answer of any status is a result; no answer at all is a [CompanionException]. */
fun interface HttpTransport {
    fun execute(call: HttpCall): HttpResult
}

/**
 * The largest response body the app reads (2 MiB). The server never sends more than half of it
 * (`MAX_RESPONSE_BYTES` in `backend/src/sidekick/companion/response_budget.py`, which trims journal
 * pages and refuses any other oversize answer); `test_companion_response_budget.py` reads both
 * numbers and fails if this one falls below the server's. Change them together.
 */
const val MAX_RESPONSE_BYTES = 2_097_152

/**
 * The platform HTTP client. Redirects are never followed (the bearer token must not follow a redirect to another
 * host), every wait is bounded, and the response size is capped.
 *
 * `readTimeoutMs` only bounds one stalled read, so a server that sends a byte every few seconds would hold the call
 * (and a worker thread) for as long as it likes. [callTimeoutMs] is the total budget for the whole exchange, from
 * connecting to the last byte of the response: when it runs out the connection is cut and the call fails with
 * `timeout`, whichever phase it was in. A read (GET) has the shorter [readCallTimeoutMs]: nothing is lost by giving
 * up on it sooner, and the room can show its offline copy instead of a spinner. A declared `Content-Length` above
 * [maxResponseBytes] is refused before any of the body is read.
 *
 * [hasNetwork] is asked before anything is opened: when the phone has no network at all the call fails at once with
 * `network` (before send), instead of waiting out the connect timeout.
 */
class UrlConnectionTransport(
    private val connectTimeoutMs: Int = 10_000,
    private val readTimeoutMs: Int = 20_000,
    private val maxResponseBytes: Int = MAX_RESPONSE_BYTES,
    private val callTimeoutMs: Long = 30_000,
    private val readCallTimeoutMs: Long = 15_000,
    private val hasNetwork: () -> Boolean = { true },
) : HttpTransport {
    override fun execute(call: HttpCall): HttpResult {
        if (!hasNetwork()) throw CompanionException("network", beforeSend = true)
        val budget = if (call.method == "GET") minOf(readCallTimeoutMs, callTimeoutMs) else callTimeoutMs
        val connection = URL(call.url).openConnection() as HttpURLConnection
        val expired = AtomicBoolean(false)
        val watchdog = WATCHDOGS.schedule(
            {
                expired.set(true)
                connection.disconnect()
            },
            budget,
            TimeUnit.MILLISECONDS,
        )
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.requestMethod = call.method
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json, application/problem+json")
            for ((name, value) in call.headers) connection.setRequestProperty(name, value)
            if (call.body != null) {
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(call.body.size)
                connection.outputStream.use { it.write(call.body) }
            }
            val status = connection.responseCode
            if (status in 300..399) throw CompanionException("redirect_refused")
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val retryAfter = connection.getHeaderField("Retry-After")?.trim()?.toIntOrNull()?.takeIf { it >= 0 }
            if (connection.contentLengthLong > maxResponseBytes) throw CompanionException("response_too_large")
            return HttpResult(status, stream?.use { readCapped(it, expired) } ?: "", retryAfter)
        } catch (e: CompanionException) {
            throw e
        } catch (_: SocketTimeoutException) {
            throw CompanionException("timeout")
        } catch (_: UnknownHostException) {
            throw expiredOr(expired, CompanionException("network", beforeSend = true))
        } catch (_: ConnectException) {
            throw expiredOr(expired, CompanionException("network", beforeSend = true))
        } catch (_: NoRouteToHostException) {
            throw expiredOr(expired, CompanionException("network", beforeSend = true))
        } catch (_: IOException) {
            // The watchdog cut the connection: a closed socket surfaces as a plain IOException, not a timeout.
            throw expiredOr(expired, CompanionException("network"))
        } finally {
            watchdog.cancel(false)
            connection.disconnect()
        }
    }

    private fun expiredOr(expired: AtomicBoolean, otherwise: CompanionException): CompanionException =
        if (expired.get()) CompanionException("timeout") else otherwise

    /** Reads at most [maxResponseBytes]; a cut connection can end the stream quietly, so the budget is checked too. */
    private fun readCapped(stream: InputStream, expired: AtomicBoolean): String {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (true) {
            val read = stream.read(buffer)
            if (expired.get()) throw CompanionException("timeout")
            if (read < 0) break
            if (out.size() + read > maxResponseBytes) throw CompanionException("response_too_large")
            out.write(buffer, 0, read)
        }
        return out.toString(Charsets.UTF_8.name())
    }

    private companion object {
        /** One daemon thread that cuts connections whose total budget has run out; it never keeps the process alive. */
        val WATCHDOGS: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "sidekick-http-watchdog").apply { isDaemon = true }
        }
    }
}
