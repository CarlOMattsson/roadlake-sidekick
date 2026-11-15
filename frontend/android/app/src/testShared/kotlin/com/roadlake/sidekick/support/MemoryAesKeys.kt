package com.roadlake.sidekick.support

import com.roadlake.sidekick.today.AesKeys
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** An AES-256 key kept in memory, for the JVM tests where there is no Android Keystore. */
class MemoryAesKeys : AesKeys {
    private var key: SecretKey? = null

    /** How many keys were made, so a test can tell a key that was removed and made again. */
    var created = 0
        private set

    override fun existing(): SecretKey? = key

    override fun create(): SecretKey {
        created++
        return KeyGenerator.getInstance("AES").apply { init(256) }.generateKey().also { key = it }
    }

    override fun delete() {
        key = null
    }
}
