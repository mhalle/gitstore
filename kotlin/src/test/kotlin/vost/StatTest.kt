package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.FileNotFoundException
import kotlin.test.assertEquals
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
}
