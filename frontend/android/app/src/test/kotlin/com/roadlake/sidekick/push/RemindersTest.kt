package com.roadlake.sidekick.push

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.HttpResult
import com.roadlake.sidekick.companion.OwnerZone
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.today.MemoryPairingStore
import com.roadlake.sidekick.today.ScriptedHttp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

private const val TASK = "3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e"

private class FakeTexts : ReminderTexts {
    override fun summary(today: Int, overdue: Int) = "$today idag · $overdue försenade"

    override fun dueAt(clock: String) = "förfaller $clock"

    override fun test() = "Testnotis från Sidekick"

    override fun publicTitle(count: Int) = "Sidekick · $count påminnelser"
}

private fun body(items: String = "", summary: String = "null", zone: String? = null) =
    """{${zone?.let { "\"timezone\":\"$it\"," } ?: ""}"items":[$items],"summary":$summary}"""

private class MemoryUnacked(var ids: List<String> = emptyList()) : UnackedStore {
    override fun load() = ids

    override fun save(ids: List<String>) {
        this.ids = ids
    }
}

private fun due(id: String, title: String, task: String? = TASK, dueAt: String? = "2026-11-08T13:30:00Z") =
    """{"id":"$id","kind":"due","title":${org.json.JSONObject.quote(title)},"task_id":${task?.let {
        "\"$it\""
    }},"due_at":${dueAt?.let { "\"$it\"" }}}"""

class RemindersCodecTest {
    @Test
    fun readsTheShapeOfThePendingAnswer() {
        val pending = RemindersCodec.parse(
            body(
                items = due("r1", "Ring banken") + "," + """{"id":"t1","kind":"test","title":"Testnotis","task_id":null,"due_at":null}""",
                summary = """{"id":"s1","today":3,"overdue":2}""",
            ),
        )!!
        assertEquals(listOf("s1", "r1", "t1"), pending.ids)
        assertEquals(3, pending.summary!!.today)
        assertEquals(2, pending.summary!!.overdue)
        assertEquals(ReminderKind.DUE, pending.items[0].kind)
        assertEquals(TASK, pending.items[0].taskId)
        assertEquals(ReminderKind.TEST, pending.items[1].kind)
        assertNull(pending.items[1].taskId)
        assertNull(pending.items[1].dueAtMillis)
    }

    @Test
    fun anUnknownKindIsIgnoredAndNotAcknowledged() {
        val unknown = """{"id":"x1","kind":"digest","title":"?","task_id":null,"due_at":null}"""
        val pending = RemindersCodec.parse(body(items = unknown + "," + due("r1", "A")))!!
        assertEquals(listOf("r1"), pending.ids)
    }

    @Test
    fun aNullSummaryAndEmptyItemsGiveNothing() {
        val pending = RemindersCodec.parse(body())!!
        assertNull(pending.summary)
        assertTrue(pending.ids.isEmpty())
    }

    @Test
    fun brokenInputIsNotRemindersAtAll() {
        assertNull(RemindersCodec.parse("not json"))
        assertNull(RemindersCodec.parse(""))
    }

    @Test
    fun aDuplicateIdAppearsOnce() {
        val pending = RemindersCodec.parse(body(items = due("r1", "A") + "," + due("r1", "A again")))!!
        assertEquals(listOf("r1"), pending.ids)
    }

    @Test
    fun aTaskIdThatIsNotAnIdOpensTodayInstead() {
        val pending = RemindersCodec.parse(body(items = due("r1", "A", task = "x&view=evil")))!!
        assertNull(pending.items[0].taskId)
    }

    @Test
    fun aDueReminderWithoutATitleOrAnIdIsSkipped() {
        val noTitle = """{"id":"r2","kind":"due","title":"  ","task_id":null,"due_at":null}"""
        val noId = """{"kind":"due","title":"A","task_id":null,"due_at":null}"""
        assertTrue(RemindersCodec.parse(body(items = "$noTitle,$noId"))!!.ids.isEmpty())
    }

    @Test
    fun isoInstantsAreReadWithOffsetsAndFractions() {
        val utc = IsoInstant.parse("2026-11-08T13:30:00Z")!!
        assertEquals(utc, IsoInstant.parse("2026-11-08T14:30:00.250+01:00"))
        assertEquals(utc, IsoInstant.parse("2026-11-08T14:30:00+0100"))
        assertNull(IsoInstant.parse("2026-13-08T13:30:00Z"))
        assertNull(IsoInstant.parse("tomorrow"))
    }

    @Test
    fun theZoneOfTheAnswerIsReadAndAMissingOrUnknownOneIsNull() {
        assertEquals("Europe/Stockholm", RemindersCodec.parse(body(zone = "Europe/Stockholm"))!!.zone!!.id)
        assertNull(RemindersCodec.parse(body())!!.zone)
        assertNull(RemindersCodec.parse(body(zone = "Mars/Olympus_Mons"))!!.zone)
        assertNull(RemindersCodec.parse("""{"timezone":42,"items":[],"summary":null}""")!!.zone)
    }

    @Test
    fun theClockIsInTheOwnersZone() {
        val millis = IsoInstant.parse("2026-11-08T13:30:00Z")!!
        assertEquals("14:30", IsoInstant.clock(millis, TimeZone.getTimeZone("Europe/Stockholm")))
        assertEquals("13:30", IsoInstant.clock(millis, TimeZone.getTimeZone("UTC")))
    }
}

class ReminderNoticesTest {
    private val zone = TimeZone.getTimeZone("Europe/Stockholm")

    private fun plan(items: String, summary: String = "null") =
        ReminderNotices.plan(RemindersCodec.parse(body(items, summary))!!, FakeTexts(), zone)

    @Test
    fun aDueReminderShowsTheTitleTheTimeAndOpensTheTask() {
        val notice = plan(due("r1", "Ring banken")).single()
        assertEquals("Ring banken", notice.title)
        assertEquals("förfaller 14:30", notice.text)
        assertEquals("sidekick://open?view=task&id=$TASK", notice.deepLink)
    }

    @Test
    fun theLockScreenVersionNamesOnlyTheCount() {
        val notices = plan(due("r1", "Hemligt") + "," + due("r2", "Också hemligt"), """{"id":"s1","today":2,"overdue":0}""")
        assertEquals(3, notices.size)
        for (notice in notices) {
            assertEquals("Sidekick · 3 påminnelser", notice.publicTitle)
            assertFalse(notice.publicTitle.contains("hemligt", ignoreCase = true))
        }
    }

    @Test
    fun theSummaryOpensToday() {
        val notice = plan("", """{"id":"s1","today":3,"overdue":2}""").single()
        assertEquals("3 idag · 2 försenade", notice.title)
        assertEquals("sidekick://open?view=today", notice.deepLink)
    }

    @Test
    fun aTestReminderSaysSo() {
        val notice = plan("""{"id":"t1","kind":"test","title":"","task_id":null,"due_at":null}""").single()
        assertEquals("Testnotis från Sidekick", notice.title)
        assertEquals(ReminderTarget.Today, notice.target)
    }

    @Test
    fun aDueReminderWithoutATimeHasNoText() {
        assertNull(plan(due("r1", "A", dueAt = null)).single().text)
    }

    @Test
    fun theSameReminderIdIsTheSameNotificationId() {
        val first = plan(due("r1", "A")).single()
        val again = plan(due("r1", "A")).single()
        val other = plan(due("r2", "A")).single()
        assertEquals(first.notificationId, again.notificationId)
        assertTrue(first.notificationId != other.notificationId)
        assertTrue(first.notificationId > ReminderNotice.GROUP_ID)
    }
}

class ReminderFlowTest {
    private class Api(var pendingAnswer: Any, var ackAnswer: Any = CompanionResponse(204, "")) : RemindersApi {
        val acks = mutableListOf<List<String>>()
        var pendingCalls = 0

        /** Runs while the fetch is in flight, i.e. before its answer is handled. */
        var duringPending: () -> Unit = {}

        override fun pending(): CompanionResponse {
            pendingCalls++
            duringPending()
            return result(pendingAnswer)
        }

        override fun ack(ids: List<String>): CompanionResponse {
            acks += ids
            return result(ackAnswer)
        }

        private fun result(answer: Any): CompanionResponse = if (answer is CompanionException) throw answer else answer as CompanionResponse
    }

    /** Shows by notification id, as the system does: a second show of the same id replaces the first. */
    private class Screen : ReminderDisplay {
        val shown = linkedMapOf<Int, ReminderNotice>()
        var calls = 0

        override fun show(notices: List<ReminderNotice>) {
            calls++
            notices.forEach { shown[it.notificationId] = it }
        }

        override fun cancelAll() {
            shown.clear()
        }
    }

    private val screen = Screen()
    private var permitted = true

    private val unacked = MemoryUnacked()
    private val generation = PairingGeneration()

    private fun flow(api: Api) =
        ReminderFlow(api, { permitted }, screen, { FakeTexts() }, { TimeZone.getTimeZone("UTC") }, unacked, generation)

    private fun ok(items: String, summary: String = "null", zone: String? = null) = CompanionResponse(200, body(items, summary, zone))

    @Test
    fun showsThenAcknowledgesEverythingIncludingTheSummary() {
        val api = Api(ok(due("r1", "A") + "," + due("r2", "B"), """{"id":"s1","today":2,"overdue":0}"""))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(3, screen.shown.size)
        assertEquals(listOf(listOf("s1", "r1", "r2")), api.acks)
    }

    @Test
    fun withoutPermissionNothingIsShownButTheAcknowledgementIsSent() {
        permitted = false
        val api = Api(ok(due("r1", "A")))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(0, screen.calls)
        assertEquals(listOf(listOf("r1")), api.acks)
    }

    @Test
    fun aFailedAcknowledgementIsNotShownAgainButAcknowledgedAgain() {
        val api = Api(ok(due("r1", "A")), ackAnswer = CompanionException("network"))
        assertEquals(SyncOutcome.RETRY, flow(api).run())
        assertEquals(listOf("r1"), unacked.ids)
        api.pendingAnswer = ok(due("r1", "A") + "," + due("r2", "B"))
        api.ackAnswer = CompanionResponse(204, "")
        assertEquals(SyncOutcome.DONE, flow(api).run())
        // r1 was shown once; the second run showed only r2, and both were acknowledged.
        assertEquals(2, screen.calls)
        assertEquals(2, screen.shown.size)
        assertEquals(listOf(listOf("r1"), listOf("r1", "r2")), api.acks)
    }

    @Test
    fun aSuccessfulAcknowledgementClearsTheList() {
        unacked.ids = listOf("old")
        val api = Api(ok(due("r1", "A")))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(listOf(listOf("old", "r1")), api.acks)
        assertTrue(unacked.ids.isEmpty())
    }

    @Test
    fun leftoverIdsAreAcknowledgedEvenWhenNothingIsPendingNow() {
        unacked.ids = listOf("old")
        val api = Api(ok(""))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(0, screen.calls)
        assertEquals(listOf(listOf("old")), api.acks)
        assertTrue(unacked.ids.isEmpty())
    }

    @Test
    fun theListKeepsAtMostFiftyIdsOldestOut() {
        val api = Api(ok((1..60).joinToString(",") { due("n$it", "A$it") }), ackAnswer = CompanionResponse(503, ""))
        assertEquals(SyncOutcome.RETRY, flow(api).run())
        assertEquals(50, unacked.ids.size)
        assertEquals("n11", unacked.ids.first())
        assertEquals("n60", unacked.ids.last())
    }

    @Test
    fun theZoneOfTheAnswerFormatsTheClockAndTheDeviceZoneIsTheFallback() {
        // 13:30 UTC is 14:30 in Stockholm in November; the device zone here is UTC.
        fun text(zone: String?): String? {
            val shown = Screen()
            ReminderFlow(Api(ok(due("r1", "A"), zone = zone)), {
                true
            }, shown, { FakeTexts() }, { TimeZone.getTimeZone("UTC") }, MemoryUnacked()).run()
            return shown.shown.values.single().text
        }
        assertEquals("förfaller 14:30", text("Europe/Stockholm"))
        assertEquals("förfaller 13:30", text(null))
        assertEquals("förfaller 13:30", text("Nowhere/Land"))
    }

    @Test
    fun theStoredOwnerZoneBeatsTheDeviceZoneWhenTheAnswerHasNone() {
        // The phone is on UTC, the owner in Tokyo (UTC+9): 13:30 UTC is 22:30 there, and a phone zone must not decide.
        fun text(owner: String?, answerZone: String?): String? {
            val shown = Screen()
            val deviceZone = { OwnerZone.zoneOf(owner, TimeZone.getTimeZone("UTC")) }
            ReminderFlow(Api(ok(due("r1", "A"), zone = answerZone)), { true }, shown, { FakeTexts() }, deviceZone, MemoryUnacked()).run()
            return shown.shown.values.single().text
        }
        assertEquals("förfaller 22:30", text("Asia/Tokyo", null))
        assertEquals("förfaller 13:30", text(null, null))
        // The zone in the answer is the newest word of the server and wins over the stored one.
        assertEquals("förfaller 14:30", text("Asia/Tokyo", "Europe/Stockholm"))
    }

    @Test
    fun aServerErrorOnAcknowledgeIsRetried() {
        val api = Api(ok(due("r1", "A")), ackAnswer = CompanionResponse(503, ""))
        assertEquals(SyncOutcome.RETRY, flow(api).run())
    }

    @Test
    fun noAnswerOrAServerErrorOnFetchIsRetriedAndNothingIsAcknowledged() {
        val none = Api(CompanionException("network"))
        assertEquals(SyncOutcome.RETRY, flow(none).run())
        val broken = Api(CompanionResponse(502, ""))
        assertEquals(SyncOutcome.RETRY, flow(broken).run())
        assertTrue(none.acks.isEmpty() && broken.acks.isEmpty())
    }

    @Test
    fun noPairingOrARefusalEndsTheWork() {
        assertEquals(SyncOutcome.DONE, flow(Api(CompanionException("not_paired"))).run())
        assertEquals(SyncOutcome.DONE, flow(Api(CompanionResponse(401, "{}"))).run())
        assertEquals(0, screen.calls)
    }

    @Test
    fun nothingPendingMeansNothingToShowOrAcknowledge() {
        val api = Api(ok(""))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(0, screen.calls)
        assertTrue(api.acks.isEmpty())
    }

    @Test
    fun anUnreadableAnswerChangesNothing() {
        val api = Api(CompanionResponse(200, "<html>"))
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertTrue(api.acks.isEmpty())
    }

    @Test
    fun remindersFetchedForAPairingThatEndedMeanwhileAreNotShownRememberedOrAcknowledged() {
        val api = Api(ok(due("r1", "A")))
        api.duringPending = { generation.advance() }
        assertEquals(SyncOutcome.DONE, flow(api).run())
        assertEquals(0, screen.calls)
        assertTrue(api.acks.isEmpty())
        assertTrue(unacked.ids.isEmpty())
    }

    @Test
    fun theEndOfAPairingTakesDownTheNotificationsAndForgetsTheUnacknowledgedIds() {
        val api = Api(ok(due("r1", "A")), ackAnswer = CompanionResponse(500, ""))
        assertEquals(SyncOutcome.RETRY, flow(api).run())
        assertEquals(listOf("r1"), unacked.ids)
        assertEquals(1, screen.shown.size)

        flow(api).clearLocal()

        assertTrue(unacked.ids.isEmpty())
        assertTrue(screen.shown.isEmpty())
    }

    @Test
    fun aNotificationThatCannotBeTakenDownDoesNotStopTheCleanUp() {
        unacked.ids = listOf("old")
        val stuck = ReminderFlow(
            Api(ok("")),
            { true },
            object : ReminderDisplay {
                override fun show(notices: List<ReminderNotice>) = Unit

                override fun cancelAll(): Unit = throw SecurityException("no access")
            },
            { FakeTexts() },
            { TimeZone.getDefault() },
            unacked,
        )
        stuck.clearLocal()
        assertTrue(unacked.ids.isEmpty())
    }

    @Test
    fun aNotificationThatCannotBeDrawnStillAcknowledges() {
        val api = Api(ok(due("r1", "A")))
        val failing =
            ReminderFlow(api, {
                true
            }, { throw SecurityException("withdrawn") }, { FakeTexts() }, { TimeZone.getDefault() }, MemoryUnacked())
        assertEquals(SyncOutcome.DONE, failing.run())
        assertEquals(listOf(listOf("r1")), api.acks)
    }
}

class ReminderRoutesTest {
    @Test
    fun theClientCallsTheTwoRoutesWithTheDeviceCredential() {
        val http = ScriptedHttp()
        http.on { if (it.url.endsWith("/reminders/pending")) HttpResult(200, "{}") else HttpResult(204, "") }
        val client = CompanionClient(MemoryPairingStore(), http, allowLocalCleartext = false)

        client.pendingReminders()
        client.ackReminders(listOf("s1", "r1"))

        val (get, post) = http.calls
        assertEquals("GET", get.method)
        assertEquals("https://sidekick.example/companion/v1/reminders/pending", get.url)
        assertTrue(get.headers.getValue("Authorization").startsWith("Bearer "))
        assertEquals("POST", post.method)
        assertEquals("https://sidekick.example/companion/v1/reminders/ack", post.url)
        assertEquals("""{"ids":["s1","r1"]}""", String(post.body!!, Charsets.UTF_8))
    }

    @Test
    fun withoutAPairingNothingIsSent() {
        val http = ScriptedHttp()
        val client = CompanionClient(MemoryPairingStore(null), http, allowLocalCleartext = false)
        val error = org.junit.Assert.assertThrows(CompanionException::class.java) { client.pendingReminders() }
        assertEquals("not_paired", error.code)
        assertTrue(http.calls.isEmpty())
    }
}

class ReminderGroupingTest {
    private val group = ReminderNotice.GROUP_ID

    @Test
    fun threeSeparateBatchesCountThree() {
        var active = emptyList<Int>()
        val counts = listOf("a", "b", "c").map { id ->
            active = active + ReminderNotice.notificationIdOf(id)
            ReminderGrouping.summaryCount(active, group)
        }
        assertEquals(listOf(1, 2, 3), counts)
    }

    @Test
    fun theSummaryIdIsNotCounted() {
        val ids = listOf(group, ReminderNotice.notificationIdOf("a"), ReminderNotice.notificationIdOf("b"))
        assertEquals(2, ReminderGrouping.summaryCount(ids, group))
    }

    @Test
    fun theSameIdCountsOnce() {
        val a = ReminderNotice.notificationIdOf("a")
        assertEquals(1, ReminderGrouping.summaryCount(listOf(a, a, a), group))
    }

    @Test
    fun aLoneNotificationNeedsNoGroup() {
        val count = ReminderGrouping.summaryCount(listOf(group, ReminderNotice.notificationIdOf("a")), group)
        assertEquals(1, count)
        assertFalse(count >= ReminderGrouping.MIN_GROUPED)
        assertEquals(0, ReminderGrouping.summaryCount(listOf(group), group))
    }
}

class ReminderSummaryTextTest {
    private fun compose(today: Int, overdue: Int) = ReminderSummaryText.compose(
        today,
        overdue,
        todayText = { "$it idag" },
        overdueText = { if (it == 1) "$it försenad" else "$it försenade" },
        join = { a, b -> "$a · $b" },
    )

    @Test
    fun bothPartsAreJoinedWhenNeitherIsZero() {
        assertEquals("3 idag · 1 försenad", compose(3, 1))
        assertEquals("1 idag · 2 försenade", compose(1, 2))
    }

    @Test
    fun aZeroPartIsLeftOut() {
        assertEquals("3 idag", compose(3, 0))
        assertEquals("2 försenade", compose(0, 2))
    }

    @Test
    fun theLineIsNeverEmpty() {
        assertEquals("0 idag", compose(0, 0))
    }
}
