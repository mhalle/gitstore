package vost

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.nio.file.Path
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MirrorTest {

    private fun createRemoteDir(tempDir: Path): String {
        val remoteDir = tempDir.resolve("remote.git").toFile()
        return remoteDir.absolutePath
    }

    @Test
    fun `backup to local bare repo`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            val diff = it.backup(remoteUrl)

            assertFalse(diff.inSync)
            assertTrue(diff.add.isNotEmpty())

            // Verify remote has the refs
            val remote = GitStore.open(remoteUrl, create = false)
            remote.use { r ->
                val remoteBranches = r.branches.list()
                assertTrue("main" in remoteBranches)
                assertEquals("hello", r.branches["main"].readText("a.txt"))
            }
        }
    }

    @Test
    fun `restore from local bare repo`(@TempDir tempDir: Path) {
        // Create source store with data
        val store1 = createStore()
        store1.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Create a new empty store and restore into it
            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                val diff = s2.restore(remoteUrl)
                assertFalse(diff.inSync)
                assertTrue(diff.add.isNotEmpty())

                val branches = s2.branches.list()
                assertTrue("main" in branches)
                assertEquals("hello", s2.branches["main"].readText("a.txt"))
            }
        }
    }

    @Test
    fun `dry-run backup makes no changes`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            // First do a real backup so remote exists
            it.backup(remoteUrl)

            // Write more data
            fs = it.branches["main"]
            fs = fs.write("b.txt", "world".toByteArray())

            // Dry-run should report changes but not push
            val diff = it.backup(remoteUrl, dryRun = true)
            assertTrue(diff.update.isNotEmpty() || diff.add.isNotEmpty())

            // Remote should still only have the old data
            val remote = GitStore.open(remoteUrl, create = false)
            remote.use { r ->
                assertFalse(r.branches["main"].exists("b.txt"))
            }
        }
    }

    @Test
    fun `dry-run restore makes no changes`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Create empty store
            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                val diff = s2.restore(remoteUrl, dryRun = true)
                assertFalse(diff.inSync)

                // Store2 should still be empty
                assertTrue(s2.branches.list().isEmpty())
            }
        }
    }

    @Test
    fun `backup deletes stale remote refs`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            // Create a second branch
            it.branches["extra"] = fs

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Verify remote has both branches
            val remote1 = GitStore.open(remoteUrl, create = false)
            remote1.use { r ->
                assertTrue("extra" in r.branches.list())
            }

            // Delete the extra branch locally
            it.branches.delete("extra")

            // Backup again — should delete the remote extra branch
            val diff = it.backup(remoteUrl)
            assertTrue(diff.delete.any { it.refName.contains("extra") })

            // Verify remote no longer has the extra branch
            val remote2 = GitStore.open(remoteUrl, create = false)
            remote2.use { r ->
                assertFalse("extra" in r.branches.list())
            }
        }
    }

    @Test
    fun `restore is additive`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Create a local-only branch
            it.branches["local-only"] = fs
            assertTrue("local-only" in it.branches.list())

            // Restore from remote — local-only branch should survive (additive)
            val diff = it.restore(remoteUrl)
            assertTrue(diff.delete.isEmpty())
            assertTrue("local-only" in it.branches.list())
        }
    }

    @Test
    fun `round-trip backup then restore`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("b.txt", "bbb".toByteArray())

            it.branches["feature"] = fs
            var feat = it.branches["feature"]
            feat = feat.write("c.txt", "ccc".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Create new store and restore
            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                s2.restore(remoteUrl)

                assertEquals("aaa", s2.branches["main"].readText("a.txt"))
                assertEquals("bbb", s2.branches["main"].readText("b.txt"))
                assertTrue("feature" in s2.branches.list())
                assertEquals("ccc", s2.branches["feature"].readText("c.txt"))
            }
        }
    }

    @Test
    fun `backup when already in sync`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            // Second backup should be in sync
            val diff = it.backup(remoteUrl)
            assertTrue(diff.inSync)
            assertEquals(0, diff.total)
        }
    }

    @Test
    fun `backup with tags`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            val remote = GitStore.open(remoteUrl, create = false)
            remote.use { r ->
                assertTrue("v1.0" in r.tags.list())
                assertEquals("hello", r.tags["v1.0"].readText("a.txt"))
            }
        }
    }

    // ── Bundle tests ────────────────────────────────────────────────────

    @Test
    fun `backup to bundle`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val bundle = tempDir.resolve("backup.bundle").toFile().absolutePath
            val diff = it.backup(bundle)

            assertFalse(diff.inSync)
            assertTrue(diff.add.isNotEmpty())
            assertTrue(File(bundle).exists())
        }
    }

    @Test
    fun `restore from bundle`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val bundle = tempDir.resolve("backup.bundle").toFile().absolutePath
            it.backup(bundle)

            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                val diff = s2.restore(bundle)
                assertFalse(diff.inSync)

                assertTrue("main" in s2.branches.list())
                assertEquals("hello", s2.branches["main"].readText("a.txt"))
                assertTrue("v1.0" in s2.tags.list())
            }
        }
    }

    @Test
    fun `bundle dry run`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())

            val bundle = tempDir.resolve("backup.bundle").toFile().absolutePath
            val diff = it.backup(bundle, dryRun = true)

            assertFalse(diff.inSync)
            assertFalse(File(bundle).exists())
        }
    }

    @Test
    fun `bundle round trip`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "aaa".toByteArray())
            fs = fs.write("b.txt", "bbb".toByteArray())
            it.tags["v1.0"] = fs

            val bundle = tempDir.resolve("roundtrip.bundle").toFile().absolutePath
            it.backup(bundle)

            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                s2.restore(bundle)
                assertEquals("aaa", s2.branches["main"].readText("a.txt"))
                assertEquals("bbb", s2.branches["main"].readText("b.txt"))
                assertTrue("v1.0" in s2.tags.list())
            }
        }
    }

    // ── Refs filtering tests ────────────────────────────────────────────

    @Test
    fun `backup with refs filter`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl, refs = listOf("main"))

            val remote = GitStore.open(remoteUrl, create = false)
            remote.use { r ->
                assertTrue("main" in r.branches.list())
                assertFalse("v1.0" in r.tags.list())
            }
        }
    }

    @Test
    fun `restore with refs filter`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val remoteUrl = createRemoteDir(tempDir)
            it.backup(remoteUrl)

            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                s2.restore(remoteUrl, refs = listOf("v1.0"))
                assertTrue("v1.0" in s2.tags.list())
            }
        }
    }

    @Test
    fun `backup bundle with refs`(@TempDir tempDir: Path) {
        val store = createStore()
        store.use {
            var fs = it.branches["main"]
            fs = fs.write("a.txt", "hello".toByteArray())
            it.tags["v1.0"] = fs

            val bundle = tempDir.resolve("main-only.bundle").toFile().absolutePath
            it.backup(bundle, refs = listOf("main"))

            val store2Dir = tempDir.resolve("restored.git").toFile()
            val store2 = GitStore.open(store2Dir.absolutePath, branch = null)
            store2.use { s2 ->
                s2.restore(bundle)
                assertTrue("main" in s2.branches.list())
                assertFalse("v1.0" in s2.tags.list())
            }
        }
    }
}
