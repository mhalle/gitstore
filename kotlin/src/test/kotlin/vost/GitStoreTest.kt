package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.File
import java.io.FileNotFoundException
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class GitStoreTest {

    @Test
    fun `open creates new bare repo with main branch`() {
        val store = createStore()
        store.use {
            assertTrue("main" in it.branches)
            assertEquals(listOf("main"), it.branches.list())
        }
    }

    @Test
    fun `open with create=false throws on missing repo`() {
        val tmpDir = Files.createTempDirectory("vost-test-").toFile()
        tmpDir.deleteOnExit()
        val path = File(tmpDir, "nonexistent.git").absolutePath
        assertThrows<FileNotFoundException> {
            GitStore.open(path, create = false)
        }
    }

    @Test
    fun `open existing repo`() {
        val tmpDir = Files.createTempDirectory("vost-test-").toFile()
        tmpDir.deleteOnExit()
        val path = File(tmpDir, "test.git").absolutePath

        // Create
        val store1 = GitStore.open(path)
        store1.close()

        // Reopen
        val store2 = GitStore.open(path)
        store2.use {
            assertTrue("main" in it.branches)
        }
    }

    @Test
    fun `open with no initial branch`() {
        val store = createStore(branch = null)
        store.use {
            assertEquals(0, it.branches.size)
        }
    }

    @Test
    fun `branches list and contains`() {
        val store = createStore()
        store.use {
            assertTrue(it.branches.contains("main"))
            assertTrue(!it.branches.contains("nonexistent"))
            assertEquals(1, it.branches.size)
        }
    }

    @Test
    fun `tags are initially empty`() {
        val store = createStore()
        store.use {
            assertEquals(0, it.tags.size)
            assertTrue(!it.tags.contains("v1"))
        }
    }

    @Test
    fun `current branch`() {
        val store = createStore()
        store.use {
            assertEquals("main", it.branches.currentName)
            val fs = it.branches.current
            assertNotNull(fs)
            assertEquals("main", fs.refName)
        }
    }

    @Test
    fun `set current branch`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.branches["dev"] = fs
            it.branches.setCurrent("dev")
            assertEquals("dev", it.branches.currentName)
        }
    }

    @Test
    fun `create and delete branch`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.branches["feature"] = fs
            assertTrue("feature" in it.branches)
            assertEquals(2, it.branches.size)

            it.branches.delete("feature")
            assertTrue("feature" !in it.branches)
            assertEquals(1, it.branches.size)
        }
    }

    @Test
    fun `create and access tag`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            assertTrue("v1" in it.tags)

            val tagFs = it.tags["v1"]
            assertEquals(fs.commitHash, tagFs.commitHash)
            assertTrue(!tagFs.writable)
        }
    }

    @Test
    fun `tag already exists throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            assertThrows<IllegalStateException> {
                it.tags["v1"] = fs
            }
        }
    }

    @Test
    fun `set and get returns writable fs`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val newFs = it.branches.setAndGet("feature", fs)
            assertEquals("feature", newFs.refName)
            assertTrue(newFs.writable)
        }
    }

    @Test
    fun `nonexistent branch throws`() {
        val store = createStore()
        store.use {
            assertThrows<NoSuchElementException> {
                it.branches["nonexistent"]
            }
        }
    }

    @Test
    fun `tags currentName throws`() {
        val store = createStore()
        store.use {
            assertThrows<IllegalStateException> {
                it.tags.currentName
            }
        }
    }

    @Test
    fun `toString includes repo path`() {
        val store = createStore()
        store.use {
            assertTrue(it.toString().startsWith("GitStore("))
        }
    }

    @Test
    fun `delete nonexistent branch throws`() {
        val store = createStore()
        store.use {
            assertThrows<NoSuchElementException> {
                it.branches.delete("nonexistent")
            }
        }
    }

    @Test
    fun `get nonexistent tag throws`() {
        val store = createStore()
        store.use {
            assertThrows<NoSuchElementException> {
                it.tags["nonexistent"]
            }
        }
    }

    @Test
    fun `delete tag`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            assertTrue("v1" in it.tags)
            it.tags.delete("v1")
            assertFalse("v1" in it.tags)
        }
    }

    @Test
    fun `tag is not writable`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertFalse(tagFs.writable)
            assertThrows<PermissionError> {
                tagFs.write("file.txt", "data".toByteArray())
            }
        }
    }

    @Test
    fun `fs refName matches branch name`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals("main", fs.refName)
        }
    }

    @Test
    fun `fs writable is true for branches`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertTrue(fs.writable)
        }
    }

    @Test
    fun `commitHash format is 40-char hex`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(40, fs.commitHash.length)
            assertTrue(fs.commitHash.all { c -> c in '0'..'9' || c in 'a'..'f' })
        }
    }

    @Test
    fun `branches size tracks changes`() {
        val store = createStore()
        store.use {
            assertEquals(1, it.branches.size)
            val fs = it.branches["main"]
            it.branches["dev"] = fs
            assertEquals(2, it.branches.size)
            it.branches.delete("dev")
            assertEquals(1, it.branches.size)
        }
    }

    @Test
    fun `current with no branches returns null`() {
        val store = createStore(branch = null)
        store.use {
            assertNull(it.branches.current)
        }
    }

    @Test
    fun `tags list returns all tag names`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            it.tags["v2"] = fs
            val names = it.tags.list().sorted()
            assertEquals(listOf("v1", "v2"), names)
        }
    }
}
