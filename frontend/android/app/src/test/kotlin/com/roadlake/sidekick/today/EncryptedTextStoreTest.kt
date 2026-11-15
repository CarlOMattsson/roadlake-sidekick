package com.roadlake.sidekick.today

import com.roadlake.sidekick.support.MemoryAesKeys
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.ProviderException
import javax.crypto.SecretKey

/** [EncryptedTextStore] over a memory store and a real AES-GCM key, alone and under the [Outbox] that keeps the journal queue. */
class EncryptedTextStoreTest {
    private val plain = "Hemlig dagbok: åäö kl. 07"
    private val keys = MemoryAesKeys()
    private val inner = MemoryTextStore()
    private var quarantines = 0

    private fun store(with: AesKeys = keys, aad: ByteArray = ByteArray(0)) = EncryptedTextStore(inner, AesGcmCipher(with, aad), with)

    private fun journalOutbox(with: AesKeys = keys) = Outbox(store(with), onQuarantine = { quarantines++ }, clock = { 1_000L })

    private fun Outbox.queueJournalText() =
        enqueueRecordWrite(OutboxKind.JOURNAL_CREATE, Outbox.NEW_SUBJECT, 0, """{"text":"$plain"}""", "journal-key-0001")

    /** A key store that cannot answer (it is locked, or its provider failed): not the same as a key that is gone. */
    private class UnavailableKeys(private val failure: Exception) : AesKeys {
        override fun existing(): SecretKey? = throw failure

        override fun create(): SecretKey = throw failure

        override fun delete() = Unit
    }

    private fun tamperedWithOneCharacter(hex: String): String {
        val at = hex.length / 2
        return hex.replaceRange(at, at + 1, if (hex[at] == '0') "1" else "0")
    }

    @Test
    fun theTextReadsBackAndWhatIsStoredIsHexWithoutTheText() {
        val store = store()
        store.write(plain)
        assertEquals(plain, store.read())
        val stored = inner.text!!
        assertTrue(stored.matches(Regex("[0-9a-f]+")))
        assertFalse(stored.contains("Hemlig"))
        assertFalse(stored.contains("åäö"))
        assertFalse(stored.contains(plain.toByteArray().joinToString("") { "%02x".format(it) }))
    }

    @Test
    fun nothingStoredReadsAsNoText() {
        assertNull(store().read())
    }

    @Test
    fun twoWritesOfTheSameTextGiveDifferentCiphertext() {
        val store = store()
        store.write(plain)
        val first = inner.text
        store.write(plain)
        assertNotEquals(first, inner.text)
        assertEquals(plain, store.read())
    }

    @Test
    fun textSealedForAnotherUseDoesNotDecrypt() {
        store(aad = "other".toByteArray()).write(plain)
        assertEquals("", store().read())
    }

    @Test
    fun changedCiphertextReadsAsEmptyAndTheQueueMovesTheFileAside() {
        val outbox = journalOutbox()
        assertNotNull(outbox.queueJournalText())
        val sealed = inner.text!!
        inner.text = tamperedWithOneCharacter(sealed)

        assertEquals("", store().read())
        val reopened = journalOutbox()
        assertTrue(reopened.pending().isEmpty())

        assertEquals("the file is moved aside, not thrown away", tamperedWithOneCharacter(sealed), inner.quarantined)
        assertNull(inner.text)
        assertEquals(1, quarantines)
        val restarted = reopened.enqueueRecordWrite(OutboxKind.JOURNAL_CREATE, Outbox.NEW_SUBJECT, 0, "{}", "journal-key-0002")
        assertNotNull("the queue starts again", restarted)
        assertEquals(listOf("journal-key-0002"), reopened.pending().map { it.idempotencyKey })
    }

    @Test
    fun textThatIsNotHexReadsAsEmpty() {
        inner.text = "not hex at all"
        assertEquals("", store().read())
        inner.text = "abc"
        assertEquals("an odd length is not ciphertext", "", store().read())
    }

    @Test
    fun aRemovedKeyReadsAsEmptyNeverAsTheTextAndNeverThrows() {
        val outbox = journalOutbox()
        outbox.queueJournalText()
        keys.delete()

        assertEquals("", store().read())
        assertTrue(journalOutbox().pending().isEmpty())
        assertNull(keys.existing())
        assertEquals(1, quarantines)
        assertFalse(inner.quarantined.orEmpty().contains(plain))
    }

    private fun assertKeyStoreFailureIsNotLossOfTheQueue(failure: Exception) {
        journalOutbox().queueJournalText()
        val sealed = inner.text!!
        val unavailable = UnavailableKeys(failure)

        assertThrows(IOException::class.java) { store(unavailable).read() }

        val outbox = journalOutbox(unavailable)
        assertTrue(outbox.pending().isEmpty())
        assertNull("nothing can be added while the queue cannot be read", outbox.queueJournalText())
        assertEquals("the file stays where it is, unchanged", sealed, inner.text)
        assertNull(inner.quarantined)
        assertEquals(0, quarantines)
        assertEquals("a key store that answers again finds the queue whole", 1, journalOutbox().pending().size)
    }

    @Test
    fun aKeyStoreThatCannotAnswerIsAnIoErrorAndTheFileIsNotMovedAside() =
        assertKeyStoreFailureIsNotLossOfTheQueue(GeneralSecurityException("locked"))

    @Test
    fun aKeyStoreProviderFailureIsAnIoErrorAndTheFileIsNotMovedAside() =
        assertKeyStoreFailureIsNotLossOfTheQueue(ProviderException("keystore died"))

    @Test
    fun eraseEmptiesTheStoreAndRemovesTheKeySoANewWriteMakesANewKey() {
        val store = store()
        store.write(plain)
        assertEquals(1, keys.created)

        store.erase()

        assertNull(inner.text)
        assertNull(inner.read())
        assertNull(keys.existing())
        assertNull(store.read())

        store.write("Ny text")
        assertEquals(2, keys.created)
        assertEquals("Ny text", store.read())
    }

    @Test
    fun aQueuedJournalWriteIsNeverOnDiskAsTextAndEraseLeavesNothing() {
        val outbox = journalOutbox()
        val entry = outbox.queueJournalText()!!
        assertEquals("""{"text":"$plain"}""", entry.bodyJson())
        assertFalse(inner.text!!.contains("Hemlig"))
        assertFalse(inner.text!!.contains("journal-key-0001"))
        assertEquals("a restart reads it back", plain, JSONObject(journalOutbox().pending().single().bodyJson()).getString("text"))

        outbox.remove(entry.subjectId, entry.idempotencyKey)

        assertTrue(journalOutbox().pending().isEmpty())
        assertFalse("nothing of the text is left once it was sent", inner.text.orEmpty().contains("Hemlig"))

        outbox.queueJournalText()
        outbox.erase()

        assertNull(inner.text)
        assertNull(inner.quarantined)
        assertNull(keys.existing())
        assertFalse(outbox.hasData())
        assertTrue(outbox.pending().isEmpty())
    }
}
