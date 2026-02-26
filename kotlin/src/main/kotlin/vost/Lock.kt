package vost

import java.io.File
import java.io.RandomAccessFile
import java.nio.channels.FileLock
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock

/**
 * Advisory repo lock: serializes ref mutations across threads and processes.
 *
 * Uses a combination of in-process ReentrantLock (for thread safety)
 * and file-based locking via java.nio (for cross-process safety).
 */
object RepoLock {
    private val threadLocks = ConcurrentHashMap<String, ReentrantLock>()

    private fun getThreadLock(repoPath: String): ReentrantLock {
        val key = File(repoPath).canonicalPath
        return threadLocks.getOrPut(key) { ReentrantLock() }
    }

    private fun lockPath(repoPath: String): String {
        val f = File(repoPath)
        return if (f.isDirectory) {
            File(f, "vost.lock").path
        } else {
            "$repoPath.lock"
        }
    }

    /**
     * Execute [block] while holding both the thread lock and file lock
     * for the given repository path.
     */
    fun <T> withLock(repoPath: String, block: () -> T): T {
        val tlock = getThreadLock(repoPath)
        tlock.lock()
        try {
            val lockFile = File(lockPath(repoPath))
            lockFile.parentFile?.mkdirs()
            val raf = RandomAccessFile(lockFile, "rw")
            var fileLock: FileLock? = null
            try {
                fileLock = raf.channel.lock()
                return block()
            } finally {
                fileLock?.release()
                raf.close()
            }
        } finally {
            tlock.unlock()
        }
    }
}
