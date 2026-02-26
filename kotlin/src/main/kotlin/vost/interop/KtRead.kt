package vost.interop

import com.google.gson.Gson
import com.google.gson.JsonObject
import vost.FileType
import vost.GitStore
import java.io.File
import java.util.Base64

object KtRead {

    fun main(fixturesPath: String, repoDir: String, prefix: String) {
        val gson = Gson()
        val fixtures = gson.fromJson(File(fixturesPath).readText(), JsonObject::class.java)
        var failures = 0

        for ((name, specElement) in fixtures.entrySet()) {
            val spec = specElement.asJsonObject
            val branch = spec.get("branch")?.asString ?: "main"
            val repoPath = "$repoDir/${prefix}_$name.git"

            if (!File(repoPath).exists()) {
                println("  FAIL $name: repo not found at $repoPath")
                failures++
                continue
            }

            val store = GitStore.open(repoPath, create = false)
            store.use {
                if (spec.has("commits")) {
                    failures += checkHistory(it, branch, spec, name)
                } else {
                    val fs = it.branches[branch]
                    failures += checkBasic(fs, spec, name)
                }

                if (spec.has("notes")) {
                    failures += checkNotes(it, branch, spec, name)
                }
            }
        }

        if (failures > 0) {
            println("\n$failures failure(s)")
            System.exit(1)
        } else {
            println("\nAll checks passed")
        }
    }

    private fun checkBasic(fs: vost.Fs, spec: JsonObject, name: String): Int {
        var failures = 0

        // Text files
        if (spec.has("files")) {
            for ((path, expected) in spec.getAsJsonObject("files").entrySet()) {
                val actual = fs.readText(path)
                if (actual != expected.asString) {
                    println("  FAIL $name: $path content expected ${expected.asString}, got $actual")
                    failures++
                } else {
                    println("  OK   $name: $path")
                }
            }
        }

        // Symlinks
        if (spec.has("symlinks")) {
            for ((path, expectedTarget) in spec.getAsJsonObject("symlinks").entrySet()) {
                val actualTarget = fs.readlink(path)
                if (actualTarget != expectedTarget.asString) {
                    println("  FAIL $name: $path link target expected ${expectedTarget.asString}, got $actualTarget")
                    failures++
                } else {
                    println("  OK   $name: symlink $path -> $actualTarget")
                }
            }
        }

        // Binary files
        if (spec.has("binary_files")) {
            for ((path, b64) in spec.getAsJsonObject("binary_files").entrySet()) {
                val expectedBytes = Base64.getDecoder().decode(b64.asString)
                val actualBytes = fs.read(path)
                if (!actualBytes.contentEquals(expectedBytes)) {
                    println("  FAIL $name: $path binary content mismatch")
                    failures++
                } else {
                    println("  OK   $name: binary $path (${actualBytes.size} bytes)")
                }
            }
        }

        // Executable files
        if (spec.has("executable_files")) {
            for ((path, expected) in spec.getAsJsonObject("executable_files").entrySet()) {
                val actual = fs.readText(path)
                if (actual != expected.asString) {
                    println("  FAIL $name: $path content expected ${expected.asString}, got $actual")
                    failures++
                    continue
                }
                // Check mode via walk
                var found = false
                for (entry in fs.walk()) {
                    for (file in entry.files) {
                        val rel = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                        if (rel == path) {
                            if (file.fileType != FileType.EXECUTABLE) {
                                println("  FAIL $name: $path expected EXECUTABLE, got ${file.fileType}")
                                failures++
                            } else {
                                println("  OK   $name: executable $path")
                            }
                            found = true
                            break
                        }
                    }
                    if (found) break
                }
            }
        }

        // Verify file count
        val allFiles = mutableSetOf<String>()
        for (entry in fs.walk()) {
            for (file in entry.files) {
                val rel = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                allFiles.add(rel)
            }
        }
        val expectedFiles = mutableSetOf<String>()
        if (spec.has("files")) {
            for ((path, _) in spec.getAsJsonObject("files").entrySet()) expectedFiles.add(path)
        }
        if (spec.has("symlinks")) {
            for ((path, _) in spec.getAsJsonObject("symlinks").entrySet()) expectedFiles.add(path)
        }
        if (spec.has("binary_files")) {
            for ((path, _) in spec.getAsJsonObject("binary_files").entrySet()) expectedFiles.add(path)
        }
        if (spec.has("executable_files")) {
            for ((path, _) in spec.getAsJsonObject("executable_files").entrySet()) expectedFiles.add(path)
        }

        val extra = allFiles - expectedFiles
        val missing = expectedFiles - allFiles
        if (extra.isNotEmpty()) {
            println("  FAIL $name: unexpected files $extra")
            failures++
        }
        if (missing.isNotEmpty()) {
            println("  FAIL $name: missing files $missing")
            failures++
        }

        return failures
    }

    private fun checkHistory(store: GitStore, branch: String, spec: JsonObject, name: String): Int {
        var failures = 0
        val fs = store.branches[branch]
        val commits = spec.getAsJsonArray("commits")

        // Final state: last commit's cumulative result
        val last = commits[commits.size() - 1].asJsonObject
        if (last.has("files")) {
            for ((path, expected) in last.getAsJsonObject("files").entrySet()) {
                val actual = fs.readText(path)
                if (actual != expected.asString) {
                    println("  FAIL $name: HEAD $path expected ${expected.asString}, got $actual")
                    failures++
                } else {
                    println("  OK   $name: HEAD $path")
                }
            }
        }

        // Removed files should not exist
        if (last.has("removes")) {
            for (pathElement in last.getAsJsonArray("removes")) {
                val path = pathElement.asString
                if (fs.exists(path)) {
                    println("  FAIL $name: $path should have been removed")
                    failures++
                } else {
                    println("  OK   $name: $path removed")
                }
            }
        }

        // Check we can walk back through history
        val numCommits = commits.size()
        val backFs = fs.back(numCommits - 1)
        val first = commits[0].asJsonObject
        if (first.has("files")) {
            for ((path, expected) in first.getAsJsonObject("files").entrySet()) {
                val actual = backFs.readText(path)
                if (actual != expected.asString) {
                    println("  FAIL $name: commit[0] $path expected ${expected.asString}, got $actual")
                    failures++
                } else {
                    println("  OK   $name: commit[0] $path")
                }
            }
        }

        // Verify commit count by walking parents
        var count = 0
        var current: vost.Fs? = fs
        while (current != null) {
            count++
            current = try { current.back(1) } catch (_: Exception) { null }
        }
        // +1 for the initial empty commit created by GitStore.open
        if (count != numCommits + 1) {
            println("  FAIL $name: expected ${numCommits + 1} commits, found $count")
            failures++
        } else {
            println("  OK   $name: $count commits in history")
        }

        return failures
    }

    private fun checkNotes(store: GitStore, branch: String, spec: JsonObject, name: String): Int {
        var failures = 0
        val fs = store.branches[branch]
        val commitHash = fs.commitHash

        for ((namespace, expectedText) in spec.getAsJsonObject("notes").entrySet()) {
            try {
                val actual = store.notes[namespace][commitHash]
                if (actual != expectedText.asString) {
                    println("  FAIL $name: notes[$namespace] expected ${expectedText.asString}, got $actual")
                    failures++
                } else {
                    println("  OK   $name: notes[$namespace]")
                }
            } catch (e: Exception) {
                println("  FAIL $name: notes[$namespace] not found for $commitHash")
                failures++
            }
        }

        return failures
    }
}
