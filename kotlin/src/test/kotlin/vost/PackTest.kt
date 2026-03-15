package vost

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class PackTest {

    @Test
    fun `pack returns count`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("b.txt", "bbb".toByteArray())
            val count = it.pack()
            assertTrue(count > 0, "expected packed objects, got $count")
        }
    }

    @Test
    fun `pack preserves data`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            fs = fs.write("b.txt", "world".toByteArray())
            it.pack()
            fs = it.branches["main"]
            assertEquals("hello", String(fs.read("a.txt")))
            assertEquals("world", String(fs.read("b.txt")))
        }
    }

    @Test
    fun `gc returns count`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            val count = it.gc()
            assertTrue(count > 0, "expected packed objects, got $count")
        }
    }

    @Test
    fun `gc preserves data`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.gc()
            fs = it.branches["main"]
            assertEquals("hello", String(fs.read("a.txt")))
        }
    }
}
