package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class HistoryTest {

    @Test
    fun `parent of initial commit is null`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertNull(fs.parent)
        }
    }

    @Test
    fun `parent returns previous snapshot`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val initial = fs.commitHash
            fs = fs.write("file.txt", "data".toByteArray())
            val parent = fs.parent
            assertNotNull(parent)
            assertEquals(initial, parent.commitHash)
        }
    }

    @Test
    fun `back(0) returns self`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val back0 = fs.back(0)
            assertEquals(fs.commitHash, back0.commitHash)
        }
    }

    @Test
    fun `back(1) returns parent`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val initial = fs.commitHash
            fs = fs.write("file.txt", "data".toByteArray())
            val back1 = fs.back(1)
            assertEquals(initial, back1.commitHash)
        }
    }

    @Test
    fun `back with n too large throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<IllegalArgumentException> {
                fs.back(10)
            }
        }
    }

    @Test
    fun `back with negative n throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<IllegalArgumentException> {
                fs.back(-1)
            }
        }
    }

    @Test
    fun `log returns commit history`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())

            val history = fs.log()
            // Should have at least 3 commits: init + 2 writes
            assertTrue(history.size >= 3)
        }
    }

    @Test
    fun `log with path filter`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())
            fs = fs.write("a.txt", "a2".toByteArray())

            val aHistory = fs.log("a.txt")
            // Should have 2 commits that changed a.txt
            assertEquals(2, aHistory.size)
        }
    }

    @Test
    fun `undo moves branch back`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val beforeB = fs.commitHash
            fs = fs.write("b.txt", "b".toByteArray())

            // Undo should move back to before b.txt was written
            val undone = fs.undo()
            assertEquals(beforeB, undone.commitHash)
            assertTrue(undone.exists("a.txt"))
            assertNull(undone.changes) // undo doesn't set changes
        }
    }

    @Test
    fun `undo multiple steps`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val initial = fs.commitHash
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())

            val undone = fs.undo(2)
            assertEquals(initial, undone.commitHash)
        }
    }

    @Test
    fun `undo on readonly throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertThrows<ReadOnlyError> {
                tagFs.undo()
            }
        }
    }

    @Test
    fun `undo with too many steps throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<IllegalArgumentException> {
                fs.undo(5)
            }
        }
    }

    @Test
    fun `undo with stale snapshot throws`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            val stale = fs
            fs.write("b.txt", "b".toByteArray()) // advances branch

            assertThrows<StaleSnapshotError> {
                stale.undo()
            }
        }
    }

    @Test
    fun `redo after undo restores state`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val afterWrite = fs.commitHash

            // Undo
            fs = fs.undo()
            assertTrue(!fs.exists("file.txt"))

            // Redo
            fs = fs.redo()
            assertEquals(afterWrite, fs.commitHash)
            assertEquals("data", fs.readText("file.txt"))
        }
    }

    @Test
    fun `redo on readonly throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertThrows<ReadOnlyError> {
                tagFs.redo()
            }
        }
    }

    @Test
    fun `reflog records entries`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())

            val entries = it.branches.reflog("main")
            assertTrue(entries.isNotEmpty())
            assertTrue(entries[0].message.isNotEmpty())
            assertEquals(40, entries[0].newSha.length)
        }
    }

    @Test
    fun `reflog on tags throws`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalStateException> {
                it.tags.reflog("v1")
            }
        }
    }
}
