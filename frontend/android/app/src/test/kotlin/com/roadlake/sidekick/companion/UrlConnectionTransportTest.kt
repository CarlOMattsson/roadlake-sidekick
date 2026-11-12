package com.roadlake.sidekick.companion

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.net.ServerSocket
import java.net.Socket

/** The platform transport against a raw socket that answers the way a slow or oversized server would. */
class UrlConnectionTransportTest {
    private val server = ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())
    private val url = "http://127.0.0.1:${server.localPort}/companion/v1/work/today"
    private val accepted = mutableListOf<Socket>()

    @After
    fun stop() {
        accepted.forEach { runCatching { it.close() } }
        server.close()
    }

    /** Accepts one connection, reads the request head, and lets [reply] write the answer. */
    private fun serve(reply: (Socket) -> Unit) {
        val thread = Thread {
            runCatching {
                val socket = server.accept()
                accepted += socket
                val input = socket.getInputStream()
                val head = StringBuilder()
                while (!head.endsWith("\r\n\r\n")) {
                    val next = input.read()
                    if (next < 0) break
                    head.append(next.toChar())
                }
                reply(socket)
            }
        }
        thread.isDaemon = true
        thread.start()
    }

    private fun get(transport: UrlConnectionTransport) = transport.execute(HttpCall("GET", url, emptyMap(), null))

    private fun failureOf(transport: UrlConnectionTransport): Pair<String, Long> {
        val started = System.nanoTime()
        try {
            get(transport)
        } catch (e: CompanionException) {
            return e.code to (System.nanoTime() - started) / 1_000_000
        }
        fail("expected a CompanionException")
        throw AssertionError()
    }

    @Test
    fun aPlainAnswerIsReadInFull() {
        serve { socket ->
            val body = "{\"ok\":true}"
            socket.getOutputStream().write(
                "HTTP/1.1 200 OK\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n$body".toByteArray(),
            )
            socket.getOutputStream().flush()
        }
        val result = get(UrlConnectionTransport(callTimeoutMs = 5_000))
        assertEquals(200, result.status)
        assertEquals("{\"ok\":true}", result.body)
    }

    @Test
    fun aServerThatDripsItsAnswerIsCutAtTheTotalBudgetEvenThoughEveryReadSucceeds() {
        serve { socket ->
            val out = socket.getOutputStream()
            out.write("HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n".toByteArray())
            repeat(200) {
                out.write('x'.code)
                out.flush()
                Thread.sleep(50)
            }
        }
        // Each read returns well inside the 5 s read timeout; only the 600 ms total budget can stop this.
        val (code, elapsedMs) = failureOf(UrlConnectionTransport(readTimeoutMs = 5_000, callTimeoutMs = 600))
        assertEquals("timeout", code)
        assertTrue("cut after $elapsedMs ms", elapsedMs < 4_000)
    }

    @Test
    fun aServerThatNeverAnswersIsCutAtTheTotalBudget() {
        serve { Thread.sleep(10_000) }
        val (code, elapsedMs) = failureOf(UrlConnectionTransport(readTimeoutMs = 20_000, callTimeoutMs = 500))
        assertEquals("timeout", code)
        assertTrue("cut after $elapsedMs ms", elapsedMs < 4_000)
    }

    @Test
    fun aDeclaredLengthAboveTheCapIsRefusedBeforeTheBodyIsRead() {
        serve { socket ->
            socket.getOutputStream().write(
                "HTTP/1.1 200 OK\r\nContent-Length: 5000\r\nConnection: close\r\n\r\nxxxx".toByteArray(),
            )
            socket.getOutputStream().flush()
            Thread.sleep(5_000)
        }
        val (code, elapsedMs) = failureOf(UrlConnectionTransport(maxResponseBytes = 1_000, callTimeoutMs = 10_000))
        assertEquals("response_too_large", code)
        assertTrue("refused after $elapsedMs ms", elapsedMs < 4_000)
    }

    @Test
    fun anUndeclaredBodyAboveTheCapIsRefusedWhileItIsRead() {
        serve { socket ->
            val out = socket.getOutputStream()
            out.write("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n".toByteArray())
            out.write(ByteArray(5_000) { 'x'.code.toByte() })
            out.flush()
        }
        val (code, _) = failureOf(UrlConnectionTransport(maxResponseBytes = 1_000, callTimeoutMs = 10_000))
        assertEquals("response_too_large", code)
    }

    @Test
    fun withoutANetworkTheCallFailsAtOnceBeforeAnythingIsSent() {
        var connected = false
        serve { connected = true }
        val transport = UrlConnectionTransport(callTimeoutMs = 10_000, hasNetwork = { false })
        try {
            get(transport)
            fail("expected a CompanionException")
        } catch (e: CompanionException) {
            assertEquals("network", e.code)
            assertTrue("nothing was sent", e.beforeSend)
        }
        Thread.sleep(100)
        assertTrue("no connection was opened", !connected)
    }

    @Test
    fun aReadIsCutAtItsOwnShorterBudget() {
        serve { Thread.sleep(10_000) }
        val transport = UrlConnectionTransport(readTimeoutMs = 20_000, callTimeoutMs = 8_000, readCallTimeoutMs = 400)
        val (code, elapsedMs) = failureOf(transport)
        assertEquals("timeout", code)
        assertTrue("a read is cut after $elapsedMs ms", elapsedMs < 4_000)
    }
}
