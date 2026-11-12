package com.roadlake.sidekick.today

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException

/** [FileTextStore] against real files in a temp directory (it is plain java.io, so it runs on the JVM). */
class FileTextStoreTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val target by lazy { File(folder.root, "today/state.json") }
    private val tmp get() = File(target.path + ".tmp")

    private fun store(
        rename: (File, File) -> Boolean = { from, to -> from.renameTo(to) },
        syncDirectory: (File) -> Unit = {},
        onDeleteFailure: (String) -> Unit = {},
    ) = FileTextStore(target, rename, syncDirectory, onDeleteFailure)

    private fun assertFails(block: () -> Unit) {
        try {
            block()
            fail("expected an IOException")
        } catch (_: IOException) {
        }
    }

    @Test
    fun aMissingFileReadsAsNull() {
        assertNull(store().read())
    }

    @Test
    fun aWrittenTextIsReadBackAndReplacesTheOld() {
        val store = store()
        store.write("åäö 1")
        assertEquals("åäö 1", store.read())
        store.write("two")
        assertEquals("two", FileTextStore(target).read())
        assertFalse(tmp.exists())
    }

    @Test
    fun aFailedRenameThrowsAndLeavesThePreviousContent() {
        store().write("previous")
        assertFails { store(rename = { _, _ -> false }).write("new") }
        assertEquals("previous", store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun aRenameThatThrowsIsNotSwallowed() {
        store().write("previous")
        assertFails { store(rename = { _, _ -> throw IOException("io") }).write("new") }
        assertEquals("previous", store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun aRealRenameFailureWhenTheTargetIsADirectoryThrows() {
        target.mkdirs()
        File(target, "inner").writeText("x")
        assertFails { store().write("new") }
        assertTrue(target.isDirectory)
        assertFalse(tmp.exists())
    }

    @Test
    fun aDirectoryThatCannotBeCreatedThrows() {
        File(folder.root, "today").writeText("a file where the directory should be")
        assertFails { store().write("new") }
    }

    @Test
    fun aFileThatCannotBeReadThrowsInsteadOfReadingEmpty() {
        target.mkdirs() // exists but is not readable as text
        assertFails { store().read() }
    }

    @Test
    fun aLeftoverTmpIsRemovedOnReadWithoutTouchingTheTarget() {
        store().write("kept")
        tmp.writeText("half a wri")
        assertEquals("kept", store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun aLeftoverTmpWithNoTargetReadsAsNull() {
        target.parentFile!!.mkdirs()
        tmp.writeText("half")
        assertNull(store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun anOlderAtomicFileBackupIsRestored() {
        target.parentFile!!.mkdirs()
        File(target.path + ".bak").writeText("last complete")
        target.writeText("partial")
        assertEquals("last complete", store().read())
        assertFalse(File(target.path + ".bak").exists())
    }

    @Test
    fun quarantineMovesTheTextAsideAndReplacesAnOlderOne() {
        val store = store()
        store.write("broken")
        store.quarantine()
        assertNull(store.read())
        assertEquals("broken", File(target.path + ".corrupt").readText())
        store.write("broken again")
        store.quarantine()
        assertEquals("broken again", File(target.path + ".corrupt").readText())
    }

    @Test
    fun quarantineOfAMissingFileDoesNothing() {
        store().quarantine()
        assertNull(store().read())
    }

    @Test
    fun deleteRemovesTheFile() {
        val store = store()
        store.write("x")
        store.delete()
        assertNull(store.read())
        assertFalse(target.exists())
    }

    @Test
    fun theDirectoryIsSyncedAfterTheRenameAndNotBefore() {
        val events = mutableListOf<String>()
        store(
            rename = { from, to ->
                events += "rename"
                from.renameTo(to)
            },
            syncDirectory = { events += "sync:${it.name}" },
        ).write("x")
        assertEquals(listOf("rename", "sync:today"), events)
    }

    @Test
    fun aFailedDirectorySyncMakesTheWriteFailAndPutsThePreviousContentBack() {
        store().write("previous")
        assertFails { store(syncDirectory = { throw IOException("fsync") }).write("new") }
        assertEquals("previous", store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun aFailedDirectorySyncOfAFirstWriteLeavesNoFile() {
        assertFails { store(syncDirectory = { throw IOException("fsync") }).write("new") }
        assertFalse(target.exists())
        assertNull(store().read())
    }

    /** The first rename (the new text) works, the directory fsync fails, and so does the put-back's rename. */
    private fun failingUndo(): FileTextStore {
        var renames = 0
        return store(
            rename = { from, to -> renames++ == 0 && from.renameTo(to) },
            syncDirectory = { throw IOException("fsync") },
        )
    }

    @Test
    fun aFailedDirectorySyncWhoseUndoFailsToo_isReportedAsAnUncertainCommit() {
        store().write("previous")
        try {
            failingUndo().write("new")
            fail("expected an UncertainCommitException")
        } catch (_: UncertainCommitException) {
        }
        // The new text may be what is on disk; the store says nothing else and leaves no half-written copy.
        assertEquals("new", store().read())
        assertFalse(tmp.exists())
    }

    @Test
    fun anUncertainCommitIsStillAnIOExceptionForEveryOtherCaller() {
        store().write("previous")
        assertFails { failingUndo().write("new") }
    }

    /** Like [failingUndo] but the fault can be cleared: while [broken] is true the directory fsync and every later rename fail. */
    private class Fault(var broken: Boolean = true)

    private fun faulty(fault: Fault): FileTextStore {
        var first = true
        return store(
            rename = { from, to -> if (first || !fault.broken) from.renameTo(to).also { first = false } else false },
            syncDirectory = { if (fault.broken) throw IOException("fsync") },
        )
    }

    @Test
    fun anUncertainCommitIsNotReportedAsQueuedEvenWhenTheFileHoldsTheEntry() {
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_B, 1, "key-0"))
        val outbox = Outbox(failingUndo(), clock = { 1_000L })
        // The entry reads back from the file, but readable is not durable: the caller is told it is not saved.
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        // The entry on disk is not lost and not duplicated: a later drain still sees it once.
        assertEquals(listOf("key-0", "key-1"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
    }

    @Test
    fun aRetryWhileTheDirectoryStillCannotBeSyncedStaysUnconfirmed() {
        val outbox = Outbox(failingUndo(), clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        assertNull(outbox.enqueuePurchase(TASK_A, 3, true, "key-2"))
        assertNull(outbox.enqueueShoppingAdd(TASK_A, """{"items":[{"name":"Milk"}]}""", "key-3"))
    }

    @Test
    fun aRetryAfterAnUncertainCommitReusesTheKeySyncsTheQueueAndThenReportsQueued() {
        // An earlier queue on disk, so the failed write's undo is a rename (which fails too) and the commit is uncertain.
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_B, 1, "key-0"))
        val fault = Fault()
        val outbox = Outbox(faulty(fault), clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        fault.broken = false
        // The retry carries a new key from a new tap (or the same one); the entry already on disk wins, once, and is now synced.
        assertEquals("key-1", outbox.enqueue(TASK_A, 3, "key-2")!!.idempotencyKey)
        assertEquals(listOf("key-0", "key-1"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
        // Confirmed: a further hit answers without writing, even if the disk breaks again.
        fault.broken = true
        assertEquals("key-1", outbox.enqueue(TASK_A, 3, "key-3")!!.idempotencyKey)
    }

    @Test
    fun aLaterSuccessfulWriteOfAnotherEntryConfirmsAnEarlierUncertainOne() {
        // An earlier queue on disk, so the failed write's undo is a rename (which fails too) and the commit is uncertain.
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_B, 1, "key-0"))
        val fault = Fault()
        val outbox = Outbox(faulty(fault), clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        fault.broken = false
        assertNotNull(outbox.enqueue("task-c", 1, "key-2"))
        fault.broken = true
        assertEquals("key-1", outbox.enqueue(TASK_A, 3, "key-3")!!.idempotencyKey)
        assertEquals(listOf("key-0", "key-1", "key-2"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
    }

    @Test
    fun theOutboxDoesNotLoseEarlierEntriesWhenALaterWriteIsUncertain() {
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_A, 3, "key-1"))
        val outbox = Outbox(failingUndo(), clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_B, 1, "key-2"))
        assertEquals(listOf("key-1", "key-2"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
    }

    @Test
    fun anUncertainCommitThatTheFileDidNotTakeIsAFailureAndTheQueueStaysAsItWas() {
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_A, 3, "key-1"))
        // The store reports an uncertain commit but the old queue is what is on disk (the new text never landed).
        val old = store()
        val uncertain = object : TextStore by old {
            override fun write(text: String) = throw UncertainCommitException("x", IOException("y"))
        }
        val outbox = Outbox(uncertain, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_B, 1, "key-2"))
        assertEquals(listOf("key-1"), outbox.pending().map { it.idempotencyKey })
    }

    @Test
    fun anUncertainCommitWhoseFileCannotBeReadIsAFailureAndLaterChangesStillReadTheFile() {
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_A, 3, "key-1"))
        var readable = false
        val old = store()
        val unreadable = object : TextStore by old {
            override fun write(text: String) = throw UncertainCommitException("x", IOException("y"))
            override fun read(): String? = if (readable) old.read() else throw IOException("busy")
        }
        val outbox = Outbox(unreadable, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_B, 1, "key-2"))
        readable = true
        assertEquals(listOf("key-1"), outbox.pending().map { it.idempotencyKey })
    }

    @Test
    fun anEntryOnDiskAfterAnUncertainCommitWhoseReadBackFailedIsNotReportedAsQueuedUntilSynced() {
        val real = store()
        var broken = true
        var written = false
        val flaky = object : TextStore by real {
            override fun write(text: String) {
                if (!broken) return real.write(text)
                real.write(text) // the text lands, but the commit is reported as uncertain
                written = true
                throw UncertainCommitException("x", IOException("y"))
            }
            override fun read(): String? = if (written && broken) throw IOException("busy") else real.read()
        }
        val outbox = Outbox(flaky, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        // The read back failed, so nothing was confirmed. The file now reads fine and holds the entry, but while the
        // commit still cannot be made certain the retry is not reported as queued.
        written = false
        assertNull(outbox.enqueue(TASK_A, 3, "key-2"))
        broken = false
        assertEquals("key-1", outbox.enqueue(TASK_A, 3, "key-3")!!.idempotencyKey)
    }

    @Test
    fun theOutboxIsNotQueuedWhenTheDirectoryCouldNotBeSynced() {
        val failing = store(syncDirectory = { throw IOException("fsync") })
        val outbox = Outbox(failing, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        // The entry that was reported as not saved is not there for a later pending() either.
        assertTrue(outbox.pending().isEmpty())
        assertTrue(Outbox(store(), clock = { 1_000L }).pending().isEmpty())
    }

    @Test
    fun aRetryAfterAFailedDirectorySyncQueuesTheEntryOnce() {
        var failures = 1
        val flaky = store(syncDirectory = { if (failures-- > 0) throw IOException("fsync") })
        val outbox = Outbox(flaky, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        assertNotNull(outbox.enqueue(TASK_A, 3, "key-1"))
        assertEquals(listOf("key-1"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
    }

    @Test
    fun aFailedDirectorySyncKeepsTheEarlierEntriesOfTheOutbox() {
        assertNotNull(Outbox(store(), clock = { 1_000L }).enqueue(TASK_A, 3, "key-1"))
        val failing = Outbox(store(syncDirectory = { throw IOException("fsync") }), clock = { 1_000L })
        assertNull(failing.enqueue(TASK_B, 1, "key-2"))
        assertEquals(listOf("key-1"), Outbox(store(), clock = { 1_000L }).pending().map { it.idempotencyKey })
    }

    @Test
    fun deleteAlsoRemovesTheCorruptCopy() {
        val store = store()
        store.write("broken")
        store.quarantine()
        store.write("again")
        assertTrue(File(target.path + ".corrupt").exists())
        store.delete()
        assertFalse(File(target.path + ".corrupt").exists())
        assertFalse(target.exists())
    }

    @Test
    fun aDeleteFailureIsReportedWithoutDataAndTheRestIsStillRemoved() {
        val messages = mutableListOf<String>()
        val store = store(onDeleteFailure = { messages += it })
        store.write("secret")
        val corrupt = File(target.path + ".corrupt")
        corrupt.mkdirs() // a non-empty directory cannot be deleted as a file
        File(corrupt, "inner").writeText("x")
        store.delete()
        assertFalse(target.exists())
        assertEquals(listOf("could not delete state.json.corrupt"), messages)
    }

    @Test
    fun theOutboxIsNotQueuedWhenTheFileCouldNotBeSaved() {
        val failing = store(rename = { _, _ -> false })
        val outbox = Outbox(failing, clock = { 1_000L })
        assertNull(outbox.enqueue(TASK_A, 3, "key-1"))
        assertTrue(outbox.pending().isEmpty())
        assertFalse(target.exists())
    }

    @Test
    fun theOutboxKeepsAnEntryThroughARealStore() {
        val first = Outbox(store(), clock = { 1_000L })
        assertNotNull(first.enqueue(TASK_A, 3, "key-1"))
        assertEquals("key-1", Outbox(store(), clock = { 1_000L }).pending().single().idempotencyKey)
    }
}
