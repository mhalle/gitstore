package vost

import java.io.File
import java.nio.file.Files

/** Create a GitStore in a fresh temporary directory. */
fun createStore(branch: String? = "main"): GitStore {
    val tmpDir = Files.createTempDirectory("vost-test-").toFile()
    tmpDir.deleteOnExit()
    val repoDir = File(tmpDir, "test.git")
    return GitStore.open(repoDir.absolutePath, branch = branch)
}

/** Create a GitStore with some pre-written files. */
fun storeWithFiles(vararg files: Pair<String, String>): Pair<GitStore, Fs> {
    val store = createStore()
    var fs = store.branches["main"]
    for ((path, content) in files) {
        fs = fs.write(path, content.toByteArray())
    }
    return Pair(store, store.branches["main"])
}
