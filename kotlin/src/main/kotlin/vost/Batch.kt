package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.FileMode

/**
 * Accumulates writes and removes, committing them in a single atomic commit.
 *
 * Use as AutoCloseable or call commit() explicitly. Nothing is committed
 * if an exception occurs.
 */
class Batch internal constructor(
    private val _fs: Fs,
    private val message: String?,
    private val operation: String?,
) : AutoCloseable {

    private val writes = mutableListOf<Pair<String, TreeWrite?>>()
    private val removePaths = mutableSetOf<String>()
    private var closed = false

    /** The resulting Fs after commit, or null if uncommitted or aborted. */
    var fs: Fs? = null
        private set

    private fun checkOpen() {
        if (closed) throw IllegalStateException("Batch is closed")
    }

    /** Stage a file write. */
    fun write(path: String, data: ByteArray, mode: FileType? = null) {
        checkOpen()
        val normalized = normalizePath(path)
        val filemode = mode?.filemode() ?: GIT_FILEMODE_BLOB
        val inserter = _fs.store.repo.newObjectInserter()
        try {
            val blobId = inserter.insert(Constants.OBJ_BLOB, data)
            inserter.flush()

            // Remove from pending removes
            removePaths.remove(normalized)
            // Remove any previous write to same path
            writes.removeAll { it.first == normalized }
            writes.add(Pair(normalized, TreeWrite(blobId, filemode)))
        } finally {
            inserter.close()
        }
    }

    /** Stage a text write (convenience wrapper). */
    fun writeText(path: String, text: String, encoding: String = "UTF-8", mode: FileType? = null) {
        write(path, text.toByteArray(charset(encoding)), mode)
    }

    /** Stage a symbolic link entry. */
    fun writeSymlink(path: String, target: String) {
        checkOpen()
        val normalized = normalizePath(path)
        val inserter = _fs.store.repo.newObjectInserter()
        try {
            val blobId = inserter.insert(Constants.OBJ_BLOB, target.toByteArray(Charsets.UTF_8))
            inserter.flush()
            removePaths.remove(normalized)
            writes.removeAll { it.first == normalized }
            writes.add(Pair(normalized, TreeWrite(blobId, GIT_FILEMODE_LINK)))
        } finally {
            inserter.close()
        }
    }

    /**
     * Stage a file removal.
     *
     * @throws java.io.FileNotFoundException If path does not exist.
     * @throws IsADirectoryException If path is a directory.
     */
    fun remove(path: String) {
        checkOpen()
        val normalized = normalizePath(path)
        val pendingWrite = writes.any { it.first == normalized }
        val existsInBase = existsAtPath(_fs.store.repo, _fs.treeId, normalized)

        if (!pendingWrite && !existsInBase) {
            throw java.io.FileNotFoundException(normalized)
        }

        if (existsInBase) {
            val (_, mode) = walkTo(_fs.store.repo, _fs.treeId, normalized)
            if (mode == FileMode.TREE.bits) throw IsADirectoryException(normalized)
        }

        writes.removeAll { it.first == normalized }
        if (existsInBase) {
            removePaths.add(normalized)
            writes.add(Pair(normalized, null))
        }
    }

    /** Return a writable file-like that stages to the batch on close. */
    fun writer(path: String, mode: String = "wb"): BatchWriter {
        checkOpen()
        val encoding = when (mode) {
            "wb" -> null
            "w" -> "UTF-8"
            else -> throw IllegalArgumentException("writer() mode must be 'wb' or 'w', got '$mode'")
        }
        return BatchWriter(this, path, encoding)
    }

    /**
     * Explicitly commit the batch.
     *
     * After calling this the batch is closed and no further writes are allowed.
     */
    fun commit(): Fs {
        checkOpen()

        if (writes.isEmpty()) {
            fs = _fs
            closed = true
            return _fs
        }

        fs = _fs.commitChanges(writes, message, operation)
        closed = true
        return fs!!
    }

    override fun close() {
        if (closed) return
        if (writes.isEmpty()) {
            fs = _fs
            closed = true
            return
        }
        fs = _fs.commitChanges(writes, message, operation)
        closed = true
    }
}
