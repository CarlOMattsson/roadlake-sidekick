package com.roadlake.sidekick.support

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList

/** A request as it arrived on the socket; header names are lower-case. */
class ServerRequest(val method: String, val target: String, val headers: Map<String, String>, val body: String) {
    val path: String get() = target.substringBefore('?')
}

/** An answer to send; `null` from the handler means "close the connection without answering". */
class ServerReply(val status: Int, val body: String = "", val headers: Map<String, String> = emptyMap())

/**
 * A minimal HTTP/1.1 server on the loopback interface, for tests that must go through the real [java.net] transport on
 * the JVM and on a device alike (`com.sun.net.httpserver` does not exist on Android). One request per connection, answered
 * on one thread; the handler decides everything. [requests] keeps what arrived, in order.
 */
class LocalHttpServer(private val handler: (ServerRequest) -> ServerReply?) : AutoCloseable {
    private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    private val acceptor = Thread(::serve, "local-http-server").apply { isDaemon = true }
    val requests = CopyOnWriteArrayList<ServerRequest>()

    /** `http://127.0.0.1:<port>`, the origin a debug build accepts for local cleartext. */
    val origin: String = "http://127.0.0.1:${socket.localPort}"

    fun start(): LocalHttpServer {
        acceptor.start()
        return this
    }

    override fun close() {
        socket.close()
        acceptor.join(2_000)
    }

    private fun serve() {
        while (!socket.isClosed) {
            val connection = try {
                socket.accept()
            } catch (_: IOException) {
                return
            }
            connection.use { answer(it) }
        }
    }

    private fun answer(connection: Socket) {
        connection.soTimeout = 5_000
        val request = try {
            read(connection.getInputStream())
        } catch (_: IOException) {
            return
        }
        requests += request
        val reply = handler(request) ?: return
        val body = reply.body.toByteArray(Charsets.UTF_8)
        val head = StringBuilder("HTTP/1.1 ${reply.status} Reply\r\n")
        head.append("Content-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n")
        for ((name, value) in reply.headers) head.append("$name: $value\r\n")
        head.append("\r\n")
        try {
            connection.getOutputStream().apply {
                write(head.toString().toByteArray(Charsets.ISO_8859_1))
                write(body)
                flush()
            }
        } catch (_: IOException) {
            // The client went away: nothing to answer.
        }
    }

    private fun read(input: InputStream): ServerRequest {
        val requestLine = line(input).split(' ')
        if (requestLine.size < 2) throw IOException("bad request line")
        val headers = HashMap<String, String>()
        while (true) {
            val header = line(input)
            if (header.isEmpty()) break
            val colon = header.indexOf(':')
            if (colon > 0) headers[header.substring(0, colon).trim().lowercase()] = header.substring(colon + 1).trim()
        }
        val length = headers["content-length"]?.toIntOrNull() ?: 0
        val body = ByteArray(length)
        var done = 0
        while (done < length) {
            val read = input.read(body, done, length - done)
            if (read < 0) throw IOException("body cut off")
            done += read
        }
        return ServerRequest(requestLine[0], requestLine[1], headers, String(body, Charsets.UTF_8))
    }

    private fun line(input: InputStream): String {
        val out = ByteArrayOutputStream()
        while (true) {
            val next = input.read()
            if (next < 0) throw IOException("connection closed")
            if (next == '\n'.code) break
            if (next != '\r'.code) out.write(next)
        }
        return out.toString(Charsets.ISO_8859_1.name())
    }
}
