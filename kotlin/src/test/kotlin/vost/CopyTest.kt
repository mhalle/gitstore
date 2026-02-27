package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.nio.file.Path
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
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

    // ── move edge cases ──

    @Test
    fun `move preserves other files`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("other.txt", "other".toByteArray())
            fs = fs.write("dest/placeholder.txt", "p".toByteArray())
            fs = fs.move(listOf("a.txt"), "dest")
            assertFalse(fs.exists("a.txt"))
            assertEquals("aaa", fs.readText("dest/a.txt"))
            assertEquals("other", fs.readText("other.txt"))
        }
    }

    @Test
    fun `move into directory with trailing slash`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            fs = fs.write("dest/placeholder.txt", "p".toByteArray())
            fs = fs.move(listOf("file.txt"), "dest/")
            assertFalse(fs.exists("file.txt"))
            assertEquals("data", fs.readText("dest/file.txt"))
        }
    }

    @Test
    fun `move is single atomic commit`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("b.txt", "bbb".toByteArray())
            val hashBefore = fs.commitHash
            fs = fs.move(listOf("a.txt"), "c.txt")
            // Exactly one new commit
            assertNotEquals(hashBefore, fs.commitHash)
        }
    }

    @Test
    fun `move nonexistent source throws`() {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<java.io.FileNotFoundException> {
                fs.move(listOf("ghost.txt"), "dest.txt")
            }
        }
    }

    @Test
    fun `move on readonly tag throws`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("file.txt", "data".toByteArray())
            it.tags["v1"] = fs
            val tagFs = it.tags["v1"]
            assertThrows<PermissionError> {
                tagFs.move(listOf("file.txt"), "other.txt")
            }
        }
    }

    @Test
    fun `move with custom message`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "data".toByteArray())
            fs = fs.move(listOf("a.txt"), "b.txt", message = "moved file")
            assertEquals("moved file", fs.message)
        }
    }

    @Test
    fun `rename preserves content`() {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            val data = byteArrayOf(0x00, 0xFF.toByte(), 0x42)
            fs = fs.write("binary.dat", data)
            fs = fs.rename("binary.dat", "renamed.dat")
            val result = fs.read("renamed.dat")
            assertEquals(3, result.size)
            assertEquals(data[0], result[0])
            assertEquals(data[1], result[1])
            assertEquals(data[2], result[2])
        }
    }

    // ── copy/sync edge cases ──

    @Test
    fun `copyIn missing file throws`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<java.io.FileNotFoundException> {
                fs.copyIn(listOf(tempDir.resolve("nonexistent.txt").toString()), "")
            }
        }
    }

    @Test
    fun `copyIn empty file`(@TempDir tempDir: Path) {
        val emptyFile = tempDir.resolve("empty.txt").toFile()
        emptyFile.writeText("")
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(emptyFile.absolutePath), "")
            assertTrue(fs.exists("empty.txt"))
            assertEquals("", fs.readText("empty.txt"))
        }
    }

    @Test
    fun `copyIn binary data`(@TempDir tempDir: Path) {
        val binFile = tempDir.resolve("data.bin").toFile()
        binFile.writeBytes(byteArrayOf(0x00, 0xFF.toByte(), 0x42))
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(binFile.absolutePath), "")
            val content = fs.read("data.bin")
            assertEquals(3, content.size)
            assertEquals(0x00.toByte(), content[0])
        }
    }

    @Test
    fun `copyOut missing file throws`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()
        val store = createStore()
        store.use {
            val fs = it.branches["main"]
            assertThrows<java.io.FileNotFoundException> {
                fs.copyOut(listOf("nonexistent.txt"), destDir.absolutePath)
            }
        }
    }

    @Test
    fun `syncIn is idempotent`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("data").toFile()
        srcDir.mkdirs()
        File(srcDir, "file.txt").writeText("content")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.syncIn(srcDir.absolutePath, "dest")
            val hash1 = fs.commitHash
            fs = fs.syncIn(srcDir.absolutePath, "dest")
            // Second sync with identical content should be no-op
            assertEquals(hash1, fs.commitHash)
        }
    }

    @Test
    fun `syncOut prunes empty dirs`(@TempDir tempDir: Path) {
        val destDir = tempDir.resolve("out").toFile()
        destDir.mkdirs()
        val subDir = File(destDir, "sub")
        subDir.mkdirs()
        File(subDir, "extra.txt").writeText("extra")

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("root.txt", "root".toByteArray())
            fs.syncOut("", destDir.absolutePath)
            assertFalse(File(destDir, "sub").exists())
        }
    }

    @Test
    fun `copyFromRef contents mode trailing slash`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("dir/a.txt", "aaa".toByteArray())
            src = src.write("dir/b.txt", "bbb".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]
            dest = dest.write("other.txt", "other".toByteArray())

            dest = dest.copyFromRef(src, listOf("dir/"), "imported")
            assertEquals("aaa", dest.readText("imported/a.txt"))
            assertEquals("bbb", dest.readText("imported/b.txt"))
        }
    }

    @Test
    fun `copyFromRef readonly dest throws`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())
            it.tags["v1"] = src
            val tagFs = it.tags["v1"]
            assertThrows<PermissionError> {
                tagFs.copyFromRef(src, listOf("a.txt"), "")
            }
        }
    }

    @Test
    fun `copyFromRef custom message`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())

            it.branches["other"] = src
            var dest = it.branches["other"]
            dest = dest.write("other.txt", "other".toByteArray())

            dest = dest.copyFromRef(src, listOf("a.txt"), "dest", message = "custom copy")
            assertEquals("custom copy", dest.message)
        }
    }

    // -- copyFromRef by name string -------------------------------------------

    @Test
    fun `copyFromRef resolves branch name string`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())

            it.branches["other"] = src
            var other = it.branches["other"]
            other = other.write("b.txt", "bbb".toByteArray())

            // Copy from "other" by name string
            var main = it.branches["main"]
            main = main.copyFromRef("other", listOf("b.txt"))
            assertEquals("bbb", main.readText("b.txt"))
            assertEquals("aaa", main.readText("a.txt"))
        }
    }

    @Test
    fun `copyFromRef resolves tag name string`() {
        val store = createStore()
        store.use {
            var src = it.branches["main"]
            src = src.write("a.txt", "aaa".toByteArray())

            it.tags["v1"] = src
            it.branches["other"] = src
            var other = it.branches["other"]
            other = other.write("other.txt", "other".toByteArray())

            other = other.copyFromRef("v1", listOf("a.txt"), "copied")
            assertEquals("aaa", other.readText("copied/a.txt"))
        }
    }

    @Test
    fun `copyFromRef nonexistent name throws`() {
        val store = createStore()
        store.use {
            var main = it.branches["main"]
            main = main.write("a.txt", "aaa".toByteArray())

            assertThrows<IllegalArgumentException> {
                main.copyFromRef("no-such-branch", listOf("a.txt"))
            }
        }
    }

    @Test
    fun `copyFromRef prefers branch over tag with same name`() {
        val store = createStore()
        store.use {
            var main = it.branches["main"]
            main = main.write("data/a.txt", "from-main".toByteArray())

            // Create branch "other" with different content
            it.branches["other"] = main
            var other = it.branches["other"]
            other = other.write("data/a.txt", "from-other".toByteArray())

            // Create tag "other" pointing to main
            it.tags["other"] = main

            // Branch should win — copy the directory
            main = it.branches["main"]
            main = main.copyFromRef("other", listOf("data"))
            assertEquals("from-other", main.readText("data/a.txt"))
        }
    }
}
