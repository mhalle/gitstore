package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.FileNotFoundException
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class FsReadTest {

    @Test
    fun `read and write round-trip`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("hello.txt", "Hello, World!".toByteArray())
            val data = fs.read("hello.txt")
            assertEquals("Hello, World!", String(data))
        }
    }

    @Test
    fun `readText convenience`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("msg.txt", "Kotlin".toByteArray())
            assertEquals("Kotlin", fs.readText("msg.txt"))
        }
    }

    @Test
    fun `read nonexistent file throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<FileNotFoundException> {
                fs.read("nonexistent.txt")
            }
        }
    }

    @Test
    fun `read directory throws IsADirectoryError`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/file.txt", "content".toByteArray())
            assertThrows<IsADirectoryError> {
                fs.read("dir")
            }
        }
    }

    @Test
    fun `read with offset and size`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("data.txt", "Hello, World!".toByteArray())
            val partial = fs.read("data.txt", offset = 7, size = 5)
            assertEquals("World", String(partial))
        }
    }

    @Test
    fun `read with offset only`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("data.txt", "Hello, World!".toByteArray())
            val data = fs.read("data.txt", offset = 7)
            assertEquals("World!", String(data))
        }
    }

    @Test
    fun `ls returns entry names`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("b.txt", "b".toByteArray())
            val names = fs.ls()
            assertEquals(listOf("a.txt", "b.txt"), names.sorted())
        }
    }

    @Test
    fun `ls subdirectory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())
            val names = fs.ls("dir")
            assertEquals(listOf("a.txt", "b.txt"), names.sorted())
        }
    }

    @Test
    fun `ls on file throws`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            assertThrows<NotADirectoryError> {
                fs.ls("file.txt")
            }
        }
    }

    @Test
    fun `exists returns true for files and dirs`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/file.txt", "data".toByteArray())
            assertTrue(fs.exists("dir/file.txt"))
            assertTrue(fs.exists("dir"))
            assertFalse(fs.exists("nonexistent"))
        }
    }

    @Test
    fun `isDir distinguishes files from dirs`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/file.txt", "data".toByteArray())
            assertTrue(fs.isDir("dir"))
            assertFalse(fs.isDir("dir/file.txt"))
            assertFalse(fs.isDir("nonexistent"))
        }
    }

    @Test
    fun `fileType returns correct types`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            fs = fs.write("exe.sh", "#!/bin/bash".toByteArray(), mode = FileType.EXECUTABLE)
            fs = fs.writeSymlink("link", "file.txt")

            assertEquals(FileType.BLOB, fs.fileType("file.txt"))
            assertEquals(FileType.EXECUTABLE, fs.fileType("exe.sh"))
            assertEquals(FileType.LINK, fs.fileType("link"))
        }
    }

    @Test
    fun `fileType on nonexistent throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<FileNotFoundException> {
                fs.fileType("nonexistent")
            }
        }
    }

    @Test
    fun `size returns byte count`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val data = "Hello, World!"
            fs = fs.write("file.txt", data.toByteArray())
            assertEquals(data.length.toLong(), fs.size("file.txt"))
        }
    }

    @Test
    fun `objectHash returns 40-char hex SHA`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "content".toByteArray())
            val hash = fs.objectHash("file.txt")
            assertEquals(40, hash.length)
            assertTrue(hash.all { c -> c in '0'..'9' || c in 'a'..'f' })
        }
    }

    @Test
    fun `commitHash returns 40-char hex SHA`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(40, fs.commitHash.length)
        }
    }

    @Test
    fun `treeHash returns 40-char hex SHA`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(40, fs.treeHash.length)
        }
    }

    @Test
    fun `refName and writable`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals("main", fs.refName)
            assertTrue(fs.writable)
        }
    }

    @Test
    fun `message property`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertTrue(fs.message.contains("Initialize"))
        }
    }

    @Test
    fun `authorName and authorEmail`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals("vost", fs.authorName)
            assertEquals("vost@localhost", fs.authorEmail)
        }
    }

    @Test
    fun `walk returns directory structure`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())
            fs = fs.write("dir/sub/c.txt", "c".toByteArray())

            val entries = fs.walk()
            assertTrue(entries.isNotEmpty())

            // Root entry
            val root = entries[0]
            assertEquals("", root.dirpath)
            assertTrue("dir" in root.dirnames)
            assertTrue(root.files.any { it.name == "a.txt" })
        }
    }

    @Test
    fun `walk subdirectory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/sub/b.txt", "b".toByteArray())

            val entries = fs.walk("dir")
            assertTrue(entries.isNotEmpty())
            assertEquals("dir", entries[0].dirpath)
        }
    }

    @Test
    fun `listdir returns WalkEntry objects`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())

            val entries = fs.listdir()
            assertTrue(entries.any { it.name == "a.txt" })
            assertTrue(entries.any { it.name == "dir" && it.mode == GIT_FILEMODE_TREE })
        }
    }

    @Test
    fun `readByHash reads blob directly`() {
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
            val data = fs.readByHash(hash, offset = 6, size = 5)
            assertEquals("World", String(data))
        }
    }

    @Test
    fun `readlink returns symlink target`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.writeSymlink("link", "target.txt")
            assertEquals("target.txt", fs.readlink("link"))
        }
    }

    @Test
    fun `readlink on non-symlink throws`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            assertThrows<IllegalStateException> {
                fs.readlink("file.txt")
            }
        }
    }

    @Test
    fun `write returns new Fs with different commit`() {
        val store = createStore()
        store.use {
            val fs1 = it.branches["main"]
            val fs2 = fs1.write("file.txt", "data".toByteArray())
            assertTrue(fs1.commitHash != fs2.commitHash)
            assertEquals("data", String(fs2.read("file.txt")))
        }
    }

    @Test
    fun `nested directory creation`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a/b/c/d.txt", "deep".toByteArray())
            assertEquals("deep", fs.readText("a/b/c/d.txt"))
            assertTrue(fs.isDir("a"))
            assertTrue(fs.isDir("a/b"))
            assertTrue(fs.isDir("a/b/c"))
        }
    }

    @Test
    fun `empty initial repo ls returns empty`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(emptyList(), fs.ls())
        }
    }

    @Test
    fun `toString includes commit hash prefix`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            val str = fs.toString()
            assertTrue(str.startsWith("Fs("))
            assertTrue("main" in str)
        }
    }

    // ── Root-path handling ──────────────────────────────────────────────

    @Test
    fun `exists returns true for root paths`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertTrue(fs.exists(""))
            assertTrue(fs.exists("/"))
        }
    }

    @Test
    fun `isDir returns true for root`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertTrue(fs.isDir(""))
        }
    }

    @Test
    fun `fileType returns TREE for root`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(FileType.TREE, fs.fileType(""))
        }
    }

    @Test
    fun `size on root throws IsADirectoryError`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<IsADirectoryError> {
                fs.size("")
            }
        }
    }

    @Test
    fun `objectHash on root returns treeHash`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertEquals(fs.treeHash, fs.objectHash(""))
        }
    }

    // ── Ranged read overflow ────────────────────────────────────────────

    @Test
    fun `read with large offset and size does not overflow`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "hello".toByteArray())
            val data = fs.read("file.txt", offset = Int.MAX_VALUE - 10, size = 100)
            assertEquals(0, data.size)
        }
    }

    @Test
    fun `readByHash with large offset and size does not overflow`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "hello".toByteArray())
            val hash = fs.objectHash("file.txt")
            val data = fs.readByHash(hash, offset = Int.MAX_VALUE - 10, size = 100)
            assertEquals(0, data.size)
        }
    }
}
