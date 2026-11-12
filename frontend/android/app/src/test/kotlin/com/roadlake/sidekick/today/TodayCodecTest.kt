package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class TodayCodecTest {
    private fun uuid(n: Int) = UUID(0x1000L, n.toLong()).toString()

    @Test
    fun takesTheServersRowsAsTheyComeAndKeepsOnlyTheFieldsTheWidgetNeeds() {
        val body = todayPage(
            item(TASK_A, "Överdue", version = 4, group = "overdue"),
            item(TASK_B, "Idag", version = 2, group = "today"),
            day = "2026-11-09",
        )
        val snapshot = TodayCodec.fromToday(body, "sidekick.example", 5L)
        // The server's order is kept: overdue first, then today's own.
        assertEquals(listOf(TASK_A, TASK_B), snapshot.tasks.map { it.id })
        assertEquals(listOf(true, false), snapshot.tasks.map { it.overdue })
        assertEquals(4, snapshot.tasks[0].version)
        assertEquals(2, snapshot.total)
        assertEquals("2026-11-09", snapshot.day)
        val stored = TodayCodec.encode(snapshot)
        assertFalse(stored.contains("SECRET NOTE"))
        assertFalse(stored.contains("description"))
        assertFalse(stored.contains("project"))
        assertFalse(stored.contains("due_at"))
    }

    @Test
    fun theServersTotalSurvivesWhenOnlyTwentyRowsAreKeptAndTitlesAreClipped() {
        val items = (1..30).map { item(uuid(it), "T".repeat(300)) }.toTypedArray()
        val snapshot = TodayCodec.fromToday(todayPage(*items, total = 45), "h", 1L)
        assertEquals(TodaySnapshot.MAX_TASKS, snapshot.tasks.size)
        assertTrue(snapshot.tasks.all { it.title.length == TodaySnapshot.MAX_TITLE_CHARS })
        assertEquals(45, snapshot.total)
        val back = TodayCodec.decode(TodayCodec.encode(snapshot))!!
        assertEquals(TodaySnapshot.MAX_TASKS, back.tasks.size)
        assertEquals(45, back.total)
        assertEquals("2026-11-09", back.day)
    }

    @Test
    fun removingARowLowersTheTotalButNeverBelowTheRowsKept() {
        val snapshot = TodaySnapshot("h", 1L, listOf(TodayTask(TASK_A, "A", 1, false), TodayTask(TASK_B, "B", 1, false)), 5)
        assertEquals(4, snapshot.without(TASK_A).total)
        assertEquals(5, snapshot.without(uuid(9)).total)
        assertEquals(1, TodaySnapshot("h", 1L, snapshot.tasks, 1).without(TASK_A).total)
    }

    @Test
    fun skipsRowsWithoutAWellFormedIdTitleOrVersion() {
        val body = todayPage(
            item("not-a-uuid", "A"),
            item(TASK_A, "   "),
            """{"id":"$TASK_B","title":"Utan version","status":"todo","group":"today"}""",
        )
        assertTrue(TodayCodec.fromToday(body, "h", 1L).tasks.isEmpty())
    }

    @Test
    fun aBodyThatIsNotATodayPageIsABadResponse() {
        for (body in listOf("[]", "{}", """{"items":[],"day":"2026-11-09"}""", """{"items":[],"total":0}""")) {
            assertEquals("bad_response", assertThrows(CompanionException::class.java) { TodayCodec.fromToday(body, "h", 1L) }.code)
        }
    }

    @Test
    fun theOfflineMarkSurvivesTheCacheAndEveryCopyOfTheSnapshot() {
        val snapshot = TodaySnapshot("h", 9L, listOf(TodayTask(TASK_A, "A", 1, false)), 1)
        assertFalse("a read that got through is not offline", snapshot.offline)
        assertFalse(TodayCodec.decode(TodayCodec.encode(snapshot))!!.offline)

        val offline = snapshot.withOffline(true)
        assertTrue(TodayCodec.decode(TodayCodec.encode(offline))!!.offline)
        assertTrue(offline.without(TASK_A).offline)
        assertTrue(offline.withNotice(TodayNotice.REJECTED).offline)
        assertFalse(offline.withOffline(false).offline)
    }

    @Test
    fun aCacheWrittenBeforeTheOfflineMarkOrWithTheOldLicenseFieldStillReads() {
        val old = """{"format":2,"partition":"h","syncedAt":9,"total":0,"day":"d","notice":null,"license":"unlicensed","tasks":[]}"""
        assertFalse(TodayCodec.decode(old)!!.offline)
    }

    @Test
    fun decodeRefusesUnknownFormatsAndGarbage() {
        assertNull(TodayCodec.decode(null))
        assertNull(TodayCodec.decode("not json"))
        assertNull(TodayCodec.decode("""{"format":1,"partition":"h","syncedAt":1,"truncated":false,"tasks":[]}"""))
        val ok = TodaySnapshot("h", 9L, listOf(TodayTask(TASK_A, "A", 3, true)), 4, TodayNotice.CONFLICT)
        val back = TodayCodec.decode(TodayCodec.encode(ok))
        assertNotNull(back)
        assertEquals(TodayNotice.CONFLICT, back!!.notice)
        assertEquals(3, back.tasks.single().version)
        assertEquals(4, back.total)
    }
}
