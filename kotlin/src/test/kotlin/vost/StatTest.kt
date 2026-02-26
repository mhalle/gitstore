package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.FileNotFoundException
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class StatTest {

    @Test
    fun `stat root returns tree info`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())

            val st = fs.stat()
            assertEquals(GIT_FILEMODE_TREE, st.mode)
            assertEquals(FileType.TREE, st.fileType)
            assertEquals(0, st.size)
            assertEquals(40, st.hash.length)
            // nlink = 2 + number of subdirectories (1 dir)
            assertEquals(3, st.nlink)
            assertTrue(st.mtime > 0)
        }
    }

    @Test
    fun `stat root with null path`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val st = fs.stat(null)
            assertEquals(FileType.TREE, st.fileType)
        }
    }

    @Test
    fun `stat file returns blob info`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val data = "Hello, World!"
            fs = fs.write("file.txt", data.toByteArray())

            val st = fs.stat("file.txt")
            assertEquals(GIT_FILEMODE_BLOB, st.mode)
            assertEquals(FileType.BLOB, st.fileType)
            assertEquals(data.length.toLong(), st.size)
            assertEquals(40, st.hash.length)
            assertEquals(1, st.nlink)
            assertTrue(st.mtime > 0)
        }
    }

    @Test
    fun `stat executable file`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("script.sh", "#!/bin/bash".toByteArray(), mode = FileType.EXECUTABLE)

            val st = fs.stat("script.sh")
            assertEquals(GIT_FILEMODE_BLOB_EXECUTABLE, st.mode)
            assertEquals(FileType.EXECUTABLE, st.fileType)
            assertEquals(1, st.nlink)
        }
    }

    @Test
    fun `stat symlink`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.writeSymlink("link", "target.txt")

            val st = fs.stat("link")
            assertEquals(GIT_FILEMODE_LINK, st.mode)
            assertEquals(FileType.LINK, st.fileType)
            assertEquals(1, st.nlink)
        }
    }

    @Test
    fun `stat directory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/sub/b.txt", "b".toByteArray())

            val st = fs.stat("dir")
            assertEquals(GIT_FILEMODE_TREE, st.mode)
            assertEquals(FileType.TREE, st.fileType)
            assertEquals(0, st.size)
            // nlink = 2 + 1 subdirectory
            assertEquals(3, st.nlink)
        }
    }

    @Test
    fun `stat nonexistent throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<FileNotFoundException> {
                fs.stat("nonexistent")
            }
        }
    }

    @Test
    fun `stat hash matches objectHash`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "content".toByteArray())

            val st = fs.stat("file.txt")
            val hash = fs.objectHash("file.txt")
            assertEquals(hash, st.hash)
        }
    }

    @Test
    fun `read with offset and size`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "Hello World".toByteArray())

            val partial = fs.read("file.txt", offset = 6, size = 5)
            assertEquals("World", String(partial))
        }
    }

    @Test
    fun `read with offset beyond end returns empty`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "short".toByteArray())

            val result = fs.read("file.txt", offset = 100)
            assertEquals(0, result.size)
        }
    }

    @Test
    fun `readByHash returns blob content`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "content".toByteArray())

            val hash = fs.objectHash("file.txt")
            val data = fs.readByHash(hash)
            assertEquals("content", String(data))
        }
    }

    @Test
    fun `readByHash with offset and size`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "Hello World".toByteArray())

            val hash = fs.objectHash("file.txt")
            val partial = fs.readByHash(hash, offset = 6, size = 5)
            assertEquals("World", String(partial))
        }
    }

    @Test
    fun `stat size matches content length`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val content = "Hello, World! This is a longer string."
            fs = fs.write("file.txt", content.toByteArray())
            val st = fs.stat("file.txt")
            assertEquals(content.length.toLong(), st.size)
        }
    }

    @Test
    fun `stat symlink size is target length`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.writeSymlink("link", "target.txt")
            val st = fs.stat("link")
            assertEquals("target.txt".length.toLong(), st.size)
        }
    }

    @Test
    fun `stat nlink for leaf directory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())
            // dir has no subdirs -> nlink = 2
            val st = fs.stat("dir")
            assertEquals(2, st.nlink)
        }
    }

    @Test
    fun `stat mtime is consistent across calls`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val st1 = fs.stat("file.txt")
            val st2 = fs.stat("file.txt")
            assertEquals(st1.mtime, st2.mtime)
        }
    }

    @Test
    fun `treeHash format is 40 hex`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            assertEquals(40, fs.treeHash.length)
            assertTrue(fs.treeHash.all { c -> c in '0'..'9' || c in 'a'..'f' })
        }
    }

    @Test
    fun `treeHash changes on write`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "v1".toByteArray())
            val hash1 = fs.treeHash
            fs = fs.write("file.txt", "v2".toByteArray())
            val hash2 = fs.treeHash
            assertNotEquals(hash1, hash2)
        }
    }

    @Test
    fun `read range middle of file`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "abcdefghij".toByteArray())
            val result = fs.read("file.txt", offset = 3, size = 4)
            assertEquals("defg", String(result))
        }
    }

    @Test
    fun `read range size beyond end is clamped`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "short".toByteArray())
            val result = fs.read("file.txt", offset = 2, size = 100)
            assertEquals("ort", String(result))
        }
    }

    @Test
    fun `read range zero size returns empty`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            val result = fs.read("file.txt", offset = 0, size = 0)
            assertEquals(0, result.size)
        }
    }

    @Test
    fun `readByHash roundtrip`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "content".toByteArray())
            val hash = fs.objectHash("file.txt")
            val data = fs.readByHash(hash)
            assertEquals("content", String(data))
        }
    }
}
