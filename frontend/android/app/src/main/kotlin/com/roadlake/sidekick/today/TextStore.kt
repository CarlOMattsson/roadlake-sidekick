package com.roadlake.sidekick.today

import android.system.Os
import android.system.OsConstants
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

/** One small text file's worth of durable state. An interface so the cache and the outbox are tested on the JVM. */
interface TextStore {
    /**
     * The stored text, or null when there is none (the file does not exist). A file that exists but cannot be read
     * throws [IOException]: that is not "empty", and a caller must not write over what it could not read.
     */
    @Throws(IOException::class)
    fun read(): String?

    /**
     * Replaces the text; the old text stays whole if this fails (it throws [IOException]). The one exception is
     * [UncertainCommitException]: the write failed and so did the undo, so either text may be stored. A caller that must
     * know (a queue) reads the store again; the others treat it as an ordinary failure.
     */
    @Throws(IOException::class)
    fun write(text: String)

    fun delete()

    /**
     * Like [delete], but proves it: throws [IOException] when anything of the stored text is still there afterwards. Used
     * where the data belongs to a pairing that has ended, and a new pairing must not start next to what is left of it.
     */
    @Throws(IOException::class)
    fun erase() {
        delete()
        if (read() != null) throw IOException("still present after delete")
    }

    /**
     * Moves a file whose content cannot be parsed aside as `<name>.corrupt` (replacing an older one), so the next write
     * does not destroy it. Throws [IOException] when it could not be moved; the file is then left where it is.
     */
    @Throws(IOException::class)
    fun quarantine()
}

/**
 * A write failed and the undo of it failed too (the file system refused the directory fsync, then the put-back), so what
 * the store holds is either the old or the new text. It is an [IOException] so every caller still sees a failed write;
 * a caller that owns a queue reads the store to learn which text won rather than assuming the old one.
 */
class UncertainCommitException(message: String, cause: Throwable) : IOException(message, cause)

/**
 * A [TextStore] in one file, written so that a write which returns has reached the disk and one that fails says so.
 * (`android.util.AtomicFile.finishWrite` swallows a failed fsync or rename and only logs it, so it cannot back a queue
 * that tells the user "saved".) The new text goes to `<name>.tmp`, is flushed and fsynced (a failure throws), and then
 * replaces the file with one rename, which is atomic on the same file system. Every failure is an [IOException] and the
 * previous content stays whole. A missing file reads as null; a file that exists but cannot be read throws, so it is
 * never taken for an empty store. A `.tmp` found at read time is a write that never finished and is removed. The
 * directory is then fsynced so the rename itself survives a power cut; a failure there is an [IOException] too (the
 * write is not reported as saved, and the previous content is put back so that nothing unconfirmed stays on disk; if
 * the put-back fails as well the failure is an [UncertainCommitException], because the new text may still be there).
 *
 * [rename] is the commit step and returns false when it did not happen; [syncDirectory] fsyncs the directory and throws
 * [IOException] on failure; both can be replaced in tests. [onDeleteFailure] gets a data-free message when [delete]
 * could not remove a file (the others are still tried).
 * minSdk is 24, so `java.nio.file.Files.move` (API 26) is not available and [File.renameTo] is used.
 */
class FileTextStore(
    private val file: File,
    private val rename: (File, File) -> Boolean = { from, to -> from.renameTo(to) },
    private val syncDirectory: (File) -> Unit = ::fsyncDirectory,
    private val onDeleteFailure: (String) -> Unit = {},
) : TextStore {
    private val temporary get() = File(file.path + ".tmp")
    private val legacyBackup get() = File(file.path + ".bak") // kept by android.util.AtomicFile in older versions

    /** Every file that can hold this store's text: the file, a half-written copy, the old backup and the quarantined copy. */
    private fun allFiles() = listOf(file, temporary, legacyBackup, File(file.path + ".corrupt"))

    @Synchronized
    override fun read(): String? {
        temporary.delete()
        val backup = legacyBackup
        if (backup.isFile) {
            // An older AtomicFile write was cut off: the backup is the last complete content, the file may be partial.
            file.delete()
            if (!backup.renameTo(file)) throw IOException("could not restore the previous content")
        }
        if (!file.exists()) return null
        return file.readBytes().toString(Charsets.UTF_8)
    }

    @Synchronized
    override fun write(text: String) {
        val directory = file.absoluteFile.parentFile
        if (directory != null && !directory.isDirectory && !directory.mkdirs() && !directory.isDirectory) {
            throw IOException("no directory")
        }
        // Kept so that a write whose rename cannot be made durable is undone: a file that is on disk but was reported as
        // failed must not later be read as saved (the caller would queue the same entry again, or treat it as confirmed).
        val previous = if (file.isFile) file.readBytes() else null
        replaceFile(text.toByteArray(Charsets.UTF_8))
        if (directory != null) {
            try {
                syncDirectory(directory)
            } catch (failure: IOException) {
                if (!restore(previous, directory)) throw UncertainCommitException("write not durable and not undone", failure)
                throw failure
            }
        }
    }

    /** Writes [bytes] to the temporary file, fsyncs it and renames it over the file; every failure is an [IOException]. */
    private fun replaceFile(bytes: ByteArray) {
        val tmp = temporary
        try {
            FileOutputStream(tmp).use { stream ->
                stream.write(bytes)
                stream.flush()
                stream.fd.sync()
            }
            if (!rename(tmp, file)) throw IOException("could not replace the file")
        } catch (failure: IOException) {
            tmp.delete()
            throw failure
        } catch (failure: RuntimeException) {
            tmp.delete()
            throw failure
        }
    }

    /**
     * Puts the content from before a failed write back (or removes the file that did not exist). Returns false when the
     * file may still hold the new text; a directory fsync that fails after the put-back only leaves the old text
     * undurable, which is not a doubt about the content.
     */
    private fun restore(previous: ByteArray?, directory: File): Boolean {
        try {
            if (previous == null) {
                if (!file.delete() && file.exists()) return false
            } else {
                replaceFile(previous)
            }
        } catch (_: IOException) {
            return false
        } catch (_: RuntimeException) {
            return false
        }
        try {
            syncDirectory(directory)
        } catch (_: IOException) {
            // The old content is in place; only its durability is unconfirmed.
        } catch (_: RuntimeException) {
        }
        return true
    }

    @Synchronized
    override fun delete() {
        // The quarantined copy holds the same personal data as the file, so it goes too.
        allFiles().forEach { target ->
            val removed = try {
                target.delete() || !target.exists()
            } catch (_: SecurityException) {
                false
            }
            if (!removed) onDeleteFailure("could not delete ${target.name}")
        }
    }

    @Synchronized
    override fun erase() {
        var left = 0
        allFiles().forEach { target ->
            val removed = try {
                target.delete() || !target.exists()
            } catch (_: SecurityException) {
                false
            }
            if (!removed) left++
        }
        if (left > 0) throw IOException("$left file(s) could not be removed")
    }

    @Synchronized
    override fun quarantine() {
        if (!file.isFile) return
        val corrupt = File(file.path + ".corrupt")
        corrupt.delete()
        if (!file.renameTo(corrupt)) throw IOException("could not move the unreadable file aside")
    }
}

/**
 * Fsyncs a directory so a rename in it is durable. Android rejects `FileInputStream(directory)`, so the directory is
 * opened with `Os.open` read-only (the SDK has no public `O_DIRECTORY`, and its value differs between ABIs; Linux opens
 * a directory read-only without it, and it is the same as `O_DIRECTORY` for our purpose). Runs on a device only; the JVM
 * tests inject a fake.
 */
internal fun fsyncDirectory(directory: File) {
    try {
        val descriptor = Os.open(directory.path, OsConstants.O_RDONLY, 0)
        try {
            Os.fsync(descriptor)
        } finally {
            Os.close(descriptor)
        }
    } catch (failure: android.system.ErrnoException) {
        throw IOException("could not sync the directory (errno ${failure.errno})")
    }
}
