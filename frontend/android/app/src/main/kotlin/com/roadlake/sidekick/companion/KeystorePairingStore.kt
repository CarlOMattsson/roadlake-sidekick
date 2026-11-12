package com.roadlake.sidekick.companion

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The pairing, encrypted. The AES-256-GCM key is generated inside the Android Keystore and cannot be exported; the
 * encrypted record (server origin, token, label) sits in the app's private preferences, not the token in the Keystore
 * itself (ADR-005). The key needs no user authentication, so background work can read it after the first unlock.
 * Nothing here is logged. A record that cannot be decrypted (key lost after a restore, tampered data) throws
 * [UnreadablePairingException]; this class does not clear itself on that, the app's wiring does it through the normal
 * unpair path ([com.roadlake.sidekick.today.ClearingPairingStore]). A [clear] that fails throws, never silently.
 */
// commit() on purpose: save and clear return only once the change is on disk, so a pairing is never half-removed.
@SuppressLint("ApplySharedPref")
class KeystorePairingStore(context: Context) : PairingStore {
    private val preferences: SharedPreferences =
        context.applicationContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    @Synchronized
    override fun load(): Pairing? {
        val stored = preferences.getString(RECORD, null) ?: return null
        return try {
            val raw = Base64.decode(stored, Base64.NO_WRAP)
            val json = JSONObject(String(decrypt(raw), Charsets.UTF_8))
            Pairing(
                serverOrigin = json.getString("serverOrigin"),
                token = json.getString("token"),
                deviceLabel = json.optString("deviceLabel").ifEmpty { null },
                pairedAt = json.optString("pairedAt").ifEmpty { null },
                expiresAt = json.optString("expiresAt").ifEmpty { null },
                renewAfter = json.optString("renewAfter").ifEmpty { null },
                enabledRooms = DeviceInfo.roomsOf(json.optJSONArray("enabledRooms")),
                ownerTimeZone = OwnerZone.idOf(json.optString("ownerTimeZone")),
                pushEnabled = json.opt("pushEnabled") as? Boolean,
            )
        } catch (_: Exception) {
            throw UnreadablePairingException()
        }
    }

    @Synchronized
    override fun save(pairing: Pairing) {
        try {
            val json = JSONObject()
                .put("serverOrigin", pairing.serverOrigin)
                .put("token", pairing.token)
                .put("deviceLabel", pairing.deviceLabel ?: "")
                .put("pairedAt", pairing.pairedAt ?: "")
                .put("expiresAt", pairing.expiresAt ?: "")
                .put("renewAfter", pairing.renewAfter ?: "")
                .put("enabledRooms", pairing.enabledRooms?.let { JSONArray(it) } ?: "")
                .put("ownerTimeZone", pairing.ownerTimeZone ?: "")
                .put("pushEnabled", pairing.pushEnabled ?: "")
            val encrypted = encrypt(json.toString().toByteArray(Charsets.UTF_8))
            val saved = preferences.edit().putString(RECORD, Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()
            if (!saved) throw CompanionException("secure_storage")
        } catch (e: CompanionException) {
            throw e
        } catch (_: Exception) {
            throw CompanionException("secure_storage")
        }
    }

    @Synchronized
    override fun clear() {
        // Both removals are attempted; either failing is reported so the caller can retry (a stale key or record is not safe to forget).
        val recordRemoved = try {
            preferences.edit().clear().commit() && preferences.all.isEmpty()
        } catch (_: RuntimeException) {
            false
        }
        val keyRemoved = try {
            val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
            if (keyStore.containsAlias(KEY_ALIAS)) keyStore.deleteEntry(KEY_ALIAS)
            !keyStore.containsAlias(KEY_ALIAS) // proven, not assumed
        } catch (_: GeneralSecurityException) {
            false
        } catch (_: IOException) {
            false
        } catch (_: RuntimeException) {
            false
        }
        if (!recordRemoved || !keyRemoved) throw CompanionException("secure_storage")
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    /** IV (12 bytes, chosen by the Keystore) followed by the ciphertext and tag. */
    private fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(AAD)
        return cipher.iv + cipher.doFinal(plain)
    }

    private fun decrypt(record: ByteArray): ByteArray {
        require(record.size > IV_BYTES)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, record, 0, IV_BYTES))
        cipher.updateAAD(AAD)
        return cipher.doFinal(record, IV_BYTES, record.size - IV_BYTES)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "sidekick_companion_pairing_v1"
        const val PREFERENCES = "sidekick_companion"
        const val RECORD = "pairing"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
        val AAD = "sidekick.companion.pairing.v1".toByteArray(Charsets.UTF_8)
    }
}
