package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class FileObjTest {

    @Test
    fun `fs writer binary mode`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val writer = fs.writer("output.bin")
            writer.write("chunk1".toByteArray())
            writer.write("chunk2".toByteArray())
            writer.close()

            assertNotNull(writer.fs)
            assertEquals("chunk1chunk2", writer.fs!!.readText("output.bin"))
        }
    }

    @Test
    fun `fs writer text mode`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val writer = fs.writer("output.txt", "w")
            writer.write("hello ")
            writer.write("world")
            writer.close()

            assertNotNull(writer.fs)
            assertEquals("hello world", writer.fs!!.readText("output.txt"))
        }
    }

    @Test
    fun `fs writer auto-close`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val writer = fs.writer("file.txt")
            writer.use { w ->
                w.write("data".toByteArray())
            }
            assertTrue(writer.closed)
            assertNotNull(writer.fs)
            assertEquals("data", writer.fs!!.readText("file.txt"))
        }
    }

    @Test
    fun `fs writer readonly throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertThrows<ReadOnlyError> {
                tagFs.writer("file.txt")
            }
        }
    }

    @Test
    fun `fs writer invalid mode throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<IllegalArgumentException> {
                fs.writer("file.txt", "r")
            }
        }
    }

    @Test
    fun `fs writer closed throws on write`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val writer = fs.writer("file.txt")
            writer.write("data".toByteArray())
            writer.close()
            assertThrows<IllegalStateException> {
                writer.write("more".toByteArray())
            }
        }
    }

    @Test
    fun `batch writer binary mode`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            val writer = batch.writer("output.bin")
            writer.write("part1".toByteArray())
            writer.write("part2".toByteArray())
            writer.close()
            val result = batch.commit()
            assertEquals("part1part2", result.readText("output.bin"))
        }
    }

    @Test
    fun `batch writer text mode`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.writer("log.txt", "w").use { w ->
                w.write("line 1\n")
                w.write("line 2\n")
            }
            val result = batch.commit()
            assertEquals("line 1\nline 2\n", result.readText("log.txt"))
        }
    }

    @Test
    fun `batch writer auto-close`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val batch = fs.batch()
            batch.writer("file.txt").use { w ->
                w.write("data".toByteArray())
            }
            val result = batch.commit()
            assertEquals("data", result.readText("file.txt"))
        }
    }
}
