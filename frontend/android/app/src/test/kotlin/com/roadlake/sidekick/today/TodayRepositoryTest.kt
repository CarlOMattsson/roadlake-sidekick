package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.companion.Pairing
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TodayRepositoryTest {
    private val todayCall = "/companion/v1/work/today"
    private val completeA = "/companion/v1/tasks/$TASK_A/complete"

    private fun Harness.serveToday(vararg items: String) =
        http.on { if (it.url.contains(todayCall)) HttpResult(200, todayPage(*items)) else null }

    private fun Harness.readToday(vararg items: String) {
        serveToday(*items)
        assertEquals(SyncResult.UPDATED, repo.sync())
    }

    private fun Harness.ready() = repo.state() as TodayState.Ready

    @Test
    fun readsTodayWithTheCompanionTodayRouteAndKeepsTheTitlesInTheCache() {
        val h = Harness()
        h.readToday(item(TASK_A, "Köp mjölk", version = 3))
        val call = h.http.calls.single()
        assertEquals("GET", call.method)
        assertTrue(call.url.startsWith("https://sidekick.example$todayCall?"))
        assertEquals("limit=20", call.url.substringAfter("?"))
        val state = h.ready()
        assertEquals("Köp mjölk", state.snapshot.tasks.single().title)
        assertEquals(1_000_000L, state.snapshot.syncedAtMillis)
        assertEquals(1, state.snapshot.total)
        assertEquals("2026-11-09", state.snapshot.day)
        assertFalse(h.cacheText.text!!.contains("SECRET NOTE"))
    }

    @Test
    fun withoutAPairingTheWidgetIsNotPairedAndLeftoversAreRemoved() {
        val h = Harness(paired = false)
        h.cacheText.text = "{}"
        h.outboxText.text = "{}"
        assertEquals(TodayState.NotPaired, h.repo.state())
        assertNull(h.cacheText.text)
        assertNull(h.outboxText.text)
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertTrue(h.http.calls.isEmpty())
    }

    @Test
    fun beforeTheFirstReadItIsLoadingAndACacheOfAnotherServerIsNotUsed() {
        val h = Harness()
        assertEquals(TodayState.Loading, h.repo.state())
        h.cache.save(TodaySnapshot("other.example", 1L, listOf(TodayTask(TASK_A, "Annans", 1, false)), 1))
        assertEquals(TodayState.Loading, h.repo.state())
        assertEquals(EnqueueResult.UNKNOWN_TASK, h.repo.enqueueCompletion(TASK_A))
    }

    @Test
    fun aTapQueuesTheCompletionAndShowsPendingWithoutNetwork() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B", version = 1))
        h.http.calls.clear()
        assertEquals(EnqueueResult.QUEUED, h.repo.enqueueCompletion(TASK_A))
        assertTrue(h.http.calls.isEmpty())
        assertEquals(setOf(TASK_A), h.ready().pendingTaskIds)
        assertEquals(2, h.ready().snapshot.tasks.size)
    }

    @Test
    fun aDoubleTapSendsOneRequestWithOneKey() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(200, "{}") else null }
        h.repo.sync()
        val post = h.http.posts().single()
        assertEquals("widget-key-1", post.headers["Idempotency-Key"])
        assertEquals(3, JSONObject(String(post.body!!)).getInt("version"))
        assertEquals("Bearer rsc_abcdefghijklmnopqrstuvwxyz0123456789", post.headers["Authorization"])
    }

    @Test
    fun aConfirmedCompletionLeavesTheOutboxAndTheRow() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B"))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(200, "{}") else null }
        h.serveToday(item(TASK_B, "B")) // the server now lists only B
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        val state = h.ready()
        assertTrue(state.pendingTaskIds.isEmpty())
        assertTrue(h.outbox.pending().isEmpty())
        assertEquals(listOf(TASK_B), state.snapshot.tasks.map { it.id })
        assertEquals(1, h.http.posts().size)
    }

    @Test
    fun anUnknownOutcomeRetriesWithTheSameKeyAndVersion() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        var failing = true
        h.http.on {
            if (!it.url.endsWith(completeA)) {
                null
            } else if (failing) {
                CompanionException("timeout")
            } else {
                HttpResult(200, "{}")
            }
        }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertEquals(setOf(TASK_A), h.ready().pendingTaskIds)
        assertEquals(1, h.outbox.pending().single().attempts)
        failing = false
        h.repo.sync()
        val posts = h.http.posts()
        assertEquals(2, posts.size)
        assertEquals(posts[0].headers["Idempotency-Key"], posts[1].headers["Idempotency-Key"])
        assertEquals(posts[0].body!!.toList(), posts[1].body!!.toList())
        assertTrue(h.ready().pendingTaskIds.isEmpty())
    }

    @Test
    fun aServerErrorKeepsTheEntryForALaterRetry() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(503, "{}") else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertTrue(h.outbox.contains(TASK_A))
    }

    @Test
    fun aCompletionThatExpiredUnsentIsShownOnceAsExpired() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.now += Outbox.MAX_AGE_MILLIS + 1
        h.serveToday(item(TASK_A, "A", version = 3))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue("it is never sent", h.http.posts().isEmpty())
        val state = h.ready()
        assertEquals(TodayNotice.EXPIRED, state.snapshot.notice)
        assertTrue(state.pendingTaskIds.isEmpty())
        // Told once: the next clean read removes the notice.
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertNull(h.ready().snapshot.notice)
    }

    @Test
    fun anExpiredNoticeSurvivesAFailedReadAndTheForegroundReadIsNotSkippedForIt() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.now += Outbox.MAX_AGE_MILLIS + 1
        h.repo.state() // a redraw drops the entry first
        h.http.on { if (it.url.contains(todayCall)) CompanionException("network") else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertEquals(TodayNotice.EXPIRED, h.ready().snapshot.notice)
        h.http.on { if (it.url.contains(todayCall)) HttpResult(200, todayPage(item(TASK_A, "A", version = 3))) else null }
        h.now += 1_000
        assertEquals(SyncResult.UPDATED, h.repo.syncIfStale(60_000))
        assertEquals(TodayNotice.EXPIRED, h.ready().snapshot.notice)
        // The notice was stored by a clean read, so the count is cleared and a fresh read is skipped again.
        assertNull(h.repo.syncIfStale(60_000))
    }

    @Test
    fun aConflictOutranksTheExpiredNotice() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B", version = 1))
        h.repo.enqueueCompletion(TASK_A)
        h.now += Outbox.MAX_AGE_MILLIS - 10
        h.repo.enqueueCompletion(TASK_B)
        h.now += 20 // A is now too old, B is not
        h.http.on { if (it.url.endsWith("/companion/v1/tasks/$TASK_B/complete")) HttpResult(409, "{}") else null }
        h.serveToday(item(TASK_A, "A", version = 3))
        h.repo.sync()
        assertEquals(TodayNotice.CONFLICT, h.ready().snapshot.notice)
    }

    @Test
    fun aConflictRereadsTodayAndNeverResendsWithANewVersion() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(409, """{"code":"version_conflict"}""") else null }
        h.serveToday(item(TASK_A, "A ändrad", version = 5)) // the reread shows the Task at version 5
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals(1, h.http.posts().size)
        assertTrue(h.outbox.pending().isEmpty())
        val state = h.ready()
        assertEquals(TodayNotice.CONFLICT, state.snapshot.notice)
        assertEquals(5, state.snapshot.tasks.single().version)
        assertTrue(state.pendingTaskIds.isEmpty())
        // The user decides: nothing is sent again by itself, and a later clean read removes the notice.
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertNull(h.ready().snapshot.notice)
        assertEquals(1, h.http.posts().size)
    }

    @Test
    fun aConflictWhileOfflineStillDropsTheStaleRow() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(409, "{}") else null }
        h.http.on { if (it.url.contains(todayCall)) CompanionException("network") else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        val state = h.ready()
        assertTrue(state.snapshot.tasks.isEmpty())
        assertEquals(TodayNotice.CONFLICT, state.snapshot.notice)
    }

    @Test
    fun aRefusalOtherThanConflictIsShownAsRejected() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(403, "{}") else null }
        h.repo.sync()
        assertEquals(TodayNotice.REJECTED, h.ready().snapshot.notice)
        assertTrue(h.outbox.pending().isEmpty())
    }

    @Test
    fun a401ClearsThePairingTheCacheAndTheOutbox() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"), item(TASK_B, "B"))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(401, """{"code":"unauthorized"}""") else null }
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertNull(h.pairing.pairing)
        assertNull(h.cacheText.text)
        assertNull(h.outboxText.text)
        assertEquals(TodayState.NotPaired, h.repo.state())
    }

    @Test
    fun a401WhileReadingClearsToo() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.on { if (it.url.contains(todayCall)) HttpResult(401, "{}") else null }
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertNull(h.cacheText.text)
        assertNull(h.pairing.pairing)
        assertEquals(TodayState.NotPaired, h.repo.state())
    }

    @Test
    fun aNewPairingStartsWithoutTheOldTitlesOrQueuedCompletions() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueueCompletion(TASK_A)
        h.clearing.save(Pairing("https://sidekick.example", "rsc_zzzzzzzzzzzzzzzz", null))
        assertNull(h.cacheText.text)
        assertNull(h.outboxText.text)
    }

    /** Ends the pairing and starts another while a request of the old one is in flight. */
    private fun Harness.replacePairing() {
        clearing.clear()
        clearing.save(Pairing("https://sidekick.example", "rsc_newnewnewnewnewnewnewnew0123456789", null))
    }

    @Test
    fun aTodayAnswerThatArrivesAfterANewPairingIsNotStoredForIt() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.on {
            if (it.url.contains(todayCall)) {
                h.replacePairing()
                HttpResult(200, todayPage(item(TASK_B, "Old pairing's B")))
            } else {
                null
            }
        }
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertNull(h.cacheText.text)
        assertEquals(TodayState.Loading, h.repo.state())
    }

    @Test
    fun aDrainThatLosesItsPairingSendsNothingMoreAndTouchesNothingOfTheNewOne() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"), item(TASK_B, "B"))
        h.repo.enqueueCompletion(TASK_A)
        h.repo.enqueueCompletion(TASK_B)
        h.http.on {
            if (it.url.endsWith(completeA)) {
                h.replacePairing()
                HttpResult(200, "{}")
            } else {
                null
            }
        }
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertEquals(1, h.http.posts().size)
        assertNull(h.outboxText.text)
        assertNull(h.cacheText.text)
    }

    @Test
    fun aRefusedAnswerAfterANewPairingDoesNotClearTheNewPairingsData() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.on {
            if (it.url.contains(todayCall)) {
                h.replacePairing()
                h.cache.save(TodaySnapshot("sidekick.example", 2L, listOf(TodayTask(TASK_B, "New", 1, false)), 1))
                HttpResult(401, "{}")
            } else {
                null
            }
        }
        // The 401 was for the old credential: the new pairing keeps its own Today.
        assertEquals(SyncResult.NOT_PAIRED, h.repo.sync())
        assertEquals("New", h.ready().snapshot.tasks.single().title)
    }

    @Test
    fun theForegroundReadIsSkippedWhenTodayIsFreshAndNothingIsQueued() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.calls.clear()
        h.now += 10_000
        assertNull(h.repo.syncIfStale(60_000))
        assertTrue(h.http.calls.isEmpty())
        h.now += 100_000
        assertEquals(SyncResult.UPDATED, h.repo.syncIfStale(60_000))
        assertEquals(1, h.http.calls.size)
    }

    @Test
    fun aFailedDiskWriteNeverThrowsFromTheCacheAndIsReportedAsRetry() {
        val h = Harness()
        h.cacheText.failWrites = true
        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertEquals(TodayState.Loading, h.repo.state())
        h.cacheText.failWrites = false
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals("A", h.ready().snapshot.tasks.single().title)
    }

    private val purchaseOfItem = "/companion/v1/shopping/items/$ITEM/purchased"

    @Test
    fun aQueuedPurchaseIsSentWithThePagesKeyAndLeavesTheQueueWhenTheServerAnswers() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.calls.clear()
        val queued = h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, true, "page-key-0001")
        assertEquals(EnqueueResult.QUEUED, queued.result)
        assertTrue("queueing sends nothing", h.http.calls.isEmpty())
        assertEquals(listOf(ITEM), h.repo.queuedPurchases().map { it.subjectId })
        assertTrue("a purchase is not a pending Today row", h.ready().pendingTaskIds.isEmpty())
        h.http.on { if (it.url.endsWith(purchaseOfItem)) HttpResult(200, "{}") else null }
        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        val post = h.http.posts().single()
        assertEquals("page-key-0001", post.headers["Idempotency-Key"])
        val body = JSONObject(String(post.body!!))
        assertEquals(4, body.getInt("version"))
        assertTrue(body.getBoolean("purchased"))
        assertTrue(h.repo.queuedPurchases().isEmpty())
        assertEquals("Today keeps its row", listOf(TASK_A), h.ready().snapshot.tasks.map { it.id })
    }

    @Test
    fun aPurchaseWithoutAnAnswerStaysQueuedWithTheSameKey() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, false, "page-key-0001")
        h.http.on { if (it.url.endsWith(purchaseOfItem)) CompanionException("network", beforeSend = true) else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        val entry = h.repo.queuedPurchases().single()
        assertEquals("page-key-0001", entry.idempotencyKey)
        assertEquals(1, entry.attempts)
    }

    @Test
    fun aConflictingPurchaseIsKeptAsFailedWithoutATodayNotice() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, true, "page-key-0001")
        h.http.on { if (it.url.endsWith(purchaseOfItem)) HttpResult(409, """{"code":"conflict"}""") else null }
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue(h.repo.queuedPurchases().isEmpty())
        assertNull(h.ready().snapshot.notice)
        val failed = h.repo.failedShoppingWrites().single()
        assertEquals(OutboxFailure.REJECTED, failed.failure)
        assertEquals("page-key-0001", failed.idempotencyKey)
        assertTrue("a failed write is not sent again", h.repo.sync() == SyncResult.UPDATED)
        assertEquals(1, h.http.posts().size)
    }

    @Test
    fun aRefusedAddStaysVisibleUntilTheUserRetriesOrRemovesIt() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        val addPath = "/companion/v1/shopping/lists/$ITEM/items"
        h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), ITEM, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        h.http.on { if (it.url.endsWith(addPath)) HttpResult(422, """{"code":"invalid_input"}""") else null }
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
        assertEquals(listOf("add-key-0001"), h.repo.failedShoppingWrites().map { it.idempotencyKey })

        assertTrue(h.repo.retryFailedWrite("add-key-0001"))
        assertTrue(h.repo.failedShoppingWrites().isEmpty())
        assertEquals(1, h.repo.queuedShoppingAdds().size)
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals(1, h.repo.failedShoppingWrites().size)

        assertTrue(h.repo.discardFailedWrite("add-key-0001"))
        assertTrue(h.repo.failedShoppingWrites().isEmpty())
        assertFalse(h.repo.discardFailedWrite("add-key-0001"))
    }

    @Test
    fun aFailedWriteBeyondTheServersIdempotencyWindowIsNotRetryableAndNotRetried() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), ITEM, """{"items":[{"name":"Milk"}]}""", "add-key-0001")
        h.now += Outbox.MAX_AGE_MILLIS + 1
        val failed = h.repo.failedShoppingWrites().single()
        assertTrue(h.repo.canRetryFailedWrite(failed))
        h.now += Outbox.MAX_KEY_AGE_MILLIS
        assertFalse(h.repo.canRetryFailedWrite(failed))
        assertFalse("not retried: the server no longer knows the key", h.repo.retryFailedWrite("add-key-0001"))
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
        assertTrue(h.repo.discardFailedWrite("add-key-0001"))
    }

    @Test
    fun aFailedWriteThatIsNotThereIsNeitherRetriedNorRemoved() {
        val h = Harness()
        assertFalse(h.repo.retryFailedWrite("add-key-0404"))
        assertFalse(h.repo.discardFailedWrite("add-key-0404"))
    }

    @Test
    fun withoutAPairingNoPurchaseIsQueued() {
        val h = Harness(paired = false)
        assertEquals(EnqueueResult.NOT_PAIRED, h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, true, "page-key-0001").result)
        assertTrue(h.repo.queuedPurchases().isEmpty())
    }

    @Test
    fun aPurchaseThatFailedUnderAnEarlierPairingIsNotQueuedForTheNewOne() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        // The request began under pairing A; it fails late, after the phone was unpaired and paired again (B).
        val began = h.repo.pairingGeneration()
        h.generation.advance()
        h.generation.advance()

        val late = h.repo.enqueuePurchase(began, ITEM, 4, true, "page-key-0001")

        assertEquals(EnqueueResult.NOT_PAIRED, late.result)
        assertNull(late.entry)
        assertTrue(h.repo.queuedPurchases().isEmpty())
        // The same call bound to the generation that is current now is kept.
        assertEquals(EnqueueResult.QUEUED, h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, true, "page-key-0002").result)
    }

    private val addToList = "/companion/v1/shopping/lists/$LIST/items"
    private val addBody = """{"items":[{"name":"Milk","client_ref":"0"}],"merge_duplicates":false}"""

    @Test
    fun aQueuedAddIsSentOnceWithThePagesKeyAndBodyAndLeavesTheQueueWhenTheServerAnswers() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.calls.clear()
        val queued = h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0001")
        assertEquals(EnqueueResult.QUEUED, queued.result)
        assertTrue("queueing sends nothing", h.http.calls.isEmpty())
        assertEquals(listOf("add-key-0001"), h.repo.queuedShoppingAdds().map { it.idempotencyKey })
        assertTrue(
            "an add is neither a purchase nor a pending Today row",
            h.repo.queuedPurchases().isEmpty() && h.ready().pendingTaskIds.isEmpty(),
        )
        h.http.on { if (it.url.endsWith(addToList)) HttpResult(200, "{}") else null }
        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        val post = h.http.posts().single()
        assertEquals("add-key-0001", post.headers["Idempotency-Key"])
        assertEquals(addBody, String(post.body!!))
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
        assertEquals("Today keeps its row", listOf(TASK_A), h.ready().snapshot.tasks.map { it.id })
    }

    @Test
    fun anAddWithoutAnAnswerIsSentAgainWithTheSameKeyAndNeverTwiceOnceAnswered() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        // The tap is repeated by the page with the same key (its first call did not report back): still one add.
        h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0001")
        h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0001")
        h.http.on { if (it.url.endsWith(addToList)) CompanionException("network", beforeSend = false) else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        val entry = h.repo.queuedShoppingAdds().single()
        assertEquals("add-key-0001", entry.idempotencyKey)
        assertEquals(1, entry.attempts)
        h.http.calls.clear()
        h.http.on { if (it.url.endsWith(addToList)) HttpResult(200, "{}") else null }
        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertEquals("add-key-0001", h.http.posts().single().headers["Idempotency-Key"])
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
    }

    @Test
    fun aRefusedAddIsDroppedWithoutATodayNoticeAndDoesNotHoldUpTheQueue() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0001")
        h.repo.enqueuePurchase(h.repo.pairingGeneration(), ITEM, 4, true, "page-key-0001")
        h.http.on {
            when {
                it.url.endsWith(addToList) -> HttpResult(404, """{"code":"not_found"}""")
                it.url.endsWith(purchaseOfItem) -> HttpResult(200, "{}")
                else -> null
            }
        }
        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertTrue(h.repo.queuedShoppingAdds().isEmpty() && h.repo.queuedPurchases().isEmpty())
        assertNull(h.ready().snapshot.notice)
    }

    @Test
    fun withoutAPairingNoAddIsQueued() {
        val h = Harness(paired = false)
        assertEquals(EnqueueResult.NOT_PAIRED, h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0001").result)
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
    }

    @Test
    fun anAddThatFailedUnderAnEarlierPairingIsNotQueuedForTheNewOne() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        val began = h.repo.pairingGeneration()
        h.generation.advance()
        h.generation.advance()

        val late = h.repo.enqueueShoppingAdd(began, LIST, addBody, "add-key-0001")

        assertEquals(EnqueueResult.NOT_PAIRED, late.result)
        assertNull(late.entry)
        assertTrue(h.repo.queuedShoppingAdds().isEmpty())
        assertEquals(
            EnqueueResult.QUEUED,
            h.repo.enqueueShoppingAdd(h.repo.pairingGeneration(), LIST, addBody, "add-key-0002").result,
        )
    }

    private companion object {
        const val ITEM = "11111111-2222-4333-8444-555555555555"
    }

    // The widget's undo window (ua-4): the tap queues the completion held; Undo takes it back before anything is sent.

    private val window = TodayRepository.UNDO_WINDOW_MILLIS

    @Test
    fun aHeldCompletionShowsAsQueuedAndUndoableAndTheDrainSendsNothingInsideTheWindow() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B"))
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(200, "{}") else null }
        h.http.calls.clear()

        assertEquals(EnqueueResult.QUEUED, h.repo.enqueueCompletion(TASK_A, window))
        h.now += window - 1
        assertEquals("the app reads it as queued too", setOf(TASK_A), h.repo.queuedCompletions().map { it.subjectId }.toSet())
        assertEquals(setOf(TASK_A), h.ready().pendingTaskIds)
        assertEquals(setOf(TASK_A), h.ready().undoTaskIds)

        assertEquals("a sync that starts inside the window", SyncResult.UPDATED, h.repo.sync())
        assertTrue("sends nothing yet", h.http.posts().isEmpty())
        assertEquals("the row is still there", 2, h.ready().snapshot.tasks.size)
        assertEquals(setOf(TASK_A), h.ready().undoTaskIds)
    }

    @Test
    fun aHeldCompletionIsSentOnceTheWindowHasEndedWithItsOwnKeyAndVersion() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B"))
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(200, "{}") else null }
        h.repo.enqueueCompletion(TASK_A, window)
        h.now += window - 1
        h.repo.sync()
        h.now += 1
        assertTrue("window over: not undoable, still pending", h.ready().undoTaskIds.isEmpty() && h.ready().pendingTaskIds == setOf(TASK_A))

        h.serveToday(item(TASK_B, "B"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        val post = h.http.posts().single()
        assertEquals("widget-key-1", post.headers["Idempotency-Key"])
        assertEquals(3, JSONObject(String(post.body!!)).getInt("version"))
        assertEquals(listOf(TASK_B), h.ready().snapshot.tasks.map { it.id })
        assertTrue(h.outbox.pending().isEmpty())
    }

    @Test
    fun undoInsideTheWindowSendsNoRequestAndTheRowIsOpenAgain() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.http.calls.clear()
        h.repo.enqueueCompletion(TASK_A, window)
        h.now += 3_000

        assertTrue(h.repo.undoCompletion(TASK_A))
        assertNull(h.repo.nextSendAtMillis())
        assertTrue(h.ready().pendingTaskIds.isEmpty())
        assertEquals("A", h.ready().snapshot.tasks.single().title)

        h.now += 10_000
        h.http.on { if (it.url.contains(todayCall)) HttpResult(200, todayPage(item(TASK_A, "A", version = 3))) else null }
        h.repo.sync()
        assertTrue("nothing was ever sent for the undone tick", h.http.posts().isEmpty())
    }

    @Test
    fun undoAfterTheWindowFindsNothingToTakeBackAndTheCompletionStaysQueued() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A, window)
        h.now += window

        assertFalse(h.repo.undoCompletion(TASK_A))
        assertEquals(setOf(TASK_A), h.ready().pendingTaskIds)
    }

    @Test
    fun aTapAgainAfterAnUndoQueuesAFreshHeldCompletion() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A, window)
        h.repo.undoCompletion(TASK_A)
        assertEquals(EnqueueResult.QUEUED, h.repo.enqueueCompletion(TASK_A, window))
        assertEquals("a new key: the undone tick was never sent", "widget-key-2", h.outbox.pending().single().idempotencyKey)
        assertEquals(h.now + window, h.repo.nextSendAtMillis())
    }

    @Test
    fun aHeldCompletionDoesNotBlockOneThatIsDue() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3), item(TASK_B, "B", version = 1))
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(200, "{}") else null }
        h.repo.enqueueCompletion(TASK_A) // no hold
        h.repo.enqueueCompletion(TASK_B, window)
        h.serveToday(item(TASK_B, "B"))
        h.repo.sync()
        assertEquals(listOf(completeA), h.http.posts().map { it.url.removePrefix("https://sidekick.example") })
        assertEquals(setOf(TASK_B), h.ready().undoTaskIds)
    }

    @Test
    fun undoWithoutAPairingDoesNothing() {
        val h = Harness(paired = false)
        assertFalse(h.repo.undoCompletion(TASK_A))
        assertNull(h.repo.nextSendAtMillis())
    }

    // Offline feedback (ua-12): a read that does not get through marks the cached Today, a read that does clears it.

    @Test
    fun aReadThatDoesNotGetThroughMarksTheCachedTodayOfflineAndKeepsItsSyncTime() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        val syncedAt = h.ready().snapshot.syncedAtMillis
        assertFalse(h.ready().snapshot.offline)

        h.now += 600_000
        h.http.on { if (it.url.contains(todayCall)) CompanionException("offline") else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertTrue(h.ready().snapshot.offline)
        assertEquals("the time is the last one that got through", syncedAt, h.ready().snapshot.syncedAtMillis)
        assertEquals("A", h.ready().snapshot.tasks.single().title)

        h.serveToday(item(TASK_A, "A"))
        assertEquals(SyncResult.UPDATED, h.repo.sync())
        assertFalse(h.ready().snapshot.offline)
    }

    @Test
    fun aFailedReadKeepsTheNoticeOfARefusedCompletionAndMarksOffline() {
        val h = Harness()
        h.readToday(item(TASK_A, "A", version = 3))
        h.repo.enqueueCompletion(TASK_A)
        h.http.on { if (it.url.endsWith(completeA)) HttpResult(409, "{}") else null }
        h.http.on { if (it.url.contains(todayCall)) HttpResult(503, "{}") else null }
        assertEquals(SyncResult.RETRY, h.repo.sync())
        assertTrue(h.ready().snapshot.offline)
        assertEquals(TodayNotice.CONFLICT, h.ready().snapshot.notice)
    }

    @Test
    fun aRefreshWithNoNetworkMarksOfflineWithoutAnyRequestAndTheNextReadClearsIt() {
        val h = Harness()
        h.readToday(item(TASK_A, "A"))
        h.http.calls.clear()

        h.repo.markOffline()
        assertTrue(h.http.calls.isEmpty())
        assertTrue(h.ready().snapshot.offline)

        h.repo.sync()
        assertFalse(h.ready().snapshot.offline)
    }

    @Test
    fun markingOfflineWithoutAPairingOrACacheChangesNothing() {
        val h = Harness(paired = false)
        h.repo.markOffline()
        assertNull(h.cacheText.text)
        val paired = Harness()
        paired.repo.markOffline()
        assertNull("nothing cached, nothing to mark", paired.cacheText.text)
    }
}
