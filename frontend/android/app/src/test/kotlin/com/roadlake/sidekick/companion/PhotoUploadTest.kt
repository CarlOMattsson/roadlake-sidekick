package com.roadlake.sidekick.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

private class PhotoStore(var pairing: Pairing?) : PairingStore {
    override fun load(): Pairing? = pairing

    override fun save(pairing: Pairing) {
        this.pairing = pairing
    }

    override fun clear() {
        pairing = null
    }
}

private class PhotoHttp(private val answer: (HttpCall) -> HttpResult) : HttpTransport {
    val calls = mutableListOf<HttpCall>()

    override fun execute(call: HttpCall): HttpResult {
        calls += call
        return answer(call)
    }
}

class PhotoUploadTest {
    private val origin = "https://sidekick.example"
    private val token = "rsc_abcdefghijklmnopqrstuvwxyz0123456789"
    private val photo = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 3, 0xFF.toByte(), 0xD9.toByte())
    private val thumb = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 9, 0xFF.toByte(), 0xD9.toByte())

    private fun code(block: () -> Unit): String = assertThrows(CompanionException::class.java, block).code

    private fun text(bytes: ByteArray) = String(bytes, Charsets.ISO_8859_1)

    @Test
    fun theFormHoldsTheDayTheCaptionAndBothFilesAsTheRouteTakesThem() {
        val form = PhotoUpload.form("2026-11-22", photo, thumb, "A bridge at dusk", boundary = "BOUNDARY")
        assertEquals("multipart/form-data; boundary=BOUNDARY", form.contentType)
        val body = text(form.body)
        assertTrue(body.startsWith("--BOUNDARY\r\nContent-Disposition: form-data; name=\"journal_date\"\r\n\r\n2026-11-22\r\n"))
        assertTrue(body.contains("name=\"alt_text\"\r\n\r\nA bridge at dusk\r\n"))
        assertTrue(body.contains("name=\"photo\"; filename=\"photo.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"))
        assertTrue(body.contains("name=\"thumbnail\"; filename=\"thumbnail.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"))
        assertTrue(body.endsWith("\r\n--BOUNDARY--\r\n"))
        // The bytes of both files go in as they are.
        assertTrue(body.contains(text(photo) + "\r\n--BOUNDARY"))
        assertTrue(body.contains(text(thumb) + "\r\n--BOUNDARY--"))
    }

    @Test
    fun aCaptionIsSentAsUtf8AndLeftOutWhenThereIsNone() {
        val withCaption = PhotoUpload.form("2026-11-22", photo, thumb, "Å ö ✓", boundary = "B")
        assertTrue(withCaption.body.toString(Charsets.UTF_8).contains("\r\n\r\nÅ ö ✓\r\n"))
        for (none in listOf(null, "")) {
            val form = PhotoUpload.form("2026-11-22", photo, thumb, none, boundary = "B")
            assertFalse(text(form.body).contains("alt_text"))
        }
    }

    @Test
    fun everyFormGetsItsOwnBoundary() {
        val first = PhotoUpload.form("2026-11-22", photo, thumb, null)
        val second = PhotoUpload.form("2026-11-22", photo, thumb, null)
        assertNotEquals(first.contentType, second.contentType)
    }

    @Test
    fun whatIsOutsideTheServersLimitsIsRefusedBeforeAnythingIsBuilt() {
        assertEquals("bad_request", code { PhotoUpload.form(null, photo, thumb, null) })
        assertEquals("bad_request", code { PhotoUpload.form("yesterday", photo, thumb, null) })
        assertEquals("bad_request", code { PhotoUpload.form("2026-11-22", null, thumb, null) })
        assertEquals("bad_request", code { PhotoUpload.form("2026-11-22", ByteArray(0), thumb, null) })
        assertEquals(
            "bad_request",
            code { PhotoUpload.form("2026-11-22", ByteArray(PhotoUpload.MAX_PHOTO_BYTES + 1), thumb, null) },
        )
        assertEquals("bad_request", code { PhotoUpload.form("2026-11-22", photo, null, null) })
        assertEquals(
            "bad_request",
            code { PhotoUpload.form("2026-11-22", photo, ByteArray(PhotoUpload.MAX_THUMBNAIL_BYTES + 1), null) },
        )
        assertEquals(
            "bad_request",
            code { PhotoUpload.form("2026-11-22", photo, thumb, "x".repeat(PhotoUpload.MAX_CAPTION_CHARS + 1)) },
        )
        // The limits themselves are allowed.
        PhotoUpload.form("2026-11-22", ByteArray(PhotoUpload.MAX_PHOTO_BYTES) { 1 }, thumb, "x".repeat(500))
    }

    @Test
    fun theClientPostsTheFormToTheRouteWithTheTokenAndTheKey() {
        val http = PhotoHttp { HttpResult(200, """{"photo":{"id":"x"}}""") }
        val client = CompanionClient(PhotoStore(Pairing(origin, token, "Samsung")), http, false)
        val answer = client.uploadJournalPhoto("2026-11-22", photo, thumb, "Caption", "photo-key-0001")

        assertEquals(200, answer.status)
        val call = http.calls.single()
        assertEquals("POST", call.method)
        assertEquals("$origin/companion/v1/journal/photos", call.url)
        assertEquals("Bearer $token", call.headers["Authorization"])
        assertEquals("photo-key-0001", call.headers["Idempotency-Key"])
        val type = call.headers.getValue("Content-Type")
        assertTrue(type.startsWith("multipart/form-data; boundary="))
        val boundary = type.substringAfter("boundary=")
        assertTrue(text(call.body!!).contains("--$boundary\r\n"))
    }

    @Test
    fun aMissingOrMalformedKeyOrAnUnpairedPhoneSendsNothing() {
        val http = PhotoHttp { HttpResult(200, "{}") }
        val client = CompanionClient(PhotoStore(Pairing(origin, token, "Samsung")), http, false)
        assertEquals("bad_request", code { client.uploadJournalPhoto("2026-11-22", photo, thumb, null, null) })
        assertEquals("bad_request", code { client.uploadJournalPhoto("2026-11-22", photo, thumb, null, "short") })
        assertEquals("bad_request", code { client.uploadJournalPhoto("nope", photo, thumb, null, "photo-key-0001") })
        val unpaired = CompanionClient(PhotoStore(null), http, false)
        assertEquals("not_paired", code { unpaired.uploadJournalPhoto("2026-11-22", photo, thumb, null, "photo-key-0001") })
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun aRefusedCredentialEndsThePairingAsForAnyOtherRequest() {
        var lost = 0
        val store = PhotoStore(Pairing(origin, token, "Samsung"))
        val http = PhotoHttp { HttpResult(401, """{"code":"unauthorized"}""") }
        val client = CompanionClient(store, http, false, { lost++ })
        val answer = client.uploadJournalPhoto("2026-11-22", photo, thumb, null, "photo-key-0001")
        assertEquals(401, answer.status)
        assertEquals(1, lost)
        assertEquals(null, store.pairing)
    }
}
