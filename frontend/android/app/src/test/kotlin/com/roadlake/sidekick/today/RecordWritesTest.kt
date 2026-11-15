package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.HttpCall
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.support.MemoryAesKeys
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Record writes (new and edited Tasks and Projects, journal entries) queued without coverage, and how the drain sends them. */
class RecordWritesTest {
    private val todayCall = "/companion/v1/work/today"
    private val createTask = "/companion/v1/tasks"
    private val editTask = "/companion/v1/tasks/$TASK_A/update"
    private val editProject = "/companion/v1/projects/$PROJECT/update"
    private val createEntry = "/companion/v1/journal/entries"
    private val diaryText = "Hemlig dagbok: åäö kl. 07"

    private fun Harness.queue(kind: OutboxKind, subjectId: String, version: Int, body: String, key: String) =
        repo.enqueueRecordWrite(repo.pairingGeneration(), kind, subjectId, version, body, key)

    private fun Harness.queueNew(kind: OutboxKind, body: String, key: String) = queue(kind, Outbox.NEW_SUBJECT, 0, body, key)

    private fun Outbox.create(kind: OutboxKind, body: String, key: String) = enqueueRecordWrite(kind, Outbox.NEW_SUBJECT, 0, body, key)

    private fun Outbox.editTask(version: Int, body: String, key: String) =
        enqueueRecordWrite(OutboxKind.TASK_EDIT, TASK_A, version, body, key)

    private fun Outbox.editEntry(body: String, key: String) = enqueueRecordWrite(OutboxKind.JOURNAL_EDIT, ENTRY, 2, body, key)

    private fun Harness.serveToday() {
        http.on { if (it.url.contains(todayCall)) HttpResult(200, todayPage()) else null }
    }

    /** Answers a POST to [path] with [answer] (an [HttpResult], or a [CompanionException] for "no answer came"). */
    private fun Harness.answer(path: String, answer: Any) {
        http.on { if (it.method == "POST" && it.url.endsWith(path)) answer else null }
    }

    private fun HttpCall.json() = JSONObject(String(body!!))

    private fun editBody(version: Int, vararg fields: Pair<String, String>) =
        JSONObject().put("version", version).also { json -> fields.forEach { json.put(it.first, it.second) } }.toString()

    /** A JSON object body of exactly [length] characters. */
    private fun bodyOfLength(length: Int) = """{"title":"${"x".repeat(length - 12)}"}"""

    private fun writeQueue(h: Harness, journal: Boolean = false) = (if (journal) h.journalOutbox else h.outbox).pending()

    // Queueing

    @Test
    fun aNewTaskIsQueuedWithItsKeyAndTheExactBodyAndTheSameKeyIsTheSameWrite() {
        val h = Harness()
        val body = """{"title":"Köp mjölk"}"""
        val queued = h.queueNew(OutboxKind.TASK_CREATE, body, CREATE_KEY)
        assertEquals(EnqueueResult.QUEUED, queued.result)
        val entry = writeQueue(h).single()
        assertEquals(CREATE_KEY, entry.idempotencyKey)
        assertEquals(createTask, entry.path)
        assertEquals(body, entry.bodyJson())
        assertEquals(entry.idempotencyKey, queued.entry!!.idempotencyKey)

        assertEquals(EnqueueResult.QUEUED, h.queueNew(OutboxKind.TASK_CREATE, body, CREATE_KEY).result)
        assertEquals("no duplicate", 1, writeQueue(h).size)
    }

    @Test
    fun aNewKeyIsASecondNewTask() {
        val h = Harness()
        h.queueNew(OutboxKind.TASK_CREATE, """{"title":"A"}""", CREATE_KEY)
        h.queueNew(OutboxKind.TASK_CREATE, """{"title":"B"}""", CREATE_KEY_2)
        assertEquals(listOf(CREATE_KEY, CREATE_KEY_2), writeQueue(h).map { it.idempotencyKey })
        assertEquals(listOf("""{"title":"A"}""", """{"title":"B"}"""), writeQueue(h).map { it.bodyJson() })
    }

    @Test
    fun anEditOfATaskAndOfAProjectAreSentToTheirOwnRoutesAndTheSameKeyIsTheSameWrite() {
        val h = Harness()
        val body = editBody(3, "title" to "New title")
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, body, "edit-key-0001")
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 2, body, "edit-key-0002")
        assertEquals(listOf(editTask, editProject), writeQueue(h).map { it.path })
        assertEquals(listOf(body, body), writeQueue(h).map { it.bodyJson() })

        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, body, "edit-key-0001")
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 2, body, "edit-key-0002")
        assertEquals(listOf("edit-key-0001", "edit-key-0002"), writeQueue(h).map { it.idempotencyKey })
    }

    // Folding a second edit

    @Test
    fun aSecondEditOfTheSameRowIsFoldedIntoTheFirstWhileItHasNeverBeenTried() {
        val h = Harness()
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "Old", "note" to "Keep"), "edit-key-0001")
        h.queue(OutboxKind.TASK_EDIT, TASK_B, 1, editBody(1, "title" to "Other"), "edit-key-0002")
        h.now += 500

        val folded = h.queue(OutboxKind.TASK_EDIT, TASK_A, 5, editBody(5, "title" to "New"), "edit-key-0003")

        assertEquals(EnqueueResult.QUEUED, folded.result)
        val queue = writeQueue(h)
        assertEquals("one write per row", listOf(TASK_A, TASK_B), queue.map { it.subjectId })
        val entry = queue.first()
        val body = JSONObject(entry.bodyJson())
        assertEquals("the later value wins", "New", body.getString("title"))
        assertEquals("a field only the first set stays", "Keep", body.getString("note"))
        assertEquals("the older version is kept", 3, body.getInt("version"))
        assertEquals(3, entry.version)
        // A new key, so a request of the old one that did get through is not mistaken for this edit.
        assertNotEquals("edit-key-0001", entry.idempotencyKey)
        assertNotEquals("edit-key-0003", entry.idempotencyKey)
        assertEquals("it keeps its place and age", 1_000_000L, entry.createdAtMillis)
        assertEquals(0, entry.attempts)
    }

    @Test
    fun theLowerVersionWinsWhenTheLaterEditRestsOnAnOlderOne() {
        val h = Harness()
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 6, editBody(6, "title" to "A"), "edit-key-0001")
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 4, editBody(4, "title" to "B"), "edit-key-0002")
        val entry = writeQueue(h).single()
        assertEquals(4, entry.version)
        assertEquals(4, JSONObject(entry.bodyJson()).getInt("version"))
    }

    @Test
    fun aFoldThatWouldBeTooLargeIsRefusedAndTheFirstEditStays() {
        val h = Harness()
        val half = "x".repeat(Outbox.MAX_PAYLOAD_CHARS / 2)
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to half), "edit-key-0001")
        val refused = h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "note" to half), "edit-key-0002")
        assertEquals(EnqueueResult.STORAGE_FAILED, refused.result)
        assertEquals(listOf("edit-key-0001"), writeQueue(h).map { it.idempotencyKey })
    }

    @Test
    fun aSecondEditIsRefusedOnceTheFirstHasBeenTriedAndTheFirstStaysUntouched() {
        val h = Harness()
        val first = editBody(3, "title" to "Old")
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, first, "edit-key-0001")
        h.outbox.recordAttempt(TASK_A, "edit-key-0001")

        val refused = h.queue(OutboxKind.TASK_EDIT, TASK_A, 5, editBody(5, "title" to "New"), "edit-key-0002")

        assertEquals(EnqueueResult.STORAGE_FAILED, refused.result)
        assertNull(refused.entry)
        val entry = writeQueue(h).single()
        assertEquals("edit-key-0001", entry.idempotencyKey)
        assertEquals(first, entry.bodyJson())
        assertEquals(1, entry.attempts)
        assertEquals("the same key is still the same write", "edit-key-0001", h.outbox.editTask(3, first, "edit-key-0001")!!.idempotencyKey)
    }

    @Test
    fun aSecondEditOfAJournalEntryIsAlwaysRefused() {
        val h = Harness()
        val first = editBody(2, "text" to diaryText)
        assertNotNull(h.journalOutbox.editEntry(first, JOURNAL_KEY))
        assertNull(h.journalOutbox.editEntry(editBody(2, "text" to "Later"), JOURNAL_KEY_2))
        val same = h.journalOutbox.editEntry(first, JOURNAL_KEY)
        assertEquals("the same key is the same write", JOURNAL_KEY, same!!.idempotencyKey)
        val entry = writeQueue(h, journal = true).single()
        assertEquals(first, entry.bodyJson())
        assertEquals("/companion/v1/journal/entries/$ENTRY/update", entry.path)
    }

    // Size

    @Test
    fun aBodyOverTheCapIsNotQueued() {
        val h = Harness()
        assertNotNull(h.outbox.create(OutboxKind.TASK_CREATE, bodyOfLength(Outbox.MAX_PAYLOAD_CHARS), CREATE_KEY))
        assertNull(h.outbox.create(OutboxKind.TASK_CREATE, bodyOfLength(Outbox.MAX_PAYLOAD_CHARS + 1), CREATE_KEY_2))
        val refused = h.queueNew(OutboxKind.TASK_CREATE, bodyOfLength(Outbox.MAX_PAYLOAD_CHARS + 1), CREATE_KEY_2)
        assertEquals(EnqueueResult.STORAGE_FAILED, refused.result)
        assertEquals(listOf(CREATE_KEY), writeQueue(h).map { it.idempotencyKey })
    }

    @Test
    fun theJournalQueueTakesALargerBodyThanTheOutbox() {
        val keys = MemoryAesKeys()
        val text = MemoryTextStore()
        val journal = Outbox(
            EncryptedTextStore(text, AesGcmCipher(keys, ByteArray(0)), keys),
            maxPayloadChars = Outbox.MAX_JOURNAL_PAYLOAD_CHARS,
            clock = { 1_000L },
        )
        val larger = bodyOfLength(Outbox.MAX_PAYLOAD_CHARS + 1)
        assertNotNull(journal.create(OutboxKind.JOURNAL_CREATE, larger, JOURNAL_KEY))
        assertNotNull(journal.create(OutboxKind.JOURNAL_CREATE, bodyOfLength(Outbox.MAX_JOURNAL_PAYLOAD_CHARS), JOURNAL_KEY_2))
        assertNull(journal.create(OutboxKind.JOURNAL_CREATE, bodyOfLength(Outbox.MAX_JOURNAL_PAYLOAD_CHARS + 1), "journal-key-0003"))
        assertEquals(listOf(JOURNAL_KEY, JOURNAL_KEY_2), journal.pending().map { it.idempotencyKey })
    }

    // Sending

    @Test
    fun anEditAndANewTaskAreSentWithTheirRouteBodyAndKeyAndLeaveTheQueueWhenTheServerAnswers() {
        val h = Harness()
        val edit = editBody(3, "title" to "Ny rubrik")
        val create = """{"title":"Köp mjölk"}"""
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, edit, "edit-key-0001")
        h.queueNew(OutboxKind.TASK_CREATE, create, CREATE_KEY)
        h.serveToday()
        h.answer(editTask, HttpResult(200, "{}"))
        h.answer(createTask, HttpResult(201, "{}"))
        assertTrue("queueing sends nothing", h.http.calls.isEmpty())

        assertEquals(SyncResult.UPDATED, h.repo.sync())

        val posts = h.http.posts()
        assertEquals(listOf("https://sidekick.example$editTask", "https://sidekick.example$createTask"), posts.map { it.url })
        assertEquals(listOf("edit-key-0001", CREATE_KEY), posts.map { it.headers["Idempotency-Key"] })
        assertEquals(listOf(edit, create), posts.map { String(it.body!!) })
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertTrue(h.outbox.pending().isEmpty())
    }

    private fun assertRetriedWithTheSameKey(noAnswer: Any) {
        val h = Harness()
        val edit = editBody(3, "title" to "Ny rubrik")
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, edit, "edit-key-0001")
        h.serveToday()
        h.answer(editTask, noAnswer)

        assertEquals(SyncResult.RETRY, h.repo.sync())
        val kept = h.repo.queuedRecordWrites().single()
        assertEquals("edit-key-0001", kept.idempotencyKey)
        assertEquals(1, kept.attempts)
        assertTrue(h.repo.failedWrites().isEmpty())

        h.answer(editTask, HttpResult(200, "{}"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals(listOf("edit-key-0001", "edit-key-0001"), h.http.posts().map { it.headers["Idempotency-Key"] })
        assertEquals(listOf(edit, edit), h.http.posts().map { String(it.body!!) })
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
    }

    @Test
    fun aWriteThatGotAServerErrorStaysQueuedAndIsSentAgainWithTheSameKey() = assertRetriedWithTheSameKey(HttpResult(503, "{}"))

    @Test
    fun aWriteWithoutAnAnswerStaysQueuedAndIsSentAgainWithTheSameKey() = assertRetriedWithTheSameKey(CompanionException("network"))

    private fun assertRefusedForGood(status: Int) {
        val h = Harness()
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "Ny rubrik"), "edit-key-0001")
        h.serveToday()
        h.answer(editTask, HttpResult(status, """{"code":"refused"}"""))

        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        val failed = h.repo.failedWrites().single()
        assertEquals(OutboxFailure.REJECTED, failed.failure)
        assertEquals("edit-key-0001", failed.idempotencyKey)

        assertEquals("never sent again by the drain", SyncResult.UPDATED, h.repo.sync())
        assertEquals(1, h.http.posts().size)
        h.now += 60_000
        assertEquals("it stays until the user removes it", 1, h.repo.failedWrites().size)

        assertTrue(h.repo.discardFailedWrite("edit-key-0001"))
        assertTrue(h.repo.failedWrites().isEmpty())
        assertFalse(h.repo.discardFailedWrite("edit-key-0001"))
    }

    @Test
    fun aWriteTheServerSaysChangedElsewhereIsKeptAsRejected() = assertRefusedForGood(409)

    @Test
    fun aWriteTheServerSaysIsGoneIsKeptAsRejected() = assertRefusedForGood(404)

    @Test
    fun aWriteTheServerSaysIsNotValidIsKeptAsRejected() = assertRefusedForGood(422)

    @Test
    fun aRejectedWriteIsSentAgainWithItsKeyWhenTheUserRetriesIt() {
        val h = Harness()
        h.queueNew(OutboxKind.TASK_CREATE, """{"title":"Köp mjölk"}""", CREATE_KEY)
        h.serveToday()
        h.answer(createTask, HttpResult(422, "{}"))
        h.repo.sync()
        h.answer(createTask, HttpResult(200, "{}"))

        assertTrue(h.repo.retryFailedWrite(CREATE_KEY))
        assertTrue(h.repo.failedWrites().isEmpty())
        assertEquals(SyncResult.UPDATED, h.repo.sync())

        assertEquals(listOf(CREATE_KEY, CREATE_KEY), h.http.posts().map { it.headers["Idempotency-Key"] })
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertTrue(h.repo.failedWrites().isEmpty())
    }

    @Test
    fun aWriteOlderThanTheQueueMayKeepIsKeptAsExpiredAndRetryPutsItBackAsNew() {
        val h = Harness()
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 2, editBody(2, "title" to "Ny rubrik"), "edit-key-0001")
        h.serveToday()
        h.answer(editProject, HttpResult(200, "{}"))
        h.now += Outbox.MAX_AGE_MILLIS + 1

        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue("not sent when it is old", h.http.posts().isEmpty())
        val expired = h.repo.failedWrites().single()
        assertEquals(OutboxFailure.EXPIRED, expired.failure)
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertTrue(h.repo.canRetryFailedWrite(expired))

        assertTrue(h.repo.retryFailedWrite("edit-key-0001"))
        val retried = h.repo.queuedRecordWrites().single()
        assertEquals("the age counts from now", h.now, retried.createdAtMillis)
        assertEquals("the key is not renewed", expired.issuedAtMillis, retried.issuedAtMillis)
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals("edit-key-0001", h.http.posts().single().headers["Idempotency-Key"])
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
    }

    // Pairing

    @Test
    fun aWriteThatFailedUnderAnEarlierPairingIsNotQueuedForTheNewOne() {
        val h = Harness()
        val began = h.repo.pairingGeneration()
        h.generation.advance()

        val title = """{"title":"A"}"""
        val diary = editBody(0, "text" to diaryText)
        val late = h.repo.enqueueRecordWrite(began, OutboxKind.TASK_CREATE, Outbox.NEW_SUBJECT, 0, title, CREATE_KEY)
        val lateJournal = h.repo.enqueueRecordWrite(began, OutboxKind.JOURNAL_CREATE, Outbox.NEW_SUBJECT, 0, diary, JOURNAL_KEY)

        assertEquals(EnqueueResult.NOT_PAIRED, late.result)
        assertNull(late.entry)
        assertEquals(EnqueueResult.NOT_PAIRED, lateJournal.result)
        assertNull(lateJournal.entry)
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertNull(h.outboxText.text)
        assertNull(h.journalText.text)
    }

    @Test
    fun withoutAPairingNoWriteIsQueued() {
        val h = Harness(paired = false)
        val result = h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "A"), "edit-key-0001")
        assertEquals(EnqueueResult.NOT_PAIRED, result.result)
        assertNull(result.entry)
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertNull(h.outboxText.text)
    }

    // The journal queue

    private fun Harness.queueJournalAndTask() {
        queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to diaryText), JOURNAL_KEY)
        queueNew(OutboxKind.TASK_CREATE, """{"title":"Köp mjölk"}""", CREATE_KEY)
    }

    @Test
    fun aJournalWriteGoesToTheEncryptedQueueAndNeverToTheOutbox() {
        val h = Harness()
        val queued = h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to diaryText), JOURNAL_KEY)

        assertEquals(EnqueueResult.QUEUED, queued.result)
        assertEquals(createEntry, queued.entry!!.path)
        assertTrue(h.outbox.pending().isEmpty())
        assertNull("the outbox file was never written", h.outboxText.text)
        assertEquals(listOf(JOURNAL_KEY), h.journalOutbox.pending().map { it.idempotencyKey })
        assertFalse(h.journalText.text!!.contains(diaryText))
        assertFalse(h.journalText.text!!.contains(JOURNAL_KEY))
        assertEquals(listOf(JOURNAL_KEY), h.repo.queuedRecordWrites().map { it.idempotencyKey })
    }

    @Test
    fun theDrainSendsTheOutboxFirstAndThenTheJournalQueue() {
        val h = Harness()
        h.queueJournalAndTask()
        assertEquals(setOf(JOURNAL_KEY, CREATE_KEY), h.repo.queuedRecordWrites().map { it.idempotencyKey }.toSet())
        h.serveToday()
        h.answer(createTask, HttpResult(200, "{}"))
        h.answer(createEntry, HttpResult(200, "{}"))

        assertEquals(SyncResult.UPDATED, h.repo.sync())

        assertEquals(listOf(CREATE_KEY, JOURNAL_KEY), h.http.posts().map { it.headers["Idempotency-Key"] })
        assertEquals(listOf(createTask, createEntry), h.http.posts().map { it.url.removePrefix("https://sidekick.example") })
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertTrue(h.journalOutbox.pending().isEmpty())
        assertFalse("nothing of the text is left in the queue file", h.journalText.text.orEmpty().contains(diaryText))
    }

    @Test
    fun aRefusedJournalWriteIsKeptAsFailedAndCanBeRetriedOrRemovedFromTheOneList() {
        val h = Harness()
        h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to diaryText), JOURNAL_KEY)
        h.serveToday()
        h.answer(createEntry, HttpResult(422, "{}"))
        h.repo.sync()
        assertEquals(listOf(JOURNAL_KEY), h.repo.failedWrites().map { it.idempotencyKey })
        assertTrue(h.repo.queuedRecordWrites().isEmpty())

        assertTrue(h.repo.retryFailedWrite(JOURNAL_KEY))
        assertEquals(1, h.repo.queuedRecordWrites().size)
        h.repo.sync()
        assertEquals(1, h.repo.failedWrites().size)

        assertTrue(h.repo.discardFailedWrite(JOURNAL_KEY))
        assertTrue(h.repo.failedWrites().isEmpty())
        assertFalse(h.journalText.text.orEmpty().contains(diaryText))
    }

    @Test
    fun clearingEverythingEmptiesBothQueues() {
        val h = Harness()
        h.queueJournalAndTask()
        assertTrue(h.outbox.hasData())
        assertTrue(h.journalOutbox.hasData())

        h.repo.clearAll()

        assertFalse(h.outbox.hasData())
        assertFalse(h.journalOutbox.hasData())
        assertNull(h.outboxText.text)
        assertNull(h.journalText.text)
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertFalse(h.repo.hasPending())
    }

    // Erasing the journal queue when it is empty

    @Test
    fun theJournalFileAndKeyAreErasedWhenTheLastEntryIsConfirmedAndTheNextEntryMakesANewKey() {
        val h = Harness()
        h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to diaryText), JOURNAL_KEY)
        assertNotNull(h.journalText.text)
        assertNotNull(h.journalKeys.existing())
        assertEquals(1, h.journalKeys.created)
        h.serveToday()
        h.answer(createEntry, HttpResult(201, "{}"))

        h.repo.sync()

        assertTrue(h.journalOutbox.pending().isEmpty())
        assertNull("no file is left", h.journalText.text)
        assertNull("no key is left", h.journalKeys.existing())
        assertFalse(h.journalOutbox.hasData())

        assertEquals(EnqueueResult.QUEUED, h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to "Nästa"), JOURNAL_KEY_2).result)
        assertEquals(2, h.journalKeys.created)
        assertEquals(listOf(JOURNAL_KEY_2), h.journalOutbox.pending().map { it.idempotencyKey })
    }

    @Test
    fun theJournalFileStaysWhileAnotherEntryOrAFailedOneIsInTheQueue() {
        val h = Harness()
        h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to diaryText), JOURNAL_KEY)
        h.queueNew(OutboxKind.JOURNAL_CREATE, editBody(0, "text" to "Två"), JOURNAL_KEY_2)
        h.journalOutbox.remove(Outbox.NEW_SUBJECT, JOURNAL_KEY)
        assertNotNull(h.journalText.text)
        assertNotNull(h.journalKeys.existing())

        h.journalOutbox.markRejected(Outbox.NEW_SUBJECT, JOURNAL_KEY_2)
        assertNotNull("a failed entry is still the user's text", h.journalText.text)
        assertNotNull(h.journalKeys.existing())
        assertEquals(1, h.journalOutbox.failed().size)

        assertTrue(h.journalOutbox.discardFailed(JOURNAL_KEY_2))
        assertNull(h.journalText.text)
        assertNull(h.journalKeys.existing())
    }

    // An edit is never folded into a write that is being sent

    @Test
    fun anEditIsNotFoldedIntoAnEntryThatIsBeingSentAndCanBeQueuedOnceItIsDone() {
        val h = Harness()
        val first = editBody(3, "title" to "Ny rubrik")
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, first, "edit-key-0001")
        val sent = h.outbox.pending().single()

        assertTrue(h.outbox.claim(sent))
        assertNull(h.outbox.editTask(3, editBody(3, "note" to "Anteckning"), "edit-key-0002"))
        assertEquals(first, h.outbox.pending().single().bodyJson())
        assertEquals("edit-key-0001", h.outbox.pending().single().idempotencyKey)

        h.outbox.release(sent)
        val folded = h.outbox.editTask(3, editBody(3, "note" to "Anteckning"), "edit-key-0002")
        assertNotNull(folded)
        val body = JSONObject(folded!!.bodyJson())
        assertEquals("Ny rubrik", body.getString("title"))
        assertEquals("Anteckning", body.getString("note"))
    }

    @Test
    fun anEntryThatWasFoldedAfterItWasReadIsNotSentWithItsOldBody() {
        val h = Harness()
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "Ny rubrik"), "edit-key-0001")
        val read = h.outbox.pending().single()
        h.outbox.editTask(3, editBody(3, "note" to "Anteckning"), "edit-key-0002")

        assertFalse("the entry there now has another body and key", h.outbox.claim(read))
        assertTrue(h.outbox.claim(h.outbox.pending().single()))
    }

    @Test
    fun anEditMadeWhileAnotherRowIsBeingSentIsFoldedAndSentWholeByTheNextRun() {
        val h = Harness()
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "Ny rubrik"), "edit-key-0001")
        h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 4, editBody(4, "name" to "Projekt"), "edit-key-0002")
        h.serveToday()
        h.http.on {
            if (it.method == "POST" && it.url.endsWith(editTask)) {
                // The page edits the project again while the drain is busy with the task: it folds into the entry the
                // drain has already read.
                h.queue(OutboxKind.PROJECT_EDIT, PROJECT, 4, editBody(4, "note" to "Anteckning"), "edit-key-0003")
                HttpResult(200, "{}")
            } else {
                null
            }
        }
        h.answer(editProject, HttpResult(200, "{}"))

        assertEquals("the skipped entry is for the next run", SyncResult.RETRY, h.repo.sync())
        assertEquals(listOf(editTask), h.http.posts().map { it.url.removePrefix("https://sidekick.example") })
        assertEquals(1, h.repo.queuedRecordWrites().size)

        assertEquals(SyncResult.UPDATED, h.repo.sync())
        val sent = h.http.posts().last()
        assertTrue(sent.url.endsWith(editProject))
        val body = sent.json()
        assertEquals("Projekt", body.getString("name"))
        assertEquals("Anteckning", body.getString("note"))
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
    }

    @Test
    fun anEditMadeWhileItsOwnRowIsBeingSentIsRefusedNotLostAndCanBeQueuedAfterwards() {
        val h = Harness()
        h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "title" to "Ny rubrik"), "edit-key-0001")
        h.serveToday()
        var during: EnqueueResult? = null
        h.http.on {
            if (it.method == "POST" && it.url.endsWith(editTask)) {
                during = h.queue(OutboxKind.TASK_EDIT, TASK_A, 3, editBody(3, "note" to "Anteckning"), "edit-key-0002").result
                HttpResult(200, "{}")
            } else {
                null
            }
        }

        h.repo.sync()

        assertEquals("the page is told, and retries", EnqueueResult.STORAGE_FAILED, during)
        assertTrue(h.repo.queuedRecordWrites().isEmpty())
        assertEquals(
            EnqueueResult.QUEUED,
            h.queue(OutboxKind.TASK_EDIT, TASK_A, 4, editBody(4, "note" to "Anteckning"), "edit-key-0002").result,
        )
    }

    private companion object {
        const val JOURNAL_KEY = "note-key-0001"
        const val JOURNAL_KEY_2 = "note-key-0002"
        const val CREATE_KEY = "new-key-0001"
        const val CREATE_KEY_2 = "new-key-0002"
        const val PROJECT = "55555555-6666-4777-8888-999999999999"
        const val ENTRY = "66666666-7777-4888-8999-aaaaaaaaaaaa"
    }
}
