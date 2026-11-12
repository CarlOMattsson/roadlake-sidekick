package com.roadlake.sidekick.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

class OwnerZoneTest {
    private val phone = TimeZone.getTimeZone("Europe/Stockholm")

    /** The calendar day of [millis] in [zone], the way the native parts count "today". */
    private fun day(millis: Long, zone: TimeZone): String =
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply { timeZone = zone }.format(millis)

    @Test
    fun onlyAZoneIdThePlatformKnowsIsKept() {
        assertEquals("America/New_York", OwnerZone.idOf(" America/New_York "))
        assertNull(OwnerZone.idOf("Mars/Olympus_Mons"))
        assertNull(OwnerZone.idOf(""))
        assertNull(OwnerZone.idOf(null))
        assertNull(OwnerZone.idOf(7))
        assertNull(OwnerZone.idOf("A".repeat(65)))
    }

    @Test
    fun theOwnersZoneWinsOverThePhonesAndTheFallbackIsTheOnlyUseOfThePhonesZone() {
        assertEquals("America/New_York", OwnerZone.zoneOf("America/New_York", phone).id)
        assertEquals("Europe/Stockholm", OwnerZone.zoneOf(null, phone).id)
        assertEquals("Europe/Stockholm", OwnerZone.zoneOf("Nowhere/Land", phone).id)
    }

    @Test
    fun theSameInstantIsDifferentCalendarDaysInTheOwnersAndThePhonesZone() {
        // 2026-11-12T04:30Z: already the 12th in Stockholm (05:30) but still the 11th in New York (23:30).
        val instant = 1_794_457_800_000L
        assertEquals("2026-11-12", day(instant, phone))
        assertEquals("2026-11-11", day(instant, OwnerZone.zoneOf("America/New_York", phone)))
        // And the other way round: an owner ahead of the phone.
        val evening = 1_794_506_400_000L // 2026-11-12T18:00Z
        assertEquals("2026-11-12", day(evening, phone))
        assertEquals("2026-11-13", day(evening, OwnerZone.zoneOf("Pacific/Auckland", phone)))
    }
}
