package com.roadlake.sidekick.today

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OutboxTest {
    private val store = MemoryTextStore()
    private var now = 1_000L
    private fun outbox() = Outbox(store) { now }

    @Test
    fun anEntrySurvivesAProcessRestart() {
        outbox().enqueue(TASK_A, 3, "widget-key-1")
        val after = outbox().pending().single()
        assertEquals(TASK_A, after.subjectId)
        assertEquals(3, after.version)
        assertEquals("widget-key-1", after.idempotencyKey)
    }

    @Test
    fun aSecondTapOnTheSameTaskKeepsTheFirstKeyAndVersion() {
        val outbox = outbox()
        val first = outbox.enqueue(TASK_A, 3, "widget-key-1")
        val second = outbox.enqueue(TASK_A, 9, "widget-key-2")
        assertEquals(first!!.idempotencyKey, second!!.idempotencyKey)
        assertEquals(3, second.version)
        assertEquals(1, outbox.pending().size)
    }

    @Test
    fun retriesCountAttemptsAndKeepTheKey() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        outbox.recordAttempt(TASK_A, "widget-key-1")
        outbox.recordAttempt(TASK_A, "widget-key-1")
        val entry = outbox.pending().single()
        assertEquals(2, entry.attempts)
        assertEquals("widget-key-1", entry.idempotencyKey)
    }

    @Test
    fun removeNeedsTheMatchingKeySoANewerTapIsNotLost() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        outbox.remove(TASK_A, "widget-key-0")
        assertTrue(outbox.contains(TASK_A))
        outbox.remove(TASK_A, "widget-key-1")
        assertFalse(outbox.contains(TASK_A))
    }

    @Test
    fun anOldEntryIsDroppedInsteadOfAppliedLongAfterTheTap() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertTrue(outbox.pending().isEmpty())
        assertTrue(outbox.enqueue(TASK_A, 4, "widget-key-2")!!.version == 4)
    }

    @Test
    fun anExpiredEntryIsCountedUntilTheUserHasBeenToldAndTheCountHoldsNoTaskData() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        assertEquals(0, outbox.expiredCount())
        now += Outbox.MAX_AGE_MILLIS + 1
        assertEquals(1, outbox.expiredCount())
        assertTrue(outbox.pending().isEmpty())
        assertEquals("a restart keeps the count", 1, outbox().expiredCount())
        assertFalse("only a number is stored for it", store.text!!.contains(TASK_A))
        outbox.enqueue(TASK_B, 1, "widget-key-2")
        assertEquals("a new entry does not reset it", 1, outbox.expiredCount())
        outbox.clearExpired()
        assertEquals(0, outbox.expiredCount())
        assertEquals(TASK_B, outbox.pending().single().subjectId)
    }

    @Test
    fun isBoundedAndNeverBreaksOnDiskFailureOrGarbage() {
        val outbox = outbox()
        for (i in 1..Outbox.MAX_ENTRIES) assertNotNull(outbox.enqueue("00000000-0000-4000-8000-%012d".format(i), 1, "widget-key-$i"))
        assertNull(outbox.enqueue(TASK_A, 1, "widget-key-x"))
        store.text = "garbage"
        assertTrue(outbox().pending().isEmpty())
        store.text = null
        store.failWrites = true
        assertNull(outbox().enqueue(TASK_A, 1, "widget-key-1"))
    }

    @Test
    fun clearRemovesEverything() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        outbox.clear()
        assertTrue(outbox.pending().isEmpty())
        assertFalse(outbox.hasData())
    }

    @Test
    fun aMissingFileIsAnEmptyQueueThatCanBeStarted() {
        val outbox = outbox()
        assertTrue(outbox.pending().isEmpty())
        assertFalse(outbox.hasData())
        assertNotNull(outbox.enqueue(TASK_A, 3, "widget-key-1"))
    }

    @Test
    fun aReadErrorLeavesTheStoredQueueUntouchedAndStopsEveryChange() {
        outbox().enqueue(TASK_A, 3, "widget-key-1")
        val before = store.text
        val writesBefore = store.writes
        store.failReads = true
        val outbox = outbox()
        assertNull(outbox.enqueue(TASK_B, 1, "widget-key-2"))
        outbox.recordAttempt(TASK_A, "widget-key-1")
        outbox.remove(TASK_A, "widget-key-1")
        assertTrue(outbox.pending().isEmpty())
        assertTrue(outbox.hasData())
        assertEquals(before, store.text)
        assertEquals(writesBefore, store.writes)
        store.failReads = false
        assertEquals("widget-key-1", outbox().pending().single().idempotencyKey)
    }

    @Test
    fun anUnparsableFileIsMovedAsideNotOverwritten() {
        var quarantines = 0
        store.text = "garbage"
        val outbox = Outbox(store, { quarantines++ }) { now }
        assertTrue(outbox.pending().isEmpty())
        assertEquals("garbage", store.quarantined)
        assertEquals(1, quarantines)
        assertNotNull(outbox.enqueue(TASK_A, 3, "widget-key-1"))
        assertEquals("garbage", store.quarantined)
        assertEquals("widget-key-1", outbox.pending().single().idempotencyKey)
    }

    @Test
    fun anUnknownFormatIsMovedAsideToo() {
        store.text = """{"format": 99, "entries": []}"""
        assertNotNull(outbox().enqueue(TASK_A, 3, "widget-key-1"))
        assertEquals("""{"format": 99, "entries": []}""", store.quarantined)
    }

    @Test
    fun ifTheFileCannotBeMovedAsideNothingIsChanged() {
        store.text = "garbage"
        store.failQuarantine = true
        val outbox = outbox()
        assertNull(outbox.enqueue(TASK_A, 3, "widget-key-1"))
        assertEquals("garbage", store.text)
        assertEquals(0, store.writes)
    }

    @Test
    fun aPurchaseIsQueuedBesideACompletionOfTheSameIdAndKeepsItsAskedState() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        val purchase = outbox.enqueuePurchase(TASK_A, 7, true, "shop-key-0001")!!
        assertEquals(OutboxKind.SHOPPING_PURCHASE, purchase.kind)
        assertEquals("/companion/v1/shopping/items/$TASK_A/purchased", purchase.path)
        val body = org.json.JSONObject(purchase.bodyJson())
        assertEquals(7, body.getInt("version"))
        assertTrue(body.getBoolean("purchased"))
        assertEquals(2, body.length())
        val again = outbox().pending()
        assertEquals(2, again.size)
        assertEquals(OutboxKind.SHOPPING_PURCHASE, again[1].kind)
        assertTrue(again[1].purchased)
        assertTrue("the task completion is still there", outbox().contains(TASK_A))
    }

    @Test
    fun aSecondPurchaseOfTheSameItemKeepsTheFirstStateKeyAndVersion() {
        val outbox = outbox()
        outbox.enqueuePurchase(TASK_A, 7, true, "shop-key-0001")
        val second = outbox.enqueuePurchase(TASK_A, 8, false, "shop-key-0002")!!
        assertEquals("shop-key-0001", second.idempotencyKey)
        assertTrue(second.purchased)
        assertEquals(7, second.version)
        assertEquals(1, outbox.pending().size)
    }

    @Test
    fun aQueueWrittenBeforePurchasesExistedIsReadAsCompletions() {
        store.text = """{"format":1,"entries":[{"task":"$TASK_A","version":3,"key":"widget-key-1","at":1000}],"expired":0}"""
        val entry = outbox().pending().single()
        assertEquals(OutboxKind.TASK_COMPLETION, entry.kind)
        assertEquals("""{"version":3}""", entry.bodyJson())
    }

    @Test
    fun aCompletionIsStoredExactlyAsBeforeSoAnOlderAppStillReadsIt() {
        outbox().enqueue(TASK_A, 3, "widget-key-1")
        assertFalse(store.text!!.contains("kind"))
    }

    @Test
    fun anEntryOfAnUnknownKindIsMovedAsideNotGuessedAt() {
        val text = """{"format":1,"entries":[{"task":"$TASK_A","version":3,"key":"widget-key-1","at":1000,"kind":"later"}]}"""
        store.text = text
        assertTrue(outbox().pending().isEmpty())
        assertEquals(text, store.quarantined)
    }

    @Test
    fun anExpiredPurchaseIsNotSentButKeptAsFailedAndNotCountedAsAnUnsentTask() {
        val outbox = outbox()
        outbox.enqueuePurchase(TASK_A, 7, true, "shop-key-0001")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertTrue(outbox.pending().isEmpty())
        assertEquals(0, outbox.expiredCount())
        val failed = outbox.failed().single()
        assertEquals(OutboxFailure.EXPIRED, failed.failure)
        assertEquals("shop-key-0001", failed.idempotencyKey)
    }

    @Test
    fun anAddedItemIsQueuedWithItsBodyAndKeyAndSurvivesARestart() {
        val body = """{"items":[{"name":"Milk","client_ref":"0"}],"merge_duplicates":false}"""
        val added = outbox().enqueueShoppingAdd(LIST, body, "add-key-0001")!!
        assertEquals(OutboxKind.SHOPPING_ADD, added.kind)
        assertEquals("/companion/v1/shopping/lists/$LIST/items", added.path)
        assertEquals(body, added.bodyJson())
        val after = outbox().pending().single()
        assertEquals(OutboxKind.SHOPPING_ADD, after.kind)
        assertEquals("add-key-0001", after.idempotencyKey)
        assertEquals(body, after.bodyJson())
    }

    @Test
    fun theSameKeyIsTheSameAddButANewKeyOnTheSameListIsAnotherAdd() {
        val outbox = outbox()
        val first = outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")!!
        val again = outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Other"}]}""", "add-key-0001")!!
        assertEquals(first.bodyJson(), again.bodyJson())
        assertEquals(1, outbox.pending().size)
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Bread"}]}""", "add-key-0002")
        assertEquals(listOf("add-key-0001", "add-key-0002"), outbox.pending().map { it.idempotencyKey })
    }

    @Test
    fun aRetryOfAnAddKeepsItsKeyAndBodyAndAnAnsweredOneLeavesTheQueue() {
        val outbox = outbox()
        val body = """{"items":[{"name":"Milk"}]}"""
        outbox.enqueueShoppingAdd(LIST, body, "add-key-0001")
        outbox.recordAttempt(LIST, "add-key-0001")
        val entry = outbox.pending().single()
        assertEquals(1, entry.attempts)
        assertEquals(body, entry.bodyJson())
        outbox.remove(LIST, "add-key-0001")
        assertTrue(outbox.pending().isEmpty())
    }

    @Test
    fun anAddBodyOverTheCapIsNotKept() {
        val huge = """{"items":[{"name":"${"x".repeat(Outbox.MAX_PAYLOAD_CHARS)}"}]}"""
        assertNull(outbox().enqueueShoppingAdd(LIST, huge, "add-key-0001"))
        assertTrue(outbox().pending().isEmpty())
    }

    @Test
    fun anExpiredAddIsKeptAsFailedWithItsBodyAndNotCountedAsAnUnsentTask() {
        val outbox = outbox()
        val body = """{"items":[{"name":"Milk"}]}"""
        outbox.enqueueShoppingAdd(LIST, body, "add-key-0001")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertTrue(outbox.pending().isEmpty())
        assertEquals(0, outbox.expiredCount())
        val failed = outbox().failed().single()
        assertEquals(OutboxFailure.EXPIRED, failed.failure)
        assertEquals(body, failed.bodyJson())
    }

    @Test
    fun anExpiredTaskCompletionIsStillDroppedAndCounted() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertTrue(outbox.failed().isEmpty())
        assertEquals(1, outbox.expiredCount())
    }

    @Test
    fun aRejectedAddStaysAsFailedAcrossARestartAndIsNotPending() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        outbox.markRejected(LIST, "add-key-0001")
        assertTrue(outbox().pending().isEmpty())
        assertEquals(OutboxFailure.REJECTED, outbox().failed().single().failure)
    }

    @Test
    fun aRejectedTaskCompletionIsNotKeptAsFailed() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1")
        outbox.markRejected(TASK_A, "widget-key-1")
        assertTrue(outbox.failed().isEmpty())
        assertEquals(1, outbox.pending().size)
    }

    @Test
    fun retryingAFailedWriteQueuesItAgainWithTheSameKeyAndAFreshAge() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertEquals(1, outbox.failed().size)
        assertTrue(outbox.retryFailed("add-key-0001"))
        val again = outbox.pending().single()
        assertEquals("add-key-0001", again.idempotencyKey)
        assertNull(again.failure)
        assertEquals(now, again.createdAtMillis)
        assertTrue(outbox.failed().isEmpty())
        assertFalse("nothing failed is left to retry", outbox.retryFailed("add-key-0001"))
    }

    @Test
    fun aFailedWriteWhoseKeyIsOlderThanTheServersWindowCannotBeRetriedOnlyRemoved() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        now += Outbox.MAX_AGE_MILLIS + 1
        assertEquals(1, outbox.failed().size)
        now += Outbox.MAX_KEY_AGE_MILLIS // the key is now older than the server remembers
        assertFalse("a re-sent add would be a second add", outbox.retryFailed("add-key-0001"))
        assertTrue(outbox().pending().isEmpty())
        assertFalse(outbox().failed().single().keyStillSafe(now))
        assertTrue(outbox.discardFailed("add-key-0001"))
        assertTrue(outbox.failed().isEmpty())
    }

    @Test
    fun aRetryDoesNotRenewTheAgeOfTheKeySoRepeatedRetriesCannotOutliveTheWindow() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        val issued = now
        var retries = 0
        while (true) {
            now += Outbox.MAX_AGE_MILLIS + 1
            outbox.pending() // moves it to failed
            if (!outbox.retryFailed("add-key-0001")) break
            assertEquals(issued, outbox.pending().single().issuedAtMillis)
            retries++
            assertTrue("a retry is always within the window", now - issued <= Outbox.MAX_KEY_AGE_MILLIS)
        }
        assertTrue(retries in 1..4)
        assertTrue(outbox.pending().isEmpty())
        assertEquals(1, outbox.failed().size)
    }

    @Test
    fun aPendingWriteIsNeverSentOnceItsKeyIsOlderThanTheWindowEvenWithinSevenDaysOfItsRetry() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        now += Outbox.MAX_KEY_AGE_MILLIS - 1_000
        outbox.markRejected(LIST, "add-key-0001")
        assertTrue(outbox.retryFailed("add-key-0001"))
        now += 2_000 // the key crosses the limit while it is pending
        assertTrue(outbox.pending().isEmpty())
        assertEquals(OutboxFailure.EXPIRED, outbox.failed().single().failure)
    }

    @Test
    fun anOldQueueFileWithoutAnIssuedTimeReadsTheCreationTimeAsIt() {
        store.write(
            """{"format":1,"expired":0,"entries":[{"task":"$LIST","version":0,"key":"add-key-0001","at":500,"attempts":0,"kind":"add","purchased":false,"payload":"{}"}]}""",
        )
        assertEquals(500L, outbox().pending().single().issuedAtMillis)
    }

    @Test
    fun discardingAFailedWriteRemovesItButNeverAPendingOne() {
        val outbox = outbox()
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        outbox.enqueueShoppingAdd(LIST, """{"items":[{"name":"Bread"}]}""", "add-key-0002")
        outbox.markRejected(LIST, "add-key-0001")
        assertFalse(outbox.discardFailed("add-key-0002"))
        assertTrue(outbox.discardFailed("add-key-0001"))
        assertTrue(outbox.failed().isEmpty())
        assertEquals(listOf("add-key-0002"), outbox.pending().map { it.idempotencyKey })
    }

    @Test
    fun aNewPurchaseOfAnItemWithAFailedOneIsAnotherEntry() {
        val outbox = outbox()
        outbox.enqueuePurchase(TASK_A, 7, true, "shop-key-0001")
        outbox.markRejected(TASK_A, "shop-key-0001")
        val second = outbox.enqueuePurchase(TASK_A, 8, false, "shop-key-0002")!!
        assertEquals("shop-key-0002", second.idempotencyKey)
        assertEquals(1, outbox.failed().size)
        assertEquals(1, outbox.pending().size)
    }

    // The widget's undo window: the completion is queued (and shown as queued) but held, and Undo only removes the entry.

    @Test
    fun aHeldEntryIsQueuedButHeldUntilItsWindowEnds() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1", holdMillis = 5_000)
        val entry = outbox.pending().single()
        assertTrue(outbox.contains(TASK_A))
        assertTrue(entry.isHeld(now))
        assertTrue(entry.isHeld(now + 4_999))
        assertFalse(entry.isHeld(now + 5_000))
        assertEquals(now + 5_000, outbox.nextSendAtMillis())
        now += 5_000
        assertNull("nothing is held any more", outbox.nextSendAtMillis())
    }

    @Test
    fun aHoldSurvivesARestartAndAnEntryWithoutOneIsNeverHeld() {
        outbox().enqueue(TASK_A, 3, "widget-key-1", holdMillis = 5_000)
        outbox().enqueue(TASK_B, 1, "widget-key-2")
        val after = outbox().pending()
        assertTrue(after.first { it.subjectId == TASK_A }.isHeld(now))
        assertFalse(after.first { it.subjectId == TASK_B }.isHeld(now))
        assertTrue(store.text!!.contains("notBefore"))
        assertEquals("an entry without a hold is written as before", 1, Regex("notBefore").findAll(store.text!!).count())
    }

    @Test
    fun undoTakesAHeldCompletionOutOfTheQueueAndNothingElse() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1", holdMillis = 5_000)
        outbox.enqueue(TASK_B, 1, "widget-key-2", holdMillis = 5_000)
        now += 2_000
        assertTrue(outbox.undoHeld(TASK_A))
        assertEquals(listOf(TASK_B), outbox.pending().map { it.subjectId })
        assertFalse("a second Undo finds nothing", outbox.undoHeld(TASK_A))
    }

    @Test
    fun undoComesTooLateOnceTheWindowHasEndedOrForAnEntryThatWasNeverHeld() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1", holdMillis = 5_000)
        outbox.enqueue(TASK_B, 1, "widget-key-2")
        now += 5_000
        assertFalse(outbox.undoHeld(TASK_A))
        assertFalse(outbox.undoHeld(TASK_B))
        assertEquals(2, outbox.pending().size)
    }

    @Test
    fun aHoldIsBoundedAndEndsWhenTheClockWasSetBack() {
        val outbox = outbox()
        outbox.enqueue(TASK_A, 3, "widget-key-1", holdMillis = Outbox.MAX_HOLD_MILLIS * 100)
        val capped = outbox.pending().single()
        assertEquals(now + Outbox.MAX_HOLD_MILLIS, capped.notBeforeMillis)

        val forged = OutboxEntry(TASK_B, 1, "widget-key-2", createdAtMillis = now, notBeforeMillis = now + 10 * Outbox.MAX_HOLD_MILLIS)
        assertFalse("a hold longer than the bound is no hold", forged.isHeld(now))
        assertFalse("the clock went back before the entry was made", capped.isHeld(now - 1))
    }
}
