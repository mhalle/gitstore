package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.nio.file.Path
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ExcludeFilterTest {

    @Test
    fun `basic pattern matching`() {
        val ef = ExcludeFilter(patterns = listOf("*.pyc"))
        assertTrue(ef.isExcluded("foo.pyc"))
        assertTrue(ef.isExcluded("dir/bar.pyc"))
        assertFalse(ef.isExcluded("foo.py"))
        assertFalse(ef.isExcluded("foo.txt"))
    }

    @Test
    fun `negation pattern`() {
        val ef = ExcludeFilter(patterns = listOf("*.pyc", "!important.pyc"))
        assertTrue(ef.isExcluded("foo.pyc"))
        assertFalse(ef.isExcluded("important.pyc"))
        assertFalse(ef.isExcluded("foo.py"))
    }

    @Test
    fun `directory-only pattern`() {
        val ef = ExcludeFilter(patterns = listOf("build/"))
        assertTrue(ef.isExcluded("build", isDir = true))
        assertFalse(ef.isExcluded("build", isDir = false))
        assertTrue(ef.isExcluded("sub/build", isDir = true))
    }

    @Test
    fun `anchored pattern with slash`() {
        val ef = ExcludeFilter(patterns = listOf("src/*.tmp"))
        assertTrue(ef.isExcluded("src/foo.tmp"))
        assertFalse(ef.isExcluded("other/foo.tmp"))
        assertFalse(ef.isExcluded("foo.tmp"))
    }

    @Test
    fun `basename matching without slash`() {
        val ef = ExcludeFilter(patterns = listOf("*.log"))
        assertTrue(ef.isExcluded("app.log"))
        assertTrue(ef.isExcluded("dir/app.log"))
        assertTrue(ef.isExcluded("a/b/c/app.log"))
    }

    @Test
    fun `comments and blank lines are ignored`() {
        val ef = ExcludeFilter(patterns = listOf("# comment", "", "  ", "*.pyc"))
        assertTrue(ef.isExcluded("foo.pyc"))
        assertTrue(ef.active)
    }

    @Test
    fun `empty filter is not active`() {
        val ef = ExcludeFilter()
        assertFalse(ef.active)
        assertFalse(ef.isExcluded("anything"))
    }

    @Test
    fun `load from file`(@TempDir tempDir: Path) {
        val patternFile = tempDir.resolve("excludes.txt").toFile()
        patternFile.writeText("*.pyc\n__pycache__/\n!important.pyc\n")

        val ef = ExcludeFilter(excludeFrom = patternFile.absolutePath)
        assertTrue(ef.active)
        assertTrue(ef.isExcluded("foo.pyc"))
        assertFalse(ef.isExcluded("important.pyc"))
        assertTrue(ef.isExcluded("__pycache__", isDir = true))
        assertFalse(ef.isExcluded("__pycache__", isDir = false))
    }

    @Test
    fun `load from nonexistent file is silent`() {
        val ef = ExcludeFilter(excludeFrom = "/nonexistent/path/file.txt")
        assertFalse(ef.active)
    }

    @Test
    fun `last matching rule wins`() {
        val ef = ExcludeFilter(patterns = listOf("*.log", "!important.log", "*.log"))
        // *.log matches, then !important.log un-excludes, then *.log re-excludes
        assertTrue(ef.isExcluded("important.log"))
        assertTrue(ef.isExcluded("other.log"))
    }

    @Test
    fun `question mark wildcard`() {
        val ef = ExcludeFilter(patterns = listOf("?.txt"))
        assertTrue(ef.isExcluded("a.txt"))
        assertFalse(ef.isExcluded("ab.txt"))
    }

    @Test
    fun `integration with copyIn`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("src").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")
        File(srcDir, "b.pyc").writeText("compiled")
        File(srcDir, "c.txt").writeText("ccc")
        val subDir = File(srcDir, "sub")
        subDir.mkdirs()
        File(subDir, "d.pyc").writeText("compiled2")
        File(subDir, "e.txt").writeText("eee")

        val ef = ExcludeFilter(patterns = listOf("*.pyc"))

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcDir.absolutePath + "/"), "", exclude = ef)

            assertTrue(fs.exists("a.txt"))
            assertFalse(fs.exists("b.pyc"))
            assertTrue(fs.exists("c.txt"))
            assertFalse(fs.exists("sub/d.pyc"))
            assertTrue(fs.exists("sub/e.txt"))
        }
    }

    @Test
    fun `integration with copyIn excludes directory`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("src").toFile()
        srcDir.mkdirs()
        File(srcDir, "a.txt").writeText("aaa")
        val buildDir = File(srcDir, "build")
        buildDir.mkdirs()
        File(buildDir, "output.bin").writeText("binary")

        val ef = ExcludeFilter(patterns = listOf("build/"))

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.copyIn(listOf(srcDir.absolutePath + "/"), "", exclude = ef)

            assertTrue(fs.exists("a.txt"))
            assertFalse(fs.exists("build/output.bin"))
        }
    }

    @Test
    fun `integration with syncIn`(@TempDir tempDir: Path) {
        val srcDir = tempDir.resolve("src").toFile()
        srcDir.mkdirs()
        File(srcDir, "keep.txt").writeText("keep")
        File(srcDir, "skip.pyc").writeText("skip")

        val ef = ExcludeFilter(patterns = listOf("*.pyc"))

        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.syncIn(srcDir.absolutePath, "dest", exclude = ef)

            assertTrue(fs.exists("dest/keep.txt"))
            assertFalse(fs.exists("dest/skip.pyc"))
        }
    }
}
