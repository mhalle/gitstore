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
    fun `invalid hash too short throws`() {
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
}
