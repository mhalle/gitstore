package vost

import org.eclipse.jgit.lib.CommitBuilder
import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.FileMode
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.revwalk.RevWalk
import org.eclipse.jgit.treewalk.TreeWalk
import java.time.Instant
import java.time.ZoneOffset
import java.time.ZonedDateTime

/**
 * An immutable snapshot of a committed tree.
 *
 * Read-only when writable is false (tag snapshot).
 * Writable when writable is true — writes auto-commit and return a new Fs.
 */
class Fs internal constructor(
    internal val store: GitStore,
    internal val commitId: ObjectId,
    /** The branch or tag name, or null for detached snapshots. */
    val refName: String? = null,
    /** Whether this snapshot can be written to. */
    val writable: Boolean = refName != null,
) {
    internal val treeId: ObjectId
    private var _changes: ChangeReport? = null
    private var _commitTime: Long? = null

    init {
        val revWalk = RevWalk(store.repo)
        try {
            val commit = revWalk.parseCommit(commitId)
            treeId = commit.tree.id
        } finally {
            revWalk.close()
        }
    }

    /** Report of the operation that created this snapshot. */
    var changes: ChangeReport?
        get() = _changes
        internal set(value) { _changes = value }

    override fun toString(): String {
        val short = commitId.name.substring(0, 7)
        val parts = mutableListOf<String>()
        if (refName != null) parts.add("refName='$refName'")
        parts.add("commit=$short")
        if (!writable) parts.add("readonly")
        return "Fs(${parts.joinToString(", ")})"
    }

    // ── Properties ────────────────────────────────────────────────────

    /** The 40-character hex SHA of this snapshot's commit. */
    val commitHash: String get() = commitId.name

    /** The 40-char hex SHA of the root tree. */
    val treeHash: String get() = treeId.name

    /** The commit message (trailing newline stripped). */
    val message: String
        get() {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                return commit.fullMessage.trimEnd('\n')
            } finally {
                revWalk.close()
            }
        }

    /** Timezone-aware commit timestamp. */
    val time: ZonedDateTime
        get() {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                val epochSeconds = commit.commitTime.toLong()
                val offset = commit.committerIdent.zoneId
                return ZonedDateTime.ofInstant(Instant.ofEpochSecond(epochSeconds), offset)
            } finally {
                revWalk.close()
            }
        }

    /** The commit author's name. */
    val authorName: String
        get() {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                return commit.authorIdent.name
            } finally {
                revWalk.close()
            }
        }

    /** The commit author's email address. */
    val authorEmail: String
        get() {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                return commit.authorIdent.emailAddress
            } finally {
                revWalk.close()
            }
        }

    private fun getCommitTime(): Long {
        if (_commitTime == null) {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                _commitTime = commit.commitTime.toLong()
            } finally {
                revWalk.close()
            }
        }
        return _commitTime!!
    }

    private fun readonlyError(verb: String): ReadOnlyError =
        if (refName != null) ReadOnlyError("Cannot $verb read-only snapshot (ref '$refName')")
        else ReadOnlyError("Cannot $verb read-only snapshot")

    // ── Read operations ───────────────────────────────────────────────

    /**
     * Read file contents as bytes.
     *
     * @param path File path in the repo.
     * @param offset Byte offset to start reading from.
     * @param size Maximum number of bytes to return (null for all).
     * @throws java.io.FileNotFoundException If path does not exist.
     * @throws IsADirectoryException If path is a directory.
     */
    fun read(path: String, offset: Int = 0, size: Int? = null): ByteArray {
        val data = readBlobAtPath(store.repo, treeId, path)
        if (offset > 0 || size != null) {
            val end = if (size != null) minOf(offset + size, data.size) else data.size
            val start = minOf(offset, data.size)
            return data.copyOfRange(start, end)
        }
        return data
    }

    /**
     * Read file contents as a string.
     *
     * @param path File path in the repo.
     * @param encoding Text encoding (default "UTF-8").
     * @return Decoded file contents.
     */
    fun readText(path: String, encoding: String = "UTF-8"): String =
        String(read(path), charset(encoding))

    /**
     * List entry names at path (or root if null).
     *
     * @throws NotADirectoryException If path is a file.
     */
    fun ls(path: String? = null): List<String> =
        listTreeAtPath(store.repo, treeId, path)

    /**
     * Walk the repo tree recursively, like os.walk.
     *
     * Returns list of (dirpath, dirnames, file_entries).
     *
     * @throws NotADirectoryException If path is a file.
     */
    fun walk(path: String? = null): List<WalkDirEntry> {
        return if (path == null || isRootPath(path)) {
            walkTree(store.repo, treeId)
        } else {
            val normalized = normalizePath(path)
            val (objId, mode) = walkTo(store.repo, treeId, normalized)
            if (mode != FileMode.TREE.bits) throw NotADirectoryException(normalized)
            walkTree(store.repo, objId, normalized)
        }
    }

    /** Return true if path exists (file or directory). */
    fun exists(path: String): Boolean =
        existsAtPath(store.repo, treeId, path)

    /** Return true if path is a directory (tree) in the repo. */
    fun isDir(path: String): Boolean {
        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized) ?: return false
        return entry.second == FileMode.TREE.bits
    }

    /**
     * Return the FileType of path.
     *
     * @throws java.io.FileNotFoundException If the path does not exist.
     */
    fun fileType(path: String): FileType {
        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized)
            ?: throw java.io.FileNotFoundException(normalized)
        return FileType.fromMode(entry.second)
    }

    /**
     * Return the size in bytes of the object at path.
     *
     * @throws java.io.FileNotFoundException If the path does not exist.
     */
    fun size(path: String): Long {
        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized)
            ?: throw java.io.FileNotFoundException(normalized)
        val (oid, _) = entry
        return blobSize(store.repo, oid)
    }

    /**
     * Return the 40-character hex SHA of the object at path.
     *
     * @throws java.io.FileNotFoundException If the path does not exist.
     */
    fun objectHash(path: String): String {
        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized)
            ?: throw java.io.FileNotFoundException(normalized)
        return entry.first.name
    }

    /**
     * Return a StatResult for path (or root if null).
     */
    fun stat(path: String? = null): StatResult {
        val mtime = getCommitTime()

        if (path == null || isRootPath(path)) {
            val nlink = 2 + countSubdirs(store.repo, treeId)
            return StatResult(
                mode = GIT_FILEMODE_TREE,
                fileType = FileType.TREE,
                size = 0,
                hash = treeId.name,
                nlink = nlink,
                mtime = mtime,
            )
        }

        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized)
            ?: throw java.io.FileNotFoundException(normalized)
        val (oid, filemode) = entry

        val ft = FileType.fromMode(filemode)
        val nlink: Int
        val fileSize: Long
        if (filemode == GIT_FILEMODE_TREE) {
            nlink = 2 + countSubdirs(store.repo, oid)
            fileSize = 0
        } else {
            nlink = 1
            fileSize = blobSize(store.repo, oid)
        }

        return StatResult(
            mode = filemode,
            fileType = ft,
            size = fileSize,
            hash = oid.name,
            nlink = nlink,
            mtime = mtime,
        )
    }

    /**
     * List directory entries with name, oid, and mode.
     */
    fun listdir(path: String? = null): List<WalkEntry> =
        listEntriesAtPath(store.repo, treeId, path)

    /**
     * Read raw blob data by hash, bypassing tree lookup.
     */
    fun readByHash(hash: String, offset: Int = 0, size: Int? = null): ByteArray {
        val oid = ObjectId.fromString(hash)
        val loader = store.repo.open(oid, Constants.OBJ_BLOB)
        val data = loader.bytes
        if (offset > 0 || size != null) {
            val end = if (size != null) minOf(offset + size, data.size) else data.size
            val start = minOf(offset, data.size)
            return data.copyOfRange(start, end)
        }
        return data
    }

    /**
     * Read the target of a symlink.
     */
    fun readlink(path: String): String {
        val normalized = normalizePath(path)
        val entry = entryAtPath(store.repo, treeId, normalized)
            ?: throw java.io.FileNotFoundException(normalized)
        val (oid, filemode) = entry
        if (filemode != GIT_FILEMODE_LINK) throw IllegalStateException("Not a symlink: $normalized")
        val loader = store.repo.open(oid, Constants.OBJ_BLOB)
        return String(loader.bytes, Charsets.UTF_8)
    }

    // ── Glob operations ──────────────────────────────────────────────

    /**
     * Expand a glob pattern against the repo tree.
     *
     * Supports `*`, `?`, and `**`. `*` and `?` do not match
     * a leading `.` unless the pattern segment itself starts with `.`.
     * `**` matches zero or more directory levels, skipping directories
     * whose names start with `.`.
     *
     * @return A sorted, deduplicated list of matching paths.
     */
    fun glob(pattern: String): List<String> = iglob(pattern).sorted()

    /**
     * Expand a glob pattern against the repo tree, returning an unordered sequence.
     */
    fun iglob(pattern: String): List<String> {
        val stripped = pattern.trim('/')
        if (stripped.isEmpty()) return emptyList()
        val seen = mutableSetOf<String>()
        val result = mutableListOf<String>()
        for (path in iglobWalk(stripped.split("/"), null, treeId)) {
            if (seen.add(path)) result.add(path)
        }
        return result
    }

    private fun iglobEntries(treeOid: ObjectId): List<Triple<String, Boolean, ObjectId>> {
        val entries = mutableListOf<Triple<String, Boolean, ObjectId>>()
        val tw = TreeWalk(store.repo)
        try {
            tw.addTree(treeOid)
            tw.isRecursive = false
            while (tw.next()) {
                entries.add(Triple(tw.nameString, tw.getRawMode(0) == FileMode.TREE.bits, tw.getObjectId(0)))
            }
        } finally {
            tw.close()
        }
        return entries
    }

    private fun iglobWalk(segments: List<String>, prefix: String?, treeOid: ObjectId): Sequence<String> = sequence {
        if (segments.isEmpty()) return@sequence
        val seg = segments[0]
        val rest = segments.subList(1, segments.size)

        if (seg == "**") {
            val entries = try { iglobEntries(treeOid) } catch (_: Exception) { return@sequence }
            if (rest.isNotEmpty()) {
                yieldAll(iglobMatchEntries(rest, prefix, entries))
            } else {
                for ((name, _, _) in entries) {
                    if (name.startsWith(".")) continue
                    yield(if (prefix != null) "$prefix/$name" else name)
                }
            }
            for ((name, isDir, oid) in entries) {
                if (name.startsWith(".")) continue
                val full = if (prefix != null) "$prefix/$name" else name
                if (isDir) {
                    yieldAll(iglobWalk(segments, full, oid))
                }
            }
            return@sequence
        }

        val hasWild = '*' in seg || '?' in seg

        if (hasWild) {
            val entries = try { iglobEntries(treeOid) } catch (_: Exception) { return@sequence }
            for ((name, _, oid) in entries) {
                if (!globMatch(seg, name)) continue
                val full = if (prefix != null) "$prefix/$name" else name
                if (rest.isNotEmpty()) {
                    yieldAll(iglobWalk(rest, full, oid))
                } else {
                    yield(full)
                }
            }
        } else {
            // Literal segment — look up directly
            val tw = TreeWalk(store.repo)
            try {
                tw.addTree(treeOid)
                tw.isRecursive = false
                while (tw.next()) {
                    if (tw.nameString == seg) {
                        val full = if (prefix != null) "$prefix/$seg" else seg
                        if (rest.isNotEmpty()) {
                            yieldAll(iglobWalk(rest, full, tw.getObjectId(0)))
                        } else {
                            yield(full)
                        }
                        break
                    }
                }
            } finally {
                tw.close()
            }
        }
    }

    private fun iglobMatchEntries(
        segments: List<String>,
        prefix: String?,
        entries: List<Triple<String, Boolean, ObjectId>>,
    ): Sequence<String> = sequence {
        val seg = segments[0]
        val rest = segments.subList(1, segments.size)
        val hasWild = '*' in seg || '?' in seg

        if (hasWild) {
            for ((name, _, oid) in entries) {
                if (!globMatch(seg, name)) continue
                val full = if (prefix != null) "$prefix/$name" else name
                if (rest.isNotEmpty()) {
                    yieldAll(iglobWalk(rest, full, oid))
                } else {
                    yield(full)
                }
            }
        } else {
            for ((name, _, oid) in entries) {
                if (name == seg) {
                    val full = if (prefix != null) "$prefix/$seg" else seg
                    if (rest.isNotEmpty()) {
                        yieldAll(iglobWalk(rest, full, oid))
                    } else {
                        yield(full)
                    }
                    return@sequence
                }
            }
        }
    }

    // ── Write operations ──────────────────────────────────────────────

    /**
     * Write data to path and commit, returning a new Fs.
     */
    fun write(
        path: String,
        data: ByteArray,
        message: String? = null,
        mode: FileType? = null,
    ): Fs {
        val filemode = mode?.filemode() ?: GIT_FILEMODE_BLOB
        val normalized = normalizePath(path)
        val inserter = store.repo.newObjectInserter()
        try {
            val blobId = inserter.insert(Constants.OBJ_BLOB, data)
            inserter.flush()
            val writes = listOf(Pair(normalized, TreeWrite(blobId, filemode) as TreeWrite?))
            return commitChanges(writes, message)
        } finally {
            inserter.close()
        }
    }

    /**
     * Write text to path and commit, returning a new Fs.
     *
     * @param path Destination path in the repo.
     * @param text String content (encoded with [encoding]).
     * @param encoding Text encoding (default "UTF-8").
     * @param message Commit message (auto-generated if null).
     * @param mode File mode override (e.g. [FileType.EXECUTABLE]).
     * @return New Fs snapshot.
     * @throws ReadOnlyError If this snapshot is read-only.
     * @throws StaleSnapshotError If the branch has advanced since this snapshot.
     */
    fun writeText(
        path: String,
        text: String,
        encoding: String = "UTF-8",
        message: String? = null,
        mode: FileType? = null,
    ): Fs = write(path, text.toByteArray(charset(encoding)), message, mode)

    /**
     * Create a symbolic link entry and commit, returning a new Fs.
     *
     * @param path Symlink path in the repo.
     * @param target The symlink target string.
     * @param message Commit message (auto-generated if null).
     * @return New Fs snapshot.
     * @throws ReadOnlyError If this snapshot is read-only.
     * @throws StaleSnapshotError If the branch has advanced since this snapshot.
     */
    fun writeSymlink(path: String, target: String, message: String? = null): Fs {
        val normalized = normalizePath(path)
        val inserter = store.repo.newObjectInserter()
        try {
            val blobId = inserter.insert(Constants.OBJ_BLOB, target.toByteArray(Charsets.UTF_8))
            inserter.flush()
            val writes = listOf(Pair(normalized, TreeWrite(blobId, GIT_FILEMODE_LINK) as TreeWrite?))
            return commitChanges(writes, message)
        } finally {
            inserter.close()
        }
    }

    /**
     * Apply multiple writes and removes in a single atomic commit.
     */
    fun apply(
        writes: Map<String, Any>? = null,
        removes: Collection<String>? = null,
        message: String? = null,
        operation: String? = null,
    ): Fs {
        val inserter = store.repo.newObjectInserter()
        try {
            val internalWrites = mutableListOf<Pair<String, TreeWrite?>>()

            for ((path, value) in (writes ?: emptyMap())) {
                val normalized = normalizePath(path)
                when (value) {
                    is ByteArray -> {
                        val blobId = inserter.insert(Constants.OBJ_BLOB, value)
                        internalWrites.add(Pair(normalized, TreeWrite(blobId, GIT_FILEMODE_BLOB)))
                    }
                    is String -> {
                        val blobId = inserter.insert(Constants.OBJ_BLOB, value.toByteArray(Charsets.UTF_8))
                        internalWrites.add(Pair(normalized, TreeWrite(blobId, GIT_FILEMODE_BLOB)))
                    }
                    is WriteEntry -> {
                        if (value.target != null) {
                            val blobId = inserter.insert(Constants.OBJ_BLOB, value.target.toByteArray(Charsets.UTF_8))
                            internalWrites.add(Pair(normalized, TreeWrite(blobId, GIT_FILEMODE_LINK)))
                        } else if (value.data != null) {
                            val blobId = inserter.insert(Constants.OBJ_BLOB, value.data)
                            val m = value.mode?.filemode() ?: GIT_FILEMODE_BLOB
                            internalWrites.add(Pair(normalized, TreeWrite(blobId, m)))
                        }
                    }
                    else -> throw IllegalArgumentException("Unsupported write value type: ${value::class}")
                }
            }

            // Add removes
            for (path in (removes ?: emptyList())) {
                val normalized = normalizePath(path)
                internalWrites.add(Pair(normalized, null))
            }

            inserter.flush()
            return commitChanges(internalWrites, message, operation)
        } finally {
            inserter.close()
        }
    }

    /**
     * Remove files from the repo.
     *
     * @param paths Repo paths to remove.
     * @param message Commit message (auto-generated if null).
     * @return New Fs snapshot with the files removed.
     * @throws ReadOnlyError If this snapshot is read-only.
     * @throws StaleSnapshotError If the branch has advanced since this snapshot.
     */
    fun remove(
        paths: List<String>,
        message: String? = null,
    ): Fs {
        val removes = paths.map { normalizePath(it) }
        val writes = removes.map { Pair(it, null as TreeWrite?) }
        return commitChanges(writes, message)
    }

    /**
     * Return a [Batch] context manager for multiple writes in one commit.
     *
     * @param message Commit message (auto-generated if null).
     * @param operation Operation name for auto-generated messages.
     * @return A new [Batch] instance.
     * @throws ReadOnlyError If this snapshot is read-only.
     */
    fun batch(message: String? = null, operation: String? = null): Batch {
        if (!writable) throw readonlyError("batch on")
        return Batch(this, message, operation)
    }

    /**
     * Return a writable file-like that commits on close.
     *
     * "wb" accepts bytes; "w" accepts strings (UTF-8 encoded).
     *
     * @param path Destination path in the repo.
     * @param mode "wb" (binary, default) or "w" (text).
     * @return A new [FsWriter] instance.
     * @throws ReadOnlyError If this snapshot is read-only.
     */
    fun writer(path: String, mode: String = "wb"): FsWriter {
        if (!writable) throw readonlyError("write to")
        val encoding = when (mode) {
            "wb" -> null
            "w" -> "UTF-8"
            else -> throw IllegalArgumentException("writer() mode must be 'wb' or 'w', got '$mode'")
        }
        return FsWriter(this, path, encoding)
    }

    // ── Rename / Move ─────────────────────────────────────────────────

    /**
     * Rename a file or directory within the repo.
     *
     * @param src Source path.
     * @param dest Destination path.
     * @param message Optional commit message.
     * @return New Fs snapshot.
     */
    fun rename(src: String, dest: String, message: String? = null): Fs {
        val srcNorm = normalizePath(src)
        val destNorm = normalizePath(dest)
        if (srcNorm == destNorm) throw IllegalArgumentException("Source and destination are the same: $srcNorm")

        val (objId, mode) = walkTo(store.repo, treeId, srcNorm)

        if (mode == FileMode.TREE.bits) {
            // Directory rename: copy all files, then remove originals
            val batch = batch(message = message, operation = "mv")
            for (entry in walk(srcNorm)) {
                for (file in entry.files) {
                    val srcFile = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                    val rel = srcFile.removePrefix("$srcNorm/")
                    val destFile = "$destNorm/$rel"
                    batch.write(destFile, read(srcFile), FileType.fromMode(file.mode))
                }
            }
            // Remove source files
            for (entry in walk(srcNorm)) {
                for (file in entry.files) {
                    val srcFile = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                    batch.remove(srcFile)
                }
            }
            return batch.commit()
        } else {
            // File rename: read blob by OID and write to new path
            val inserter = store.repo.newObjectInserter()
            try {
                val writes = listOf(
                    Pair(destNorm, TreeWrite(objId, mode) as TreeWrite?),
                    Pair(srcNorm, null as TreeWrite?),
                )
                inserter.flush()
                return commitChanges(writes, message, "mv")
            } finally {
                inserter.close()
            }
        }
    }

    /**
     * Move files within the repo.
     *
     * @param sources Source path(s).
     * @param dest Destination path.
     * @param message Optional commit message.
     * @return New Fs snapshot.
     */
    fun move(sources: List<String>, dest: String, message: String? = null): Fs {
        val destNorm = if (dest.trimEnd('/').isNotEmpty()) normalizePath(dest.trimEnd('/')) else ""
        val batch = batch(message = message, operation = "mv")

        for (src in sources) {
            val srcNorm = normalizePath(src)
            val (objId, mode) = walkTo(store.repo, treeId, srcNorm)

            if (mode == FileMode.TREE.bits) {
                // Directory: move contents
                for (entry in walk(srcNorm)) {
                    for (file in entry.files) {
                        val srcFile = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                        val rel = srcFile.removePrefix("$srcNorm/")
                        val name = srcNorm.substringAfterLast('/')
                        val destFile = if (destNorm.isEmpty()) "$name/$rel" else "$destNorm/$name/$rel"
                        batch.write(destFile, read(srcFile), FileType.fromMode(file.mode))
                    }
                }
                for (entry in walk(srcNorm)) {
                    for (file in entry.files) {
                        val srcFile = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                        batch.remove(srcFile)
                    }
                }
            } else {
                // File: move to dest
                val name = srcNorm.substringAfterLast('/')
                val destFile = if (destNorm.isEmpty()) name else "$destNorm/$name"
                val data = read(srcNorm)
                batch.write(destFile, data, FileType.fromMode(mode))
                batch.remove(srcNorm)
            }
        }

        return batch.commit()
    }

    // ── Copy operations ───────────────────────────────────────────────

    /**
     * Copy local files into the repo.
     *
     * @param sources Local path(s). Trailing `/` copies contents.
     * @param dest Destination path in the repo.
     * @param message Commit message.
     * @param delete Remove repo files under dest not in source.
     * @return New Fs snapshot with changes.
     */
    fun copyIn(
        sources: List<String>,
        dest: String,
        message: String? = null,
        delete: Boolean = false,
        exclude: ExcludeFilter? = null,
    ): Fs = CopyOps.copyIn(this, sources, dest, message = message, delete = delete, exclude = exclude)

    /**
     * Copy repo files to local disk.
     *
     * @param sources Repo path(s). Trailing `/` copies contents.
     * @param dest Local destination directory.
     * @param delete Remove local files under dest not in source.
     * @return This Fs with changes set.
     */
    fun copyOut(
        sources: List<String>,
        dest: String,
        delete: Boolean = false,
    ): Fs = CopyOps.copyOut(this, sources, dest, delete = delete)

    /**
     * Make repo_path identical to local_path (including deletes).
     */
    fun syncIn(
        localPath: String,
        repoPath: String,
        message: String? = null,
        exclude: ExcludeFilter? = null,
    ): Fs = CopyOps.syncIn(this, localPath, repoPath, message = message, exclude = exclude)

    /**
     * Make local_path identical to repo_path (including deletes).
     */
    fun syncOut(
        repoPath: String,
        localPath: String,
    ): Fs = CopyOps.syncOut(this, repoPath, localPath)

    /**
     * Copy files from another ref into this branch in a single atomic commit.
     *
     * Since both snapshots share the same object store, blobs are referenced
     * by OID — no data is read into memory regardless of file size.
     */
    fun copyFromRef(
        source: Fs,
        sources: List<String> = listOf(""),
        dest: String = "",
        delete: Boolean = false,
        message: String? = null,
    ): Fs {
        if (source.store !== store) {
            throw IllegalArgumentException("source must belong to the same repo as self")
        }
        if (!writable) throw readonlyError("write to")

        val destNorm = if (dest.isNotEmpty()) normalizePath(dest) else ""

        // Enumerate source files → {dest_path: (oid, mode)}
        val srcMapped = mutableMapOf<String, Pair<ObjectId, Int>>()
        for (src in sources) {
            val stripped = src.trimEnd('/')
            val isContents = src.endsWith("/") || stripped.isEmpty()

            if (stripped.isEmpty()) {
                // Root contents mode — copy everything
                for (entry in source.walk()) {
                    for (file in entry.files) {
                        val storePath = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                        val destFile = if (destNorm.isEmpty()) storePath else "$destNorm/$storePath"
                        srcMapped[normalizePath(destFile)] = Pair(ObjectId.fromString(file.oid), file.mode)
                    }
                }
            } else if (isContents) {
                // Contents mode — pour contents into dest
                val srcNorm = normalizePath(stripped)
                if (!source.exists(srcNorm)) throw java.io.FileNotFoundException(srcNorm)
                if (source.isDir(srcNorm)) {
                    for (entry in source.walk(srcNorm)) {
                        for (file in entry.files) {
                            val storePath = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                            val rel = storePath.removePrefix("$srcNorm/")
                            val destFile = if (destNorm.isEmpty()) rel else "$destNorm/$rel"
                            srcMapped[normalizePath(destFile)] = Pair(ObjectId.fromString(file.oid), file.mode)
                        }
                    }
                } else {
                    // Single file
                    val entry = entryAtPath(store.repo, source.treeId, srcNorm)
                        ?: throw java.io.FileNotFoundException(srcNorm)
                    val name = srcNorm.substringAfterLast('/')
                    val destFile = if (destNorm.isEmpty()) name else "$destNorm/$name"
                    srcMapped[normalizePath(destFile)] = entry
                }
            } else {
                // Directory or file mode
                val srcNorm = normalizePath(stripped)
                if (!source.exists(srcNorm)) throw java.io.FileNotFoundException(srcNorm)
                if (source.isDir(srcNorm)) {
                    val dirname = srcNorm.substringAfterLast('/')
                    val target = if (destNorm.isEmpty()) dirname else "$destNorm/$dirname"
                    for (entry in source.walk(srcNorm)) {
                        for (file in entry.files) {
                            val storePath = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                            val rel = storePath.removePrefix("$srcNorm/")
                            val destFile = normalizePath("$target/$rel")
                            srcMapped[destFile] = Pair(ObjectId.fromString(file.oid), file.mode)
                        }
                    }
                } else {
                    // Single file
                    val entry = entryAtPath(store.repo, source.treeId, srcNorm)
                        ?: throw java.io.FileNotFoundException(srcNorm)
                    val name = srcNorm.substringAfterLast('/')
                    val destFile = if (destNorm.isEmpty()) name else "$destNorm/$name"
                    srcMapped[normalizePath(destFile)] = entry
                }
            }
        }

        // Walk current dest to find files for comparison/deletion
        val destFiles = mutableMapOf<String, Pair<ObjectId, Int>>()
        if (delete || srcMapped.isNotEmpty()) {
            // Walk dest area(s)
            val destPrefixes = mutableSetOf<String>()
            destPrefixes.add(destNorm)
            for (dp in destPrefixes) {
                try {
                    val walkPath = dp.ifEmpty { null }
                    for (entry in walk(walkPath)) {
                        for (file in entry.files) {
                            val storePath = if (entry.dirpath.isEmpty()) file.name else "${entry.dirpath}/${file.name}"
                            destFiles[storePath] = Pair(ObjectId.fromString(file.oid), file.mode)
                        }
                    }
                } catch (_: Exception) {
                    // Dest doesn't exist yet
                }
            }
        }

        // Build writes and removes
        val writes = mutableListOf<Pair<String, TreeWrite?>>()
        for ((destPath, srcEntry) in srcMapped) {
            val (oid, mode) = srcEntry
            val destEntry = destFiles[destPath]
            if (destEntry == null || destEntry.first != oid || destEntry.second != mode) {
                writes.add(Pair(destPath, TreeWrite(oid, mode)))
            }
        }

        if (delete) {
            for (full in destFiles.keys) {
                if (full !in srcMapped) {
                    writes.add(Pair(full, null))
                }
            }
        }

        if (writes.isEmpty()) return this

        return commitChanges(writes, message, "cp")
    }

    // ── History ───────────────────────────────────────────────────────

    /** The parent snapshot, or null for the initial commit. */
    val parent: Fs?
        get() {
            val revWalk = RevWalk(store.repo)
            try {
                val commit = revWalk.parseCommit(commitId)
                if (commit.parentCount == 0) return null
                return Fs(store, commit.getParent(0).id, refName = refName, writable = writable)
            } finally {
                revWalk.close()
            }
        }

    /**
     * Return the Fs at the n-th ancestor commit.
     *
     * @param n Number of commits to go back (must be >= 0).
     * @return Fs at the ancestor commit.
     * @throws IllegalArgumentException If n < 0 or history is too short.
     */
    fun back(n: Int = 1): Fs {
        require(n >= 0) { "back() requires n >= 0, got $n" }
        var fs = this
        for (i in 0 until n) {
            fs = fs.parent ?: throw IllegalArgumentException("Cannot go back $n commits — history too short")
        }
        return fs
    }

    /**
     * Move branch back N commits (undo).
     */
    fun undo(steps: Int = 1): Fs {
        require(steps >= 1) { "steps must be >= 1, got $steps" }
        if (!writable) throw readonlyError("undo on")

        // Walk back N parents
        var current = this
        for (i in 0 until steps) {
            current = current.parent
                ?: throw IllegalArgumentException("Cannot undo $steps steps - only $i commit(s) in history")
        }

        // Atomic stale-check + ref update under lock
        val fullRefName = "refs/heads/$refName"
        RepoLock.withLock(store.repo.directory.path) {
            val ref = store.repo.findRef(fullRefName)
                ?: throw StaleSnapshotError("Branch '$refName' not found")
            if (ref.objectId != commitId) {
                throw StaleSnapshotError("Branch '$refName' has advanced since this snapshot")
            }
            val refUpdate = store.repo.updateRef(fullRefName)
            refUpdate.setNewObjectId(current.commitId)
            refUpdate.setExpectedOldObjectId(commitId)
            refUpdate.setRefLogMessage("undo: move back", false)
            refUpdate.isForceUpdate = true
            refUpdate.update()
        }

        return current
    }

    /**
     * Move branch forward N steps using reflog (redo).
     */
    fun redo(steps: Int = 1): Fs {
        require(steps >= 1) { "steps must be >= 1, got $steps" }
        if (!writable) throw readonlyError("redo on")

        val fullRefName = "refs/heads/$refName"

        // Early stale check
        val ref = store.repo.findRef(fullRefName)
            ?: throw StaleSnapshotError("Branch '$refName' not found")
        if (ref.objectId != commitId) {
            throw StaleSnapshotError("Branch '$refName' has advanced since this snapshot")
        }

        // Read reflog
        val reflogReader = store.repo.getReflogReader(fullRefName)
            ?: throw IllegalStateException("No reflog found for branch '$refName'")
        val entries: List<org.eclipse.jgit.lib.ReflogEntry> = reflogReader.getReverseEntries()
        if (entries.isEmpty()) {
            throw IllegalStateException("No reflog found for branch '$refName'")
        }

        // Find current position in reflog (search newest first to find most recent match)
        val currentSha = commitId
        var currentIndex: Int? = null
        for (i in entries.indices) {
            if (entries[i].newId == currentSha) {
                currentIndex = i
                break
            }
        }
        if (currentIndex == null) {
            throw IllegalStateException("Cannot redo - current commit not in reflog")
        }

        // Walk backwards N steps in reflog
        var targetSha: ObjectId = currentSha
        var index = currentIndex
        for (step in 0 until steps) {
            if (index < 0) {
                throw IllegalArgumentException("Cannot redo $steps steps - only $step step(s) available")
            }
            targetSha = entries[index].oldId
            if (targetSha == ObjectId.zeroId()) {
                throw IllegalArgumentException("Cannot redo $steps step(s) — reaches branch creation point")
            }
            index--
        }

        val targetFs = Fs(store, targetSha, refName = refName, writable = writable)

        // Atomic stale-check + ref update under lock
        RepoLock.withLock(store.repo.directory.path) {
            val currentRef = store.repo.findRef(fullRefName)
                ?: throw StaleSnapshotError("Branch '$refName' not found")
            if (currentRef.objectId != commitId) {
                throw StaleSnapshotError("Branch '$refName' has advanced since this snapshot")
            }
            val refUpdate = store.repo.updateRef(fullRefName)
            refUpdate.setNewObjectId(targetSha)
            refUpdate.setExpectedOldObjectId(commitId)
            refUpdate.setRefLogMessage("redo: move forward", false)
            refUpdate.isForceUpdate = true
            refUpdate.update()
        }

        return targetFs
    }

    /**
     * Walk the commit history, yielding ancestor Fs snapshots.
     *
     * @param path Only yield commits that changed this file.
     */
    fun log(path: String? = null): List<Fs> {
        val filterPath = if (path != null) normalizePath(path) else null
        val result = mutableListOf<Fs>()
        var current: Fs? = this

        while (current != null) {
            if (filterPath != null) {
                val currentEntry = entryAtPath(store.repo, current.treeId, filterPath)
                val parentFs = current.parent
                val parentEntry = if (parentFs != null) entryAtPath(store.repo, parentFs.treeId, filterPath) else null
                if (currentEntry == parentEntry) {
                    current = current.parent
                    continue
                }
            }
            result.add(current)
            current = current.parent
        }
        return result
    }

    // ── Internal commit ───────────────────────────────────────────────

    /**
     * Commit changes atomically with CAS ref update.
     * @param writes List of (path, TreeWrite?) — null TreeWrite means remove.
     * @param message Custom commit message or null for auto.
     * @param operation Operation name for auto messages.
     */
    internal fun commitChanges(
        writes: List<Pair<String, TreeWrite?>>,
        message: String?,
        operation: String? = null,
    ): Fs {
        if (!writable) throw readonlyError("write to")

        // Build changes report
        val changes = buildChanges(writes)
        val finalMessage = formatCommitMessage(changes, message, operation)

        val fullRefName = "refs/heads/$refName"

        return RepoLock.withLock(store.repo.directory.path) {
            // Stale snapshot check
            val currentRef = store.repo.findRef(fullRefName)
                ?: throw StaleSnapshotError("Branch '$refName' not found")
            if (currentRef.objectId != commitId) {
                throw StaleSnapshotError("Branch '$refName' has advanced since this snapshot")
            }

            val inserter = store.repo.newObjectInserter()
            try {
                // Rebuild tree
                val newTreeId = rebuildTree(store.repo, inserter, treeId, writes)

                // No-op check
                if (newTreeId == treeId) {
                    inserter.flush()
                    return@withLock this
                }

                // Create commit
                val sig = store.signature
                val commit = CommitBuilder()
                commit.setTreeId(newTreeId)
                commit.setParentId(commitId)
                commit.setAuthor(PersonIdent(sig.name, sig.email))
                commit.setCommitter(commit.author)
                commit.setMessage(if (finalMessage.endsWith("\n")) finalMessage else "$finalMessage\n")

                val newCommitId = inserter.insert(commit)
                inserter.flush()

                // CAS ref update
                val refUpdate = store.repo.updateRef(fullRefName)
                refUpdate.setNewObjectId(newCommitId)
                refUpdate.setExpectedOldObjectId(commitId)
                refUpdate.setRefLogMessage("commit: $finalMessage", false)
                refUpdate.update()

                val newFs = Fs(store, newCommitId, refName = refName, writable = writable)
                newFs._changes = changes
                newFs
            } finally {
                inserter.close()
            }
        }
    }

    private fun buildChanges(writes: List<Pair<String, TreeWrite?>>): ChangeReport {
        val addEntries = mutableListOf<FileEntry>()
        val updateEntries = mutableListOf<FileEntry>()
        val deleteEntries = mutableListOf<FileEntry>()

        for ((path, tw) in writes) {
            if (tw != null) {
                // Write
                val existing = entryAtPath(store.repo, treeId, path)
                if (existing != null) {
                    // Check for no-op
                    val (existingOid, existingMode) = existing
                    if (existingOid == tw.oid && existingMode == tw.mode) continue
                    updateEntries.add(FileEntry.fromMode(path, tw.mode))
                } else {
                    addEntries.add(FileEntry.fromMode(path, tw.mode))
                }
            } else {
                // Remove
                val existing = entryAtPath(store.repo, treeId, path)
                if (existing != null) {
                    deleteEntries.add(FileEntry.fromMode(path, existing.second))
                }
            }
        }

        return ChangeReport(add = addEntries, update = updateEntries, delete = deleteEntries)
    }
}

/**
 * Write data to a branch with automatic retry on concurrent modification.
 */
fun retryWrite(
    store: GitStore,
    branch: String,
    path: String,
    data: ByteArray,
    message: String? = null,
    mode: FileType? = null,
    retries: Int = 5,
): Fs {
    for (attempt in 0 until retries) {
        val fs = store.branches[branch]
        try {
            return fs.write(path, data, message, mode)
        } catch (e: StaleSnapshotError) {
            if (attempt == retries - 1) throw e
            val delay = minOf(10L * (1L shl attempt), 200L)
            Thread.sleep((Math.random() * delay).toLong())
        }
    }
    throw StaleSnapshotError("All $retries retries exhausted")
}
