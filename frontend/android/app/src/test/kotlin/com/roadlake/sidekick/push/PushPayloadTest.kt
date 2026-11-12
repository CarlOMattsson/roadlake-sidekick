package com.roadlake.sidekick.push

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PushPayloadTest {
    private fun parse(text: String) = PushPayload.parse(text.toByteArray(Charsets.UTF_8))

    @Test
    fun theTwoKnownKindsAreRecognised() {
        assertEquals(PushKind.WAKE, parse("""{"k":"w"}"""))
        assertEquals(PushKind.REMINDERS, parse("""{"k":"r"}"""))
    }

    @Test
    fun anUnknownKindOrShapeIsIgnored() {
        assertNull(parse("""{"k":"x"}"""))
        assertNull(parse("""{"k":1}"""))
        assertNull(parse("""{"k":null}"""))
        assertNull(parse("""{"kind":"w"}"""))
        assertNull(parse("{}"))
        assertNull(parse("""["w"]"""))
        assertNull(parse(""""w""""))
        assertNull(parse("not json"))
        assertNull(parse(""))
        assertNull(PushPayload.parse(null))
        assertNull(PushPayload.parse(ByteArray(0)))
        assertNull(PushPayload.parse(byteArrayOf(0x7b, 0x00, 0xff.toByte())))
    }

    @Test
    fun anOversizedMessageIsNotEvenParsed() {
        assertNull(parse("""{"k":"w","pad":"${"x".repeat(2000)}"}"""))
    }

    @Test
    fun theReceiverDoesWhatTheKindSaysAndNothingForTheRest() {
        var wakes = 0
        var reminders = 0
        val receiver = PushReceiver(onWake = { wakes++ }, onReminders = { reminders++ })

        receiver.handle("""{"k":"w"}""".toByteArray())
        assertEquals(1 to 0, wakes to reminders)
        receiver.handle("""{"k":"r"}""".toByteArray())
        assertEquals(1 to 1, wakes to reminders)
        receiver.handle("""{"k":"zzz"}""".toByteArray())
        receiver.handle("garbage".toByteArray())
        receiver.handle(null)
        assertEquals(1 to 1, wakes to reminders)
    }
}
