package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class NotesTest {

    @Test
    fun `set and get note`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes.commits[hash] = "my note"
            assertEquals("my note", it.notes.commits[hash])
        }
    }

    @Test
    fun `get nonexistent note throws`() {
        val store = createStore()
        store.use {
            assertThrows<NoSuchElementException> {
                it.notes.commits["0000000000000000000000000000000000000000"]
            }
        }
    }

    @Test
    fun `contains check`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            assertFalse(hash in it.notes.commits)
            it.notes.commits[hash] = "note"
            assertTrue(hash in it.notes.commits)
        }
    }

    @Test
    fun `delete note`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes.commits[hash] = "note"
            assertTrue(hash in it.notes.commits)

            it.notes.commits.delete(hash)
            assertFalse(hash in it.notes.commits)
        }
    }

    @Test
    fun `delete nonexistent note throws`() {
        val store = createStore()
        store.use {
            assertThrows<NoSuchElementException> {
                it.notes.commits.delete("0000000000000000000000000000000000000000")
            }
        }
    }

    @Test
    fun `keys returns all note hashes`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val hash1 = fs.commitHash
            fs = fs.write("b.txt", "b".toByteArray())
            val hash2 = fs.commitHash

            it.notes.commits[hash1] = "note1"
            it.notes.commits[hash2] = "note2"

            val keys = it.notes.commits.keys().sorted()
            assertEquals(2, keys.size)
            assertTrue(keys.contains(hash1))
            assertTrue(keys.contains(hash2))
        }
    }

    @Test
    fun `size returns count`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val hash1 = fs.commitHash

            assertEquals(0, it.notes.commits.size())
            it.notes.commits[hash1] = "note"
            assertEquals(1, it.notes.commits.size())
        }
    }

    @Test
    fun `overwrite note`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes.commits[hash] = "v1"
            assertEquals("v1", it.notes.commits[hash])

            it.notes.commits[hash] = "v2"
            assertEquals("v2", it.notes.commits[hash])
        }
    }

    @Test
    fun `custom namespace`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes["reviews"][hash] = "approved"
            assertEquals("approved", it.notes["reviews"][hash])

            // Should not be in commits namespace
            assertFalse(hash in it.notes.commits)
        }
    }

    @Test
    fun `invalid hash throws`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalArgumentException> {
                it.notes.commits["not-a-hash"] = "note"
            }
        }
    }

    @Test
    fun `contains with invalid hash returns false`() {
        val store = createStore()
        store.use {
            assertFalse("not-a-hash" in it.notes.commits)
        }
    }

    @Test
    fun `notes batch writes`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val hash1 = fs.commitHash
            fs = fs.write("b.txt", "b".toByteArray())
            val hash2 = fs.commitHash

            it.notes.commits.batch().use { batch ->
                batch[hash1] = "note1"
                batch[hash2] = "note2"
            }

            assertEquals("note1", it.notes.commits[hash1])
            assertEquals("note2", it.notes.commits[hash2])
        }
    }

    @Test
    fun `notes batch delete`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes.commits[hash] = "note"

            it.notes.commits.batch().use { batch ->
                batch.delete(hash)
            }

            assertFalse(hash in it.notes.commits)
        }
    }

    @Test
    fun `notes batch mixed writes and deletes`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val hash1 = fs.commitHash
            fs = fs.write("b.txt", "b".toByteArray())
            val hash2 = fs.commitHash

            it.notes.commits[hash1] = "old note"

            it.notes.commits.batch().use { batch ->
                batch.delete(hash1)
                batch[hash2] = "new note"
            }

            assertFalse(hash1 in it.notes.commits)
            assertEquals("new note", it.notes.commits[hash2])
        }
    }

    @Test
    fun `for current branch`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())

            it.notes.commits.setForCurrentBranch("current note")
            assertEquals("current note", it.notes.commits.getForCurrentBranch())
        }
    }

    @Test
    fun `empty note text roundtrip`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash
            it.notes.commits[hash] = ""
            assertEquals("", it.notes.commits[hash])
        }
    }

    @Test
    fun `unicode note text roundtrip`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash
            val text = "LGTM \u2705\n\u65E5\u672C\u8A9E\u30C6\u30B9\u30C8"
            it.notes.commits[hash] = text
            assertEquals(text, it.notes.commits[hash])
        }
    }

    @Test
    fun `multiline note text roundtrip`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash
            val text = "line1\nline2\nline3"
            it.notes.commits[hash] = text
            assertEquals(text, it.notes.commits[hash])
        }
    }

    @Test
    fun `notes batch overwrite last-wins`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            it.notes.commits.batch().use { batch ->
                batch[hash] = "first"
                batch[hash] = "second"
            }
            assertEquals("second", it.notes.commits[hash])
        }
    }

    @Test
    fun `notes batch noop no commit`() {
        val store = createStore()
        store.use {
            // Empty batch should not throw
            it.notes.commits.batch().use { }
            assertEquals(0, it.notes.commits.size())
        }
    }

    @Test
    fun `notes batch closed rejects commit`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            val batch = it.notes.commits.batch()
            batch[hash] = "note"
            batch.close()
            assertThrows<IllegalStateException> {
                batch.commit()
            }
        }
    }

    @Test
    fun `notes batch set then delete same hash`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash

            // First, write the note to the store
            it.notes.commits[hash] = "original"
            assertTrue(hash in it.notes.commits)

            // Now batch: set then delete should remove it
            it.notes.commits.batch().use { batch ->
                batch[hash] = "updated"
                batch.delete(hash)
            }
            assertFalse(hash in it.notes.commits)
        }
    }

    @Test
    fun `notes batch delete then set same hash`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val hash = fs.commitHash
            it.notes.commits[hash] = "original"

            it.notes.commits.batch().use { batch ->
                batch.delete(hash)
                batch[hash] = "restored"
            }
            assertEquals("restored", it.notes.commits[hash])
        }
    }

    @Test
    fun `invalid target too short throws`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalArgumentException> {
                it.notes.commits["abcd"] = "note"
            }
        }
    }

    @Test
    fun `invalid hash non-hex throws`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalArgumentException> {
                it.notes.commits["zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"] = "note"
            }
        }
    }

    // ── Ref-based target resolution ─────────────────────────────────

    @Test
    fun `set and get by branch name`() {
        val store = createStore()
        store.use {
            it.notes.commits["main"] = "note for main"
            assertEquals("note for main", it.notes.commits["main"])
        }
    }

    @Test
    fun `set and get by tag name`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1.0"] = fs
            it.notes.commits["v1.0"] = "note for tag"
            assertEquals("note for tag", it.notes.commits["v1.0"])
        }
    }

    @Test
    fun `ref and hash access same note`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.notes.commits["main"] = "via ref"
            assertEquals("via ref", it.notes.commits[fs.commitHash])
        }
    }

    @Test
    fun `contains by ref`() {
        val store = createStore()
        store.use {
            assertFalse("main" in it.notes.commits)
            it.notes.commits["main"] = "note"
            assertTrue("main" in it.notes.commits)
        }
    }

    @Test
    fun `delete by ref`() {
        val store = createStore()
        store.use {
            it.notes.commits["main"] = "note"
            assertTrue("main" in it.notes.commits)
            it.notes.commits.delete("main")
            assertFalse("main" in it.notes.commits)
        }
    }

    @Test
    fun `batch with ref targets`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.branches["dev"] = fs
            // Advance main so the two branches have different tips
            fs.write("a.txt", "a".toByteArray())

            it.notes.commits.batch().use { batch ->
                batch["main"] = "note for main"
                batch["dev"] = "note for dev"
            }

            assertEquals("note for main", it.notes.commits["main"])
            assertEquals("note for dev", it.notes.commits["dev"])
        }
    }

    @Test
    fun `batch delete by ref`() {
        val store = createStore()
        store.use {
            it.notes.commits["main"] = "note"
            it.notes.commits.batch().use { batch ->
                batch.delete("main")
            }
            assertFalse("main" in it.notes.commits)
        }
    }

    @Test
    fun `nonexistent ref raises`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalArgumentException> {
                it.notes.commits["nonexistent"] = "note"
            }
        }
    }

    // -- FS snapshot as target ------------------------------------------------

    @Test
    fun `set and get by FS snapshot`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val ns = it.notes.commits
            ns[fs] = "note for snapshot"
            assertEquals("note for snapshot", ns[fs])
        }
    }

    @Test
    fun `FS and hash access same note`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val ns = it.notes.commits
            ns[fs] = "via snapshot"
            assertEquals("via snapshot", ns[fs.commitHash])
        }
    }

    @Test
    fun `contains by FS`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val ns = it.notes.commits
            assertFalse(fs in ns)
            ns[fs] = "note"
            assertTrue(fs in ns)
        }
    }

    @Test
    fun `delete by FS`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val ns = it.notes.commits
            ns[fs] = "note"
            ns.delete(fs)
            assertFalse(fs in ns)
        }
    }

    @Test
    fun `batch with FS targets`() {
        val store = createStore()
        store.use {
            val fs1 = it.branches["main"]
            val fs2 = fs1.write("a.txt", "a".toByteArray())
            it.notes.commits.batch().use { b ->
                b[fs1] = "note for fs1"
                b[fs2] = "note for fs2"
            }
            assertEquals("note for fs1", it.notes.commits[fs1])
            assertEquals("note for fs2", it.notes.commits[fs2])
        }
    }

    @Test
    fun `batch delete by FS`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val ns = it.notes.commits
            ns[fs] = "note"
            ns.batch().use { b -> b.delete(fs) }
            assertFalse(fs in ns)
        }
    }
}
