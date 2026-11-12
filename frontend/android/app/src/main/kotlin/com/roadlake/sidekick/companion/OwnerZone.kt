package com.roadlake.sidekick.companion

import java.util.TimeZone

/**
 * The owner's time zone, the one the server counts "today" in (`SIDEKICK_OWNER_TIMEZONE`). Every native part that shows
 * or plans by the owner's calendar (reminder times, the page's Today and dates) uses it, never the phone's own zone: an
 * owner in New York and a phone on a Stockholm roaming network must still agree on which day it is.
 */
object OwnerZone {
    /** [value] as a zone id the platform knows, or null. `TimeZone.getTimeZone` would turn an unknown id into GMT without a word. */
    fun idOf(value: Any?): String? {
        val id = (value as? String)?.trim()?.takeIf { it.isNotEmpty() && it.length <= MAX_ID_CHARS } ?: return null
        return id.takeIf { it in TimeZone.getAvailableIDs() }
    }

    /** The zone for [id] (as kept by [idOf]), or [fallback] when the server never said one. */
    fun zoneOf(id: String?, fallback: TimeZone): TimeZone = idOf(id)?.let(TimeZone::getTimeZone) ?: fallback

    private const val MAX_ID_CHARS = 64
}
