package com.roadlake.sidekick.today

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * An AES-256-GCM key generated inside the Android Keystore under [alias]: it cannot be exported, and it needs no user
 * authentication, so background work can use it after the first unlock (the same rule as the pairing's key).
 */
class KeystoreAesKeys(private val alias: String) : AesKeys {
    override fun existing(): SecretKey? = keyStore().getKey(alias, null) as? SecretKey

    override fun create(): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    @Throws(IOException::class)
    override fun delete() {
        try {
            val store = keyStore()
            if (store.containsAlias(alias)) store.deleteEntry(alias)
            if (store.containsAlias(alias)) throw IOException("key still present") // proven, not assumed
        } catch (e: GeneralSecurityException) {
            throw IOException("key could not be removed", e)
        } catch (e: RuntimeException) {
            throw IOException("key could not be removed", e)
        }
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
    }
}
