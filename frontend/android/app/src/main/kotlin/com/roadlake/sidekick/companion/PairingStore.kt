package com.roadlake.sidekick.companion

/**
 * What a paired phone keeps: where the server is, the device credential, and the label the operator gave the device.
 * [pairedAt], [expiresAt] and [renewAfter] are the server's ISO 8601 instants (null when the server has not said, as in
 * a pairing made before renewal existed). [enabledRooms] is the rooms the instance shows, as the server last said
 * (null: it never did, which reads as every room), kept so the app draws the right rooms offline. [ownerTimeZone] is the
 * owner's zone as the server last said ([OwnerZone]; null: it never did), kept so dates and reminder times are the
 * owner's also without a network. [pushEnabled] is whether the server delivers push, as it last said (null: it never
 * did), kept so the app can hide its push row also on a cold start without a network.
 * Deliberately not a data class: no `toString` that would print the token.
 */
class Pairing(
    val serverOrigin: String,
    val token: String,
    val deviceLabel: String?,
    val pairedAt: String? = null,
    val expiresAt: String? = null,
    val renewAfter: String? = null,
    val enabledRooms: List<String>? = null,
    val ownerTimeZone: String? = null,
    val pushEnabled: Boolean? = null,
) {
    /**
     * True when [other] is this very device on this server, also under a renewed credential: renewal changes the token
     * but keeps the server and the time of pairing. A new pairing (even after a clear) differs in [pairedAt].
     */
    fun isSameDeviceAs(other: Pairing) = serverOrigin == other.serverOrigin && pairedAt == other.pairedAt

    /** The same pairing with what `GET /device` said; a field the server left out keeps its old value. */
    fun withDevice(info: DeviceInfo) = Pairing(
        serverOrigin,
        token,
        info.label ?: deviceLabel,
        info.createdAt ?: pairedAt,
        info.expiresAt ?: expiresAt,
        info.renewAfter ?: renewAfter,
        info.enabledRooms ?: enabledRooms,
        info.ownerTimeZone ?: ownerTimeZone,
        info.pushEnabled ?: pushEnabled,
    )

    /** The same pairing under a renewed credential. */
    fun withRenewedToken(newToken: String, info: DeviceInfo) = Pairing(
        serverOrigin, newToken, deviceLabel, pairedAt, info.expiresAt ?: expiresAt, info.renewAfter ?: renewAfter,
        info.enabledRooms ?: enabledRooms, info.ownerTimeZone ?: ownerTimeZone,
        info.pushEnabled ?: pushEnabled,
    )

    fun withRenewAfter(renewAfter: String) =
        Pairing(serverOrigin, token, deviceLabel, pairedAt, expiresAt, renewAfter, enabledRooms, ownerTimeZone, pushEnabled)
}

/**
 * Where the pairing lives. The Android implementation ([KeystorePairingStore]) encrypts it with a Keystore key; the
 * interface exists so the client logic is tested on the JVM without the Android framework.
 */
interface PairingStore {
    /**
     * The stored pairing, or null when there is none. A record that exists but cannot be read (key lost after a restore,
     * tampered or truncated data) throws [UnreadablePairingException]: the store does not clear itself, so that the one
     * normal end of a pairing ([clear] through the app's wiring) is the only way a pairing disappears.
     */
    @Throws(UnreadablePairingException::class)
    fun load(): Pairing?

    /** Throws [CompanionException] (`secure_storage`) when the pairing could not be stored. */
    fun save(pairing: Pairing)

    /**
     * Replaces the stored pairing with a newer record of the same pairing (renewed token, new dates). Unlike [save] it
     * starts nothing: what belongs to the pairing (the cache, the outbox) stays. Throws like [save].
     */
    fun update(pairing: Pairing) = save(pairing)

    /**
     * Removes the credential and everything derived from it (the cache, once there is one). Throws
     * [CompanionException] (`secure_storage`) when the stored pairing or its key could not be removed; every removal is
     * still attempted first.
     */
    fun clear()

    /**
     * True when a new pairing may start: nothing of an earlier one is left to remove (or it was just removed). Asked
     * before the pairing code is spent, so a phone that cannot wipe its old data refuses early and the code stays valid.
     * Throws [CompanionException] (`already_paired`) when a pairing exists by now; a store that wipes must check this under
     * [PairingLock] and must never remove an existing pairing.
     */
    fun readyForPairing(): Boolean = true
}

/** The stored pairing exists but cannot be read. Carries no content: never the record, the key or the cause's message. */
class UnreadablePairingException : Exception("stored pairing unreadable")
