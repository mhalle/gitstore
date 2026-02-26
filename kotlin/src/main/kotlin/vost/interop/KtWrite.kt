package vost.interop

import com.google.gson.Gson
import com.google.gson.JsonObject
import vost.FileType
import vost.GitStore
import java.io.File
import java.util.Base64

object KtWrite {

    fun main(fixturesPath: String, outputDir: String) {
        val gson = Gson()
        val fixtures = gson.fromJson(File(fixturesPath).readText(), JsonObject::class.java)

        for ((name, specElement) in fixtures.entrySet()) {
            val spec = specElement.asJsonObject
            val branch = spec.get("branch")?.asString ?: "main"
            val repoPath = "$outputDir/kt_$name.git"

            val store = GitStore.open(repoPath, branch = branch)
            store.use {
                if (spec.has("commits")) {
                    writeHistory(it, branch, spec)
                } else {
                    writeScenario(it, branch, spec)
                }

                if (spec.has("notes")) {
                    writeNotes(it, branch, spec)
                }
            }

            println("  kt_write: $name -> $repoPath")
        }
    }

    private fun writeScenario(store: GitStore, branch: String, spec: JsonObject) {
        var fs = store.branches[branch]
        val batch = fs.batch(message = "interop")

        // Text files
        if (spec.has("files")) {
            for ((path, value) in spec.getAsJsonObject("files").entrySet()) {
                batch.write(path, value.asString.toByteArray(Charsets.UTF_8))
            }
        }

        // Symlinks
        if (spec.has("symlinks")) {
            for ((path, target) in spec.getAsJsonObject("symlinks").entrySet()) {
                batch.writeSymlink(path, target.asString)
            }
        }

        // Binary files (base64-encoded)
        if (spec.has("binary_files")) {
            for ((path, b64) in spec.getAsJsonObject("binary_files").entrySet()) {
                val data = Base64.getDecoder().decode(b64.asString)
                batch.write(path, data)
            }
        }

        // Executable files
        if (spec.has("executable_files")) {
            for ((path, content) in spec.getAsJsonObject("executable_files").entrySet()) {
                batch.write(path, content.asString.toByteArray(Charsets.UTF_8), FileType.EXECUTABLE)
            }
        }

        batch.commit()
    }

    private fun writeHistory(store: GitStore, branch: String, spec: JsonObject) {
        var fs = store.branches[branch]

        for (stepElement in spec.getAsJsonArray("commits")) {
            val step = stepElement.asJsonObject
            val message = step.get("message").asString
            val batch = fs.batch(message = message)

            if (step.has("files")) {
                for ((path, content) in step.getAsJsonObject("files").entrySet()) {
                    batch.write(path, content.asString.toByteArray(Charsets.UTF_8))
                }
            }

            if (step.has("removes")) {
                for (pathElement in step.getAsJsonArray("removes")) {
                    batch.remove(pathElement.asString)
                }
            }

            fs = batch.commit()
        }
    }

    private fun writeNotes(store: GitStore, branch: String, spec: JsonObject) {
        val fs = store.branches[branch]
        val commitHash = fs.commitHash

        for ((namespace, text) in spec.getAsJsonObject("notes").entrySet()) {
            store.notes[namespace][commitHash] = text.asString
        }
    }
}
