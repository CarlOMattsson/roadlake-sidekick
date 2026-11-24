package com.roadlake.sidekick.companion

import java.io.ByteArrayOutputStream
import java.security.SecureRandom

/** The body of a `multipart/form-data` request and the `Content-Type` that names its boundary. */
class MultipartForm(val contentType: String, val body: ByteArray)

/**
 * The photo a page adds to a journal day (`POST /companion/v1/journal/photos`, ADR-014). The page has already shrunk the
 * picture and drew the thumbnail (long edge 2048 px and 320 px, JPEG), which also leaves the metadata out of both; this
 * object checks what it is given against the server's limits before a connection is opened, and builds the form: the two
 * files and the fields beside them as the parts of one body. It holds no Android type, so it is unit tested on the JVM.
 *
 * Nothing here is logged: the bytes, the caption and the day never leave the form.
 */
object PhotoUpload {
    const val PATH = "/companion/v1/journal/photos"

    /** The server's limits (`PHOTO_LIMITS` and `THUMBNAIL_LIMITS` in the backend's photo domain). */
    const val MAX_PHOTO_BYTES = 4 * 1024 * 1024
    const val MAX_THUMBNAIL_BYTES = 128 * 1024
    const val MAX_CAPTION_CHARS = 500

    private val DAY = Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}")
    private const val CRLF = "\r\n"

    /** The form for [journalDate], [photo], [thumbnail] and the optional [caption]; `bad_request` for anything outside the limits. */
    fun form(
        journalDate: String?,
        photo: ByteArray?,
        thumbnail: ByteArray?,
        caption: String?,
        boundary: String = newBoundary(),
    ): MultipartForm {
        if (journalDate == null || !DAY.matches(journalDate)) throw CompanionException("bad_request")
        if (photo == null || photo.isEmpty() || photo.size > MAX_PHOTO_BYTES) throw CompanionException("bad_request")
        if (thumbnail == null || thumbnail.isEmpty() || thumbnail.size > MAX_THUMBNAIL_BYTES) {
            throw CompanionException("bad_request")
        }
        if (caption != null && caption.length > MAX_CAPTION_CHARS) throw CompanionException("bad_request")

        val out = ByteArrayOutputStream(photo.size + thumbnail.size + 1024)
        field(out, boundary, "journal_date", journalDate)
        if (!caption.isNullOrEmpty()) field(out, boundary, "alt_text", caption)
        file(out, boundary, "photo", "photo.jpg", photo)
        file(out, boundary, "thumbnail", "thumbnail.jpg", thumbnail)
        out.write("--$boundary--$CRLF".toByteArray(Charsets.US_ASCII))
        return MultipartForm("multipart/form-data; boundary=$boundary", out.toByteArray())
    }

    private fun field(out: ByteArrayOutputStream, boundary: String, name: String, value: String) {
        out.write("--$boundary${CRLF}Content-Disposition: form-data; name=\"$name\"$CRLF$CRLF".toByteArray(Charsets.US_ASCII))
        out.write(value.toByteArray(Charsets.UTF_8))
        out.write(CRLF.toByteArray(Charsets.US_ASCII))
    }

    private fun file(out: ByteArrayOutputStream, boundary: String, name: String, fileName: String, bytes: ByteArray) {
        out.write(
            (
                "--$boundary${CRLF}Content-Disposition: form-data; name=\"$name\"; filename=\"$fileName\"$CRLF" +
                    "Content-Type: image/jpeg$CRLF$CRLF"
                ).toByteArray(Charsets.US_ASCII),
        )
        out.write(bytes)
        out.write(CRLF.toByteArray(Charsets.US_ASCII))
    }

    /** A boundary no file or caption can contain by accident: 24 random bytes as hex. */
    private fun newBoundary(): String {
        val bytes = ByteArray(24).also { SecureRandom().nextBytes(it) }
        return "sidekick" + bytes.joinToString("") { "%02x".format(it) }
    }
}
