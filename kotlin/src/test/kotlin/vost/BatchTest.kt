package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.FileNotFoundException
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BatchTest {

    @Test
    fun `batch write and commit`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.write("a.txt", "a".toByteArray())
            batch.write("b.txt", "b".toByteArray())
            val result = batch.commit()
            assertEquals("a", result.readText("a.txt"))
            assertEquals("b", result.readText("b.txt"))
        }
    }

    @Test
    fun `batch result is set after commit`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            assertNull(batch.result)
            batch.write("file.txt", "data".toByteArray())
            batch.commit()
            assertNotNull(batch.result)
        }
    }

    @Test
    fun `batch auto-close commits`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.write("file.txt", "data".toByteArray())
            batch.close()
            assertNotNull(batch.result)
            assertEquals("data", batch.result!!.readText("file.txt"))
        }
    }

    @Test
    fun `batch use block auto-close`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            var resultFs: Fs? = null
            fs.batch().use { batch ->
                batch.write("file.txt", "data".toByteArray())
                resultFs = null // will be set after close
            }
            // Re-read from the branch
            val newFs = it.branches["main"]
            assertEquals("data", newFs.readText("file.txt"))
        }
    }

    @Test
    fun `batch writeText`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.writeText("msg.txt", "hello")
            val result = batch.commit()
            assertEquals("hello", result.readText("msg.txt"))
        }
    }

    @Test
    fun `batch writeSymlink`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.writeSymlink("link", "target.txt")
            val result = batch.commit()
            assertEquals(FileType.LINK, result.fileType("link"))
            assertEquals("target.txt", result.readlink("link"))
        }
    }

    @Test
    fun `batch remove`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())

            val batch = fs.batch()
            batch.remove("a.txt")
            val result = batch.commit()
            assertFalse(result.exists("a.txt"))
            assertTrue(result.exists("b.txt"))
        }
    }

    @Test
    fun `batch remove nonexistent throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            assertThrows<FileNotFoundException> {
                batch.remove("nonexistent.txt")
            }
        }
    }

    @Test
    fun `batch remove directory throws`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/file.txt", "data".toByteArray())

            val batch = fs.batch()
            assertThrows<IsADirectoryException> {
                batch.remove("dir")
            }
        }
    }

    @Test
    fun `batch empty commit returns same fs`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            val result = batch.commit()
            assertEquals(fs.commitHash, result.commitHash)
        }
    }

    @Test
    fun `batch closed after commit`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.write("file.txt", "data".toByteArray())
            batch.commit()
            assertThrows<IllegalStateException> {
                batch.write("another.txt", "data".toByteArray())
            }
        }
    }

    @Test
    fun `batch write then remove same path`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "original".toByteArray())

            val batch = fs.batch()
            batch.write("file.txt", "updated".toByteArray())
            batch.remove("file.txt")
            val result = batch.commit()
            assertFalse(result.exists("file.txt"))
        }
    }

    @Test
    fun `batch remove then write same path`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "original".toByteArray())

            val batch = fs.batch()
            batch.remove("file.txt")
            batch.write("file.txt", "new content".toByteArray())
            val result = batch.commit()
            assertEquals("new content", result.readText("file.txt"))
        }
    }

    @Test
    fun `batch with custom message`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch(message = "custom message")
            batch.write("file.txt", "data".toByteArray())
            val result = batch.commit()
            assertEquals("custom message", result.message)
        }
    }

    @Test
    fun `batch on readonly throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertThrows<ReadOnlyError> {
                tagFs.batch()
            }
        }
    }

    @Test
    fun `multiple writes to same path keeps last`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.write("file.txt", "v1".toByteArray())
            batch.write("file.txt", "v2".toByteArray())
            batch.write("file.txt", "v3".toByteArray())
            val result = batch.commit()
            assertEquals("v3", result.readText("file.txt"))
        }
    }
}
