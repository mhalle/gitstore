package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.File
import java.io.FileNotFoundException
import java.nio.file.Files
import kotlin.test.assertEquals
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
}
