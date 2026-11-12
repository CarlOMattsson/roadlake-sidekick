package com.roadlake.sidekick.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class RequestPolicyTest {
    private val taskId = "3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e"

    private fun code(block: () -> Unit): String = assertThrows(CompanionException::class.java, block).code

    @Test
    fun allowsTheCompanionRoutesTheRoomsUse() {
        listOf(
            "/companion/v1/work/agenda",
            "/companion/v1/tasks/$taskId",
            "/companion/v1/tasks/$taskId/complete",
        ).forEach { assertEquals(it, RequestPolicy.checkPath(it)) }
    }

    @Test
    fun refusesEverythingOutsideTheCompanionPrefix() {
        listOf(
            null,
            "",
            "/",
            "/api/v1/tasks",
            "/mcp",
            "/agent-mcp",
            "/companion/v2/work/agenda",
            "/companion/v1",
            "/companion/v1/",
            "companion/v1/work/agenda",
            "//evil.example/companion/v1/x",
            "https://evil.example/companion/v1/x",
            "/Companion/v1/work/agenda",
            "/x/companion/v1/work/agenda",
        ).forEach { assertEquals("path_refused", code { RequestPolicy.checkPath(it) }) }
    }

    @Test
    fun refusesPathTricks() {
        listOf(
            "/companion/v1/../api/v1/tasks",
            "/companion/v1/./work",
            "/companion/v1/work//agenda",
            "/companion/v1/work/agenda/",
            "/companion/v1/work/agenda?x=1",
            "/companion/v1/work/agenda#x",
            "/companion/v1/work/%2e%2e/agenda",
            "/companion/v1/work\\agenda",
            "/companion/v1/work agenda",
            "/companion/v1/work/agenda\n",
            "/companion/v1/" + "a".repeat(65),
            "/companion/v1/a/b/c/d/e/f/g",
        ).forEach { assertEquals(it, "path_refused", code { RequestPolicy.checkPath(it) }) }
    }

    @Test
    fun refusesTheRoutesWithTheirOwnPluginMethods() {
        assertEquals("path_refused", code { RequestPolicy.checkPath("/companion/v1/pair") })
        assertEquals("path_refused", code { RequestPolicy.checkPath("/companion/v1/device") })
        assertEquals("path_refused", code { RequestPolicy.checkPath("/companion/v1/device/x") })
    }

    @Test
    fun allowsGetAndPostOnAnyCompanionPath() {
        val path = "/companion/v1/work/agenda"
        assertEquals("GET", RequestPolicy.checkMethod("GET", path))
        assertEquals("POST", RequestPolicy.checkMethod("POST", path))
        listOf(null, "", "get", "put", "DELETE", "PATCH", "CONNECT").forEach {
            assertEquals("bad_request", code { RequestPolicy.checkMethod(it, path) })
        }
    }

    @Test
    fun allowsPutOnlyForTheLicensePath() {
        assertEquals("PUT", RequestPolicy.checkMethod("PUT", "/companion/v1/license"))
        listOf(
            null,
            "",
            "/companion/v1/work/agenda",
            "/companion/v1/tasks/$taskId",
            "/companion/v1/push/subscription",
            "/companion/v1/license/x",
            "/companion/v1/licenses",
            "/companion/v1/license/",
            "/companion/v1/license?x=1",
            "/Companion/v1/license",
        ).forEach { assertEquals(it, "bad_request", code { RequestPolicy.checkMethod("PUT", it) }) }
    }

    @Test
    fun encodesTheQueryAndRefusesBadKeys() {
        assertEquals("", RequestPolicy.encodeQuery(null))
        assertEquals("", RequestPolicy.encodeQuery(emptyMap()))
        assertEquals(
            "?q=a%20b%26c&tags=x&tags=y%C3%A5&limit=20",
            RequestPolicy.encodeQuery(linkedMapOf("q" to listOf("a b&c"), "tags" to listOf("x", "yå"), "limit" to listOf("20"))),
        )
        assertEquals("bad_request", code { RequestPolicy.encodeQuery(mapOf("a=b" to listOf("1"))) })
        assertEquals("bad_request", code { RequestPolicy.encodeQuery(mapOf("" to listOf("1"))) })
        assertEquals("bad_request", code { RequestPolicy.encodeQuery(mapOf("q" to listOf("x".repeat(513)))) })
        assertEquals(
            "bad_request",
            code { RequestPolicy.encodeQuery(mapOf("q" to List(41) { "x" })) },
        )
    }

    @Test
    fun letsAPaginationCursorBeLongerThanOtherQueryValues() {
        val longest = "x".repeat(RequestPolicy.MAX_CURSOR_LENGTH)
        assertEquals("?cursor=$longest", RequestPolicy.encodeQuery(mapOf("cursor" to listOf(longest))))
        assertEquals("bad_request", code { RequestPolicy.encodeQuery(mapOf("cursor" to listOf(longest + "x"))) })
    }

    @Test
    fun checksTheIdempotencyKeyHeader() {
        assertNull(RequestPolicy.checkIdempotencyKey(null))
        assertEquals(taskId, RequestPolicy.checkIdempotencyKey(taskId))
        assertEquals("bad_request", code { RequestPolicy.checkIdempotencyKey("short") })
        assertEquals("bad_request", code { RequestPolicy.checkIdempotencyKey("abcdefgh\r\nX-Evil: 1") })
        assertEquals("bad_request", code { RequestPolicy.checkIdempotencyKey("a".repeat(129)) })
    }

    @Test
    fun checksTheBody() {
        assertNull(RequestPolicy.checkBody("GET", null))
        assertEquals("{\"version\":3}", String(RequestPolicy.checkBody("POST", "{\"version\":3}")!!))
        assertEquals("{\"key\":\"k\"}", String(RequestPolicy.checkBody("PUT", "{\"key\":\"k\"}")!!))
        assertEquals("bad_request", code { RequestPolicy.checkBody("GET", "{}") })
        assertEquals(
            "bad_request",
            code { RequestPolicy.checkBody("PUT", "x".repeat(RequestPolicy.MAX_BODY_BYTES + 1)) },
        )
        assertEquals(
            "bad_request",
            code { RequestPolicy.checkBody("POST", "x".repeat(RequestPolicy.MAX_BODY_BYTES + 1)) },
        )
    }

    @Test
    fun countsBodyBytesNotCharacters() {
        // A journal write at the form's own ceiling: 256 KiB exactly passes, one byte more does not.
        assertEquals(
            RequestPolicy.MAX_BODY_BYTES,
            RequestPolicy.checkBody("POST", "x".repeat(RequestPolicy.MAX_BODY_BYTES))!!.size,
        )
        // Half as many characters of "ö" (2 bytes each) still fill the budget; one more is refused.
        val half = RequestPolicy.MAX_BODY_BYTES / 2
        assertEquals(RequestPolicy.MAX_BODY_BYTES, RequestPolicy.checkBody("POST", "ö".repeat(half))!!.size)
        assertEquals("bad_request", code { RequestPolicy.checkBody("POST", "ö".repeat(half + 1)) })
    }
}
