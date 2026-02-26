package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.nio.file.Path
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CopyTest {

    @Test
    fun `copyIn single file`(@TempDir tempDir: Path) {
        val srcFile = tempDir.resolve("hello.txt").toFile()
        srcFile.writeText("hello world")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcFile.absolutePath), "")
            assertEquals("hello world", fs.readText("hello.txt"))
        }
    }

    @Test
    fun `copyIn directory`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("data").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")
        File(srcDir, "b.txt").writeText("bbb")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcDir.absolutePath), "")
            assertEquals("aaa", fs.readText("data/a.txt"))
            assertEquals("bbb", fs.readText("data/b.txt"))
        }
    }

    @Test
    fun `copyIn directory contents mode`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("data").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcDir.absolutePath + "/"), "dest")
            assertEquals("aaa", fs.readText("dest/a.txt"))
        }
    }

    @Test
    fun `copyIn with dest path`(@TempDir tempDir: Path) {
        val srcFile = tempDir.resolve("file.txt").toFile()
        srcFile.writeText("data")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcFile.absolutePath), "subdir")
            assertEquals("data", fs.readText("subdir/file.txt"))
        }
    }

    @Test
    fun `copyIn with delete`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("data").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            // First, put some files in the repo
            fs = fs.write("dest/a.txt", "old".toByteArray())
            fs = fs.write("dest/extra.txt", "extra".toByteArray())

            // Sync with delete
            fs = fs.copyIn(listOf(srcDir.absolutePath + "/"), "dest", delete = true)
            assertEquals("aaa", fs.readText("dest/a.txt"))
            assertFalse(fs.exists("dest/extra.txt"))
        }
    }

    @Test
    fun `copyOut single file`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("hello.txt", "hello".toByteArray())

            fs.copyOut(listOf("hello.txt"), destDir.absolutePath)

            val outFile = File(destDir, "hello.txt")
            assertTrue(outFile.exists())
            assertEquals("hello", outFile.readText())
        }
    }

    @Test
    fun `copyOut directory`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("data/a.txt", "aaa".toByteArray())
            fs = fs.write("data/b.txt", "bbb".toByteArray())

            fs.copyOut(listOf("data"), destDir.absolutePath)

            assertEquals("aaa", File(destDir, "data/a.txt").readText())
            assertEquals("bbb", File(destDir, "data/b.txt").readText())
        }
    }

    @Test
    fun `copyOut contents mode`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("data/a.txt", "aaa".toByteArray())

            fs.copyOut(listOf("data/"), destDir.absolutePath)

            assertEquals("aaa", File(destDir, "a.txt").readText())
        }
    }

    @Test
    fun `copyOut with delete`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()
        destDir.mkdirs()
        File(destDir, "extra.txt").writeText("should be deleted")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())

            fs.copyOut(listOf(""), destDir.absolutePath, delete = true)

            assertEquals("aaa", File(destDir, "a.txt").readText())
            assertFalse(File(destDir, "extra.txt").exists())
        }
    }

    @Test
    fun `syncIn`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("data").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dest/old.txt", "old".toByteArray())

            fs = fs.syncIn(srcDir.absolutePath, "dest")
            assertEquals("aaa", fs.readText("dest/a.txt"))
            assertFalse(fs.exists("dest/old.txt"))
        }
    }

    @Test
    fun `syncOut`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()
        destDir.mkdirs()
        File(destDir, "extra.txt").writeText("extra")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("data/a.txt", "aaa".toByteArray())

            fs.syncOut("data", destDir.absolutePath)

            assertEquals("aaa", File(destDir, "a.txt").readText())
            assertFalse(File(destDir, "extra.txt").exists())
        }
    }

    @Test
    fun `copyFromRef basic`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())
            src = src.write("b.txt", "bbb".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]
            dest = dest.write("other.txt", "other".toByteArray())

            // Copy everything from main into other at "copied/"
            dest = dest.copyFromRef(src, listOf(""), "copied")
            assertEquals("aaa", dest.readText("copied/a.txt"))
            assertEquals("bbb", dest.readText("copied/b.txt"))
            assertTrue(dest.exists("other.txt"))
        }
    }

    @Test
    fun `copyFromRef with delete`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]
            dest = dest.write("extra.txt", "extra".toByteArray())

            // Copy from main to other root with delete
            dest = dest.copyFromRef(src, listOf(""), "", delete = true)
            assertEquals("aaa", dest.readText("a.txt"))
            assertFalse(dest.exists("extra.txt"))
        }
    }

    @Test
    fun `copyFromRef single file`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())
            src = src.write("b.txt", "bbb".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]

            dest = dest.copyFromRef(src, listOf("a.txt"), "dest")
            assertEquals("aaa", dest.readText("dest/a.txt"))
        }
    }

    @Test
    fun `copyFromRef no-op when identical`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())

            it.branches["other"] = src
            val dest = it.branches["other"]

            val result = dest.copyFromRef(src)
            // Should be no-op since content is identical
            assertEquals(dest.commitHash, result.commitHash)
        }
    }

    @Test
    fun `rename file`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("old.txt", "data".toByteArray())

            fs = fs.rename("old.txt", "new.txt")
            assertFalse(fs.exists("old.txt"))
            assertEquals("data", fs.readText("new.txt"))
        }
    }

    @Test
    fun `rename directory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("dir/a.txt", "a".toByteArray())
            fs = fs.write("dir/b.txt", "b".toByteArray())

            fs = fs.rename("dir", "newdir")
            assertFalse(fs.exists("dir"))
            assertEquals("a", fs.readText("newdir/a.txt"))
            assertEquals("b", fs.readText("newdir/b.txt"))
        }
    }

    @Test
    fun `move file into directory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            fs = fs.write("dest/existing.txt", "existing".toByteArray())

            fs = fs.move(listOf("file.txt"), "dest")
            assertFalse(fs.exists("file.txt"))
            assertEquals("data", fs.readText("dest/file.txt"))
            assertEquals("existing", fs.readText("dest/existing.txt"))
        }
    }

    @Test
    fun `move multiple files into directory`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("b.txt", "bbb".toByteArray())
            fs = fs.write("dest/placeholder.txt", "p".toByteArray())

            fs = fs.move(listOf("a.txt", "b.txt"), "dest")
            assertFalse(fs.exists("a.txt"))
            assertFalse(fs.exists("b.txt"))
            assertEquals("aaa", fs.readText("dest/a.txt"))
            assertEquals("bbb", fs.readText("dest/b.txt"))
        }
    }

    @Test
    fun `copyFromRef copies between branches`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("file.txt", "source data".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]
            dest = dest.write("other.txt", "other".toByteArray())
            // Get fresh writable dest
            dest = it.branches["other"]

            dest = dest.copyFromRef(src, listOf("file.txt"), "")
            assertEquals("source data", dest.readText("file.txt"))
        }
    }
}
