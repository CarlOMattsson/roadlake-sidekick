package com.roadlake.sidekick.today

import java.io.IOException
import java.security.GeneralSecurityException
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Where the AES-256 key of an [AesGcmCipher] lives: in the Android Keystore on the phone, in memory in a test. */
interface AesKeys {
    /** The key, or null when there is none (never made, or deleted). */
    fun existing(): SecretKey?

    /** Makes a key. Never exportable on the phone. */
    fun create(): SecretKey

    /** Removes the key; throws [IOException] when it is still there afterwards. */
    @Throws(IOException::class)
    fun delete()
}

/** The text cannot be decrypted with the key there is (no key, a lost key, or changed data): it is gone for good, not temporarily unreadable. */
class UndecryptableException : GeneralSecurityException("undecryptable")

/**
 * AES-256-GCM with a fresh random IV for every message, [aad] bound to the use. [encrypt] returns the IV followed by the
 * ciphertext and its tag. Nothing here is logged.
 */
class AesGcmCipher(private val keys: AesKeys, private val aad: ByteArray) {
    @Synchronized
    @Throws(GeneralSecurityException::class)
    fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, keys.existing() ?: keys.create())
        cipher.updateAAD(aad)
        return cipher.iv + cipher.doFinal(plain)
    }

    /** Throws [UndecryptableException] when the data cannot be decrypted for good; another [GeneralSecurityException] means the key store cannot answer now. */
    @Synchronized
    @Throws(GeneralSecurityException::class)
    fun decrypt(sealed: ByteArray): ByteArray {
        val key = keys.existing() ?: throw UndecryptableException()
        if (sealed.size <= IV_BYTES + TAG_BYTES) throw UndecryptableException()
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BYTES * 8, sealed, 0, IV_BYTES))
        cipher.updateAAD(aad)
        return try {
            cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
        } catch (_: AEADBadTagException) {
            throw UndecryptableException()
        }
    }

    private companion object {
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BYTES = 16
    }
}

/**
 * A [TextStore] whose text is encrypted at rest: [inner] only ever holds hexadecimal ciphertext, so what the user wrote
 * (the journal queue) is never on disk in clear text, in the file, its temporary copy or the quarantined one. The key
 * belongs to the [cipher]; [erase] removes the key together with the file, so what is left cannot be read.
 *
 * Text that can never be decrypted again (the key is gone, or the file was changed) reads as empty text, which the queue
 * above takes for an unparseable file and moves aside. A key store that only cannot answer now is an [IOException]: the
 * queue stops changing and tries again, it does not throw the file away.
 */
class EncryptedTextStore(private val inner: TextStore, private val cipher: AesGcmCipher, private val keys: AesKeys) : TextStore {
    @Throws(IOException::class)
    override fun read(): String? {
        val stored = inner.read() ?: return null
        return try {
            String(cipher.decrypt(fromHex(stored)), Charsets.UTF_8)
        } catch (_: UndecryptableException) {
            ""
        } catch (_: IllegalArgumentException) {
            ""
        } catch (e: GeneralSecurityException) {
            throw IOException("key store unavailable", e)
        } catch (e: RuntimeException) {
            throw IOException("key store unavailable", e)
        }
    }

    @Throws(IOException::class)
    override fun write(text: String) {
        val sealed = try {
            cipher.encrypt(text.toByteArray(Charsets.UTF_8))
        } catch (e: GeneralSecurityException) {
            throw IOException("cannot encrypt", e)
        } catch (e: RuntimeException) {
            throw IOException("cannot encrypt", e)
        }
        inner.write(toHex(sealed))
    }

    override fun delete() = inner.delete()

    @Throws(IOException::class)
    override fun erase() {
        inner.erase()
        keys.delete()
    }

    @Throws(IOException::class)
    override fun quarantine() = inner.quarantine()

    private fun toHex(bytes: ByteArray): String {
        val out = StringBuilder(bytes.size * 2)
        for (byte in bytes) {
            out.append(HEX[(byte.toInt() shr 4) and 0xF]).append(HEX[byte.toInt() and 0xF])
        }
        return out.toString()
    }

    private fun fromHex(text: String): ByteArray {
        require(text.length % 2 == 0)
        return ByteArray(text.length / 2) { index ->
            val high = Character.digit(text[index * 2], 16)
            val low = Character.digit(text[index * 2 + 1], 16)
            require(high >= 0 && low >= 0)
            ((high shl 4) or low).toByte()
        }
    }

    private companion object {
        val HEX = "0123456789abcdef".toCharArray()
    }
}
