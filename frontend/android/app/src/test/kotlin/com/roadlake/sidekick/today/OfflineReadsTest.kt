package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.HttpCall
import com.roadlake.sidekick.companion.HttpResult
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class OfflineReadsTest {
    private val list = "/companion/v1/shopping/lists/$LIST"
    private val copyText = MemoryTextStore()
    private val h = Harness()
    private val reads = OfflineReads(h.client, copyText, { h.now }, h.generation)
    private var offline = false

    init {
        h.http.on {
            when {
                offline -> CompanionException("network", beforeSend = true)
                it.url.contains(list) -> HttpResult(200, """{"items":["mjölk"]}""")
                it.url.contains("/companion/v1/shopping/items/") -> HttpResult(200, "{}")
                else -> null
            }
        }
    }

    private fun readList(date: String = "2026-11-11") =
        reads.request("GET", list, mapOf("on_date" to listOf(date), "limit" to listOf("100")), null, null)

    @Test
    fun aListReadWithoutAnAnswerIsAnsweredFromTheLastCopyWithItsTime() {
        assertNull(readList().cachedAtMillis)
        val readAt = h.now
        h.now += 60_000
        offline = true
        val answer = readList(date = "2026-11-12")
        assertEquals(200, answer.response.status)
        assertEquals("""{"items":["mjölk"]}""", answer.response.body)
        assertEquals(readAt, answer.cachedAtMillis)
    }

    @Test
    fun withoutACopyTheFailureIsTheCallersAsBefore() {
        offline = true
        try {
            readList()
            fail("expected a CompanionException")
        } catch (e: CompanionException) {
            assertEquals("network", e.code)
        }
    }

    @Test
    fun aServerAnswerIsNeverReplacedByTheCopy() {
        readList()
        h.http.on { if (it.url.contains(list)) HttpResult(503, "{}") else null }
        val answer = readList()
        assertEquals(503, answer.response.status)
        assertNull(answer.cachedAtMillis)
    }

    @Test
    fun writesAndOtherRoutesAreNotKept() {
        reads.request("POST", "/companion/v1/shopping/items/$LIST/purchased", null, """{"version":1,"purchased":true}""", "page-key-0001")
        assertNull(copyText.text)
        assertNull(OfflineReads.keyOf("GET", "/companion/v1/work/today", null))
        assertEquals(
            "/companion/v1/shopping/lists?include_archived=true&limit=50",
            OfflineReads.keyOf("GET", "/companion/v1/shopping/lists", mapOf("limit" to listOf("50"), "include_archived" to listOf("true"))),
        )
    }

    @Test
    fun theCopyOfAnotherServerIsNotUsedAndTheCopyIsBounded() {
        readList()
        assertTrue(copyText.text!!.contains("sidekick.example"))
        copyText.text = copyText.text!!.replace("sidekick.example", "other.example")
        offline = true
        try {
            readList()
            fail("expected a CompanionException")
        } catch (e: CompanionException) {
            assertEquals("network", e.code)
        }
        offline = false
        repeat(OfflineReads.MAX_SHOPPING + 3) { page ->
            reads.request("GET", list, mapOf("offset" to listOf("$page")), null, null)
        }
        assertEquals(OfflineReads.MAX_SHOPPING, storedKeys().size)
    }

    @Test
    fun anAnswerThatArrivesAfterThePairingChangedIsNotKept() {
        h.http.on {
            if (it.url.contains(list)) {
                h.generation.advance()
                HttpResult(200, "{}")
            } else {
                null
            }
        }
        readList()
        assertNull(copyText.text)
    }

    private fun storedKeys(): List<String> {
        val stored = JSONObject(copyText.text!!).getJSONArray("entries")
        return List(stored.length()) { stored.getJSONObject(it).getString("key") }
    }

    private fun storedBody(key: String): JSONObject {
        val stored = JSONObject(copyText.text!!).getJSONArray("entries")
        for (i in 0 until stored.length()) {
            if (stored.getJSONObject(i).getString("key") == key) return JSONObject(stored.getJSONObject(i).getString("body"))
        }
        fail("no copy of $key")
        throw AssertionError()
    }

    /** A server script that, like the first one, gives no answer while [offline]. */
    private fun serve(handler: (HttpCall) -> Any?) =
        h.http.on { if (offline) CompanionException("network", beforeSend = true) else handler(it) }

    private fun readAgenda(vararg query: Pair<String, String>) =
        reads.request("GET", AGENDA, query.associate { it.first to listOf(it.second) }, null, null)

    private fun readTask() = reads.request("GET", "/companion/v1/tasks/$TASK", null, null, null)

    private fun post(path: String, key: String) = reads.request("POST", path, null, """{"version":1}""", key)

    private fun row(id: String, kind: String = "task", taskId: String = id) =
        """{"kind":"$kind","id":"$id","task_id":"$taskId","title":"t","status":"todo","version":3}"""

    private fun agendaIds(): List<String> {
        val rows = storedBody(AGENDA).getJSONArray("items")
        return List(rows.length()) { rows.getJSONObject(it).getString("id") }
    }

    @Test
    fun theAgendaIsKeptAndAnsweredFromTheCopyWithoutAConnection() {
        serve { if (it.url.contains(AGENDA)) HttpResult(200, """{"items":[${row(TASK)}],"next_cursor":null,"filters":{}}""") else null }
        assertNull(readAgenda("sort" to "due_asc").cachedAtMillis)
        val readAt = h.now
        h.now += 1_000
        offline = true
        val answer = readAgenda("sort" to "due_asc")
        assertEquals(readAt, answer.cachedAtMillis)
        assertTrue(answer.response.body.contains(TASK))
    }

    @Test
    fun anAgendaSearchOrALaterPageIsNotKept() {
        serve { if (it.url.contains(AGENDA)) HttpResult(200, """{"items":[],"next_cursor":null}""") else null }
        readAgenda("q" to "tandläkare")
        readAgenda("cursor" to "abc")
        assertNull(copyText.text)
        readAgenda("limit" to "25")
        assertEquals(listOf("$AGENDA?limit=25"), storedKeys())
    }

    @Test
    fun aTaskDetailIsKeptAndTheAgendaDoesNotPushOutTheLists() {
        serve {
            when {
                it.url.contains(AGENDA) -> HttpResult(200, """{"items":[],"next_cursor":null}""")
                it.url.contains("/companion/v1/tasks/$TASK") -> HttpResult(200, """{"task":{"id":"$TASK","status":"todo","version":3}}""")
                it.url.contains(list) -> HttpResult(200, """{"items":[]}""")
                else -> null
            }
        }
        readList()
        repeat(OfflineReads.MAX_AGENDA + 4) { readAgenda("limit" to "${it + 1}") }
        readTask()
        val keys = storedKeys()
        assertEquals(OfflineReads.MAX_AGENDA, keys.count { it.startsWith(AGENDA) })
        assertEquals(1, keys.count { it.startsWith("/companion/v1/shopping/") })
        assertEquals(1, keys.count { it == "/companion/v1/tasks/$TASK" })
        offline = true
        assertEquals(h.now, readTask().cachedAtMillis)
    }

    @Test
    fun aPurchaseTheServerAcceptedIsInTheCopyOfTheListAndTheCount() {
        val item = """{"id":"$ITEM","list_id":"$LIST","name":"Mjölk","purchased":false,"version":1}"""
        serve {
            when {
                it.url.contains("/items/$ITEM/purchased") ->
                    HttpResult(
                        200,
                        """{"item":{"id":"$ITEM","list_id":"$LIST","name":"Mjölk","purchased":true,"version":2},"open_count":0}""",
                    )

                it.url.endsWith("/shopping/lists") -> HttpResult(200, """{"lists":[{"id":"$LIST","open_count":1}]}""")

                it.url.contains(list) -> HttpResult(200, """{"items":[$item,{"id":"other","purchased":false,"version":1}]}""")

                else -> null
            }
        }
        readList()
        reads.request("GET", "/companion/v1/shopping/lists", null, null, null)
        val readAt = h.now
        h.now += 5_000
        post("/companion/v1/shopping/items/$ITEM/purchased", "page-key-0001")
        offline = true
        val answer = readList()
        assertEquals(readAt, answer.cachedAtMillis)
        val rows = JSONObject(answer.response.body).getJSONArray("items")
        assertTrue(rows.getJSONObject(0).getBoolean("purchased"))
        assertEquals(2, rows.getJSONObject(0).getInt("version"))
        assertEquals("Mjölk", rows.getJSONObject(0).getString("name"))
        assertFalse(rows.getJSONObject(1).getBoolean("purchased"))
        val lists = storedBody("/companion/v1/shopping/lists").getJSONArray("lists")
        assertEquals(0, lists.getJSONObject(0).getInt("open_count"))
    }

    @Test
    fun aRefusedWriteLeavesTheCopyAsItWas() {
        readList()
        val before = copyText.text
        serve { if (it.url.contains("/purchased")) HttpResult(409, """{"code":"conflict"}""") else null }
        post("/companion/v1/shopping/items/$ITEM/purchased", "page-key-0002")
        assertEquals(before, copyText.text)
    }

    @Test
    fun aCompletedTaskLeavesTheAgendaButItsStepsStayAndTheDetailTakesItsNewState() {
        serve {
            when {
                it.url.contains("/tasks/$TASK/complete") -> HttpResult(200, """{"task":{"id":"$TASK","status":"completed","version":4}}""")

                it.url.contains(
                    AGENDA,
                ) -> HttpResult(200, """{"items":[${row(TASK)},${row(OTHER)},${row("s1", "step", TASK)}],"next_cursor":null}""")

                it.url.contains("/tasks/$TASK") ->
                    HttpResult(200, """{"task":{"id":"$TASK","status":"todo","version":3,"title":"Ring","project_title":"Hus"}}""")

                else -> null
            }
        }
        readAgenda()
        readTask()
        post("/companion/v1/tasks/$TASK/complete", "page-key-0003")
        assertEquals(listOf(OTHER, "s1"), agendaIds())
        val task = storedBody("/companion/v1/tasks/$TASK").getJSONObject("task")
        assertEquals("completed", task.getString("status"))
        assertEquals(4, task.getInt("version"))
        assertEquals("Hus", task.getString("project_title"))
    }

    @Test
    fun aReceiptIsEnoughForTheDetailAndAReopenedTaskDropsTheAgendaCopy() {
        serve {
            when {
                it.url.contains("/tasks/$TASK/complete") -> HttpResult(200, """{"ok":true,"id":"$TASK","version":4,"status":"completed"}""")
                it.url.contains("/tasks/$TASK/reopen") -> HttpResult(200, """{"task":{"id":"$TASK","status":"todo","version":5}}""")
                it.url.contains(AGENDA) -> HttpResult(200, """{"items":[${row(TASK)}],"next_cursor":null}""")
                it.url.contains("/tasks/$TASK") -> HttpResult(200, """{"task":{"id":"$TASK","status":"todo","version":3}}""")
                else -> null
            }
        }
        readAgenda()
        readTask()
        post("/companion/v1/tasks/$TASK/complete", "page-key-0004")
        assertEquals(emptyList<String>(), agendaIds())
        val done = storedBody("/companion/v1/tasks/$TASK").getJSONObject("task")
        assertEquals("completed", done.getString("status"))
        assertFalse(done.has("ok"))
        readAgenda()
        post("/companion/v1/tasks/$TASK/reopen", "page-key-0005")
        assertEquals(listOf("/companion/v1/tasks/$TASK"), storedKeys())
        assertEquals(5, storedBody("/companion/v1/tasks/$TASK").getJSONObject("task").getInt("version"))
        offline = true
        try {
            readAgenda()
            fail("expected a CompanionException")
        } catch (e: CompanionException) {
            assertEquals("network", e.code)
        }
    }

    @Test
    fun aCompletionThatRollsTheTaskForwardDropsTheAgendaCopy() {
        serve {
            when {
                it.url.contains("/complete") -> HttpResult(200, """{"task":{"id":"$TASK","status":"todo","version":4}}""")
                it.url.contains(AGENDA) -> HttpResult(200, """{"items":[${row(TASK)}],"next_cursor":null}""")
                else -> null
            }
        }
        readAgenda()
        post("/companion/v1/tasks/$TASK/complete", "page-key-0008")
        assertNull(JSONObject(copyText.text!!).getJSONArray("entries").optJSONObject(0))
    }

    @Test
    fun aWriteAnsweredAfterThePairingChangedDoesNotTouchTheCopy() {
        readList()
        val before = copyText.text
        serve {
            if (it.url.contains("/purchased")) {
                h.generation.advance()
                HttpResult(200, """{"item":{"id":"$ITEM","list_id":"$LIST","purchased":true,"version":2}}""")
            } else {
                null
            }
        }
        post("/companion/v1/shopping/items/$ITEM/purchased", "page-key-0006")
        assertEquals(before, copyText.text)
    }

    @Test
    fun aCopyOfAnotherServerIsNotPatchedEither() {
        readList()
        copyText.text = copyText.text!!.replace("sidekick.example", "other.example")
        val before = copyText.text
        serve { if (it.url.contains("/purchased")) HttpResult(200, """{"item":{"id":"$ITEM","purchased":true,"version":2}}""") else null }
        post("/companion/v1/shopping/items/$ITEM/purchased", "page-key-0007")
        assertEquals(before, copyText.text)
    }

    private companion object {
        const val LIST = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        const val ITEM = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        const val TASK = "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        const val OTHER = "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        const val AGENDA = "/companion/v1/work/agenda"
    }
}
