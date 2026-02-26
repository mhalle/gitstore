package vost

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FsGlobTest {

    @Test
    fun `glob matches files by pattern`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())
            fs = fs.write("c.py", "c".toByteArray())

            val matches = fs.glob("*.txt")
            assertEquals(listOf("a.txt", "b.txt"), matches)
        }
    }

    @Test
    fun `glob matches nested files`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())
            fs = fs.write("dir/c.py", "c".toByteArray())

            val matches = fs.glob("dir/*.txt")
            assertEquals(listOf("dir/a.txt", "dir/b.txt"), matches)
        }
    }

    @Test
    fun `glob double star matches across directories`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())
            fs = fs.write("dir/sub/c.txt", "c".toByteArray())

            val matches = fs.glob("**/*.txt")
            assertEquals(listOf("a.txt", "dir/b.txt", "dir/sub/c.txt"), matches)
        }
    }

    @Test
    fun `glob returns empty for no match`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())

            val matches = fs.glob("*.py")
            assertTrue(matches.isEmpty())
        }
    }

    @Test
    fun `glob matches exact path`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("specific.txt", "data".toByteArray())

            val matches = fs.glob("specific.txt")
            assertEquals(listOf("specific.txt"), matches)
        }
    }

    @Test
    fun `glob skips dotfiles`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write(".hidden", "data".toByteArray())
            fs = fs.write("visible.txt", "data".toByteArray())

            val matches = fs.glob("*")
            assertEquals(listOf("visible.txt"), matches)
        }
    }

    @Test
    fun `glob explicit dot matches dotfiles`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write(".hidden", "data".toByteArray())
            fs = fs.write(".config", "data".toByteArray())
            fs = fs.write("visible.txt", "data".toByteArray())

            val matches = fs.glob(".*")
            assertEquals(listOf(".config", ".hidden"), matches)
        }
    }

    @Test
    fun `glob question mark wildcard`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a1.txt", "a".toByteArray())
            fs = fs.write("a2.txt", "b".toByteArray())
            fs = fs.write("ab.txt", "c".toByteArray())

            val matches = fs.glob("a?.txt")
            assertEquals(listOf("a1.txt", "a2.txt", "ab.txt"), matches)
        }
    }

    @Test
    fun `iglob returns unsorted results`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("b.txt", "b".toByteArray())
            fs = fs.write("a.txt", "a".toByteArray())

            val matches = fs.iglob("*.txt")
            assertEquals(2, matches.size)
            assertTrue(matches.containsAll(listOf("a.txt", "b.txt")))
        }
    }

    @Test
    fun `glob empty pattern returns empty`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())

            val matches = fs.glob("")
            assertTrue(matches.isEmpty())
        }
    }

    @Test
    fun `glob double star at end`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/sub/b.txt", "b".toByteArray())

            val matches = fs.glob("dir/**")
            // ** at end matches all non-dot entries at the level and below
            assertTrue(matches.contains("dir/a.txt"))
            assertTrue(matches.contains("dir/sub"))
            assertTrue(matches.contains("dir/sub/b.txt"))
        }
    }
}
