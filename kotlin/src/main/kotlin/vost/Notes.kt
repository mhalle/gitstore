package vost

import org.eclipse.jgit.lib.CommitBuilder
import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.FileMode
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.lib.TreeFormatter
import org.eclipse.jgit.revwalk.RevWalk
import org.eclipse.jgit.treewalk.TreeWalk

private val HEX40_RE = Regex("^[0-9a-f]{40}$")

private fun validateHash(h: String) {
    if (!HEX40_RE.matches(h)) {
        throw IllegalArgumentException("Invalid commit hash: '$h' (must be 40-char lowercase hex)")
    }
}

/**
 * One git notes namespace, backed by `refs/notes/<name>`.
 *
 * Maps 40-char hex commit hashes to UTF-8 note text.
 */
class NoteNamespace internal constructor(
    internal val store: GitStore,
    internal val namespace: String,
) {
    internal val ref = "refs/notes/$namespace"

    override fun toString(): String = "NoteNamespace('$namespace')"

    // ── Internal helpers ──────────────────────────────────────────────

    internal fun tipOid(): ObjectId? {
        val r = store.repo.findRef(ref) ?: return null
        return r.objectId
    }

    internal fun treeOid(): ObjectId? {
        val tip = tipOid() ?: return null
        val revWalk = RevWalk(store.repo)
        try {
            val commit = revWalk.parseCommit(tip)
            return commit.tree.id
        } finally {
            revWalk.close()
        }
    }

    /**
     * Find the blob OID for hash h in the tree, handling flat and 2/38 fanout.
     */
    private fun findNoteInTree(treeOid: ObjectId, h: String): ObjectId? {
        val tw = TreeWalk(store.repo)
        try {
            tw.addTree(treeOid)
            tw.isRecursive = false
            while (tw.next()) {
                val name = tw.nameString
                val mode = tw.getRawMode(0)
                val oid = tw.getObjectId(0)
                if (name == h && mode != FileMode.TREE.bits) {
                    return oid
                }
                if (name == h.substring(0, 2) && mode == FileMode.TREE.bits) {
                    // 2/38 fanout
                    val suffix = h.substring(2)
                    val subTw = TreeWalk(store.repo)
                    try {
                        subTw.addTree(oid)
                        subTw.isRecursive = false
                        while (subTw.next()) {
                            if (subTw.nameString == suffix) {
                                return subTw.getObjectId(0)
                            }
                        }
                    } finally {
                        subTw.close()
                    }
                }
            }
        } finally {
            tw.close()
        }
        return null
    }

    /**
     * Iterate all notes in the tree, yielding (hash, blob_oid) pairs.
     */
    internal fun iterNotes(treeOid: ObjectId): List<Pair<String, ObjectId>> {
        val result = mutableListOf<Pair<String, ObjectId>>()
        val tw = TreeWalk(store.repo)
        try {
            tw.addTree(treeOid)
            tw.isRecursive = false
            while (tw.next()) {
                val name = tw.nameString
                val mode = tw.getRawMode(0)
                val oid = tw.getObjectId(0)
                if (mode == FileMode.TREE.bits && name.length == 2) {
                    // Fanout subtree
                    val subTw = TreeWalk(store.repo)
                    try {
                        subTw.addTree(oid)
                        subTw.isRecursive = false
                        while (subTw.next()) {
                            val fullHash = name + subTw.nameString
                            if (HEX40_RE.matches(fullHash)) {
                                result.add(Pair(fullHash, subTw.getObjectId(0)))
                            }
                        }
                    } finally {
                        subTw.close()
                    }
                } else if (HEX40_RE.matches(name)) {
                    result.add(Pair(name, oid))
                }
            }
        } finally {
            tw.close()
        }
        return result
    }

    /**
     * Build a tree with the given flat entries (all entries at root level).
     */
    internal fun buildNoteTree(entries: Map<String, ObjectId>): ObjectId {
        val inserter = store.repo.newObjectInserter()
        try {
            val formatter = TreeFormatter()
            for ((name, oid) in entries.toSortedMap()) {
                formatter.append(name, FileMode.REGULAR_FILE, oid)
            }
            val treeOid = inserter.insert(formatter)
            inserter.flush()
            return treeOid
        } finally {
            inserter.close()
        }
    }

    /**
     * Commit a new note tree to the notes ref under lock.
     */
    internal fun commitNoteTree(newTreeOid: ObjectId, message: String) {
        val sig = store.signature
        RepoLock.withLock(store.repo.directory.path) {
            val inserter = store.repo.newObjectInserter()
            try {
                val commit = CommitBuilder()
                commit.setTreeId(newTreeOid)
                val tip = tipOid()
                if (tip != null) {
                    commit.setParentId(tip)
                }
                commit.setAuthor(PersonIdent(sig.name, sig.email))
                commit.setCommitter(commit.author)
                commit.setMessage(if (message.endsWith("\n")) message else "$message\n")
                val commitOid = inserter.insert(commit)
                inserter.flush()

                val refUpdate = store.repo.updateRef(ref)
                refUpdate.setNewObjectId(commitOid)
                if (tip != null) {
                    refUpdate.setExpectedOldObjectId(tip)
                } else {
                    refUpdate.setExpectedOldObjectId(ObjectId.zeroId())
                }
                refUpdate.setRefLogMessage("notes: $message", false)
                refUpdate.isForceUpdate = true
                refUpdate.update()
            } finally {
                inserter.close()
            }
        }
    }

    // ── Target resolution ────────────────────────────────────────────

    /**
     * Resolve [target] to a 40-char commit hash.
     * Accepts a 40-char hex hash (returned as-is), a branch name, or a tag name.
     */
    internal fun resolveTarget(target: String): String {
        if (HEX40_RE.matches(target)) return target
        if (target in store.branches) return store.branches[target].commitHash
        if (target in store.tags) return store.tags[target].commitHash
        throw IllegalArgumentException(
            "Cannot resolve '$target': not a commit hash, branch, or tag"
        )
    }

    internal fun resolveTarget(fs: Fs): String = fs.commitHash

    // ── Public API ────────────────────────────────────────────────────

    /**
     * Get the note text for an Fs snapshot.
     *
     * @param fs Snapshot whose commit to look up.
     * @return The note text.
     * @throws NoSuchElementException If no note exists for this commit.
     */
    operator fun get(fs: Fs): String = get(fs.commitHash)

    /**
     * Get the note text for a commit hash or ref name (branch/tag).
     *
     * @param target 40-char hex commit hash, branch name, or tag name.
     * @return The note text.
     * @throws NoSuchElementException If no note exists for the resolved commit.
     * @throws IllegalArgumentException If [target] cannot be resolved.
     */
    operator fun get(target: String): String {
        val h = resolveTarget(target)
        val treeOid = treeOid() ?: throw NoSuchElementException(h)
        val blobOid = findNoteInTree(treeOid, h) ?: throw NoSuchElementException(h)
        val loader = store.repo.open(blobOid, Constants.OBJ_BLOB)
        return String(loader.bytes, Charsets.UTF_8)
    }

    /**
     * Set the note text for an Fs snapshot.
     *
     * @param fs Snapshot whose commit to annotate.
     * @param text Note text to set.
     */
    operator fun set(fs: Fs, text: String) = set(fs.commitHash, text)

    /**
     * Set the note text for a commit hash or ref name (branch/tag).
     *
     * @param target 40-char hex commit hash, branch name, or tag name.
     * @param text Note text to set.
     * @throws IllegalArgumentException If [target] cannot be resolved.
     */
    operator fun set(target: String, text: String) {
        val h = resolveTarget(target)

        // Read existing tree entries into a flat map
        val entries = mutableMapOf<String, ObjectId>()
        val treeOid = treeOid()
        if (treeOid != null) {
            for ((hash, blobOid) in iterNotes(treeOid)) {
                entries[hash] = blobOid
            }
        }

        // Insert new blob
        val inserter = store.repo.newObjectInserter()
        try {
            val blobOid = inserter.insert(Constants.OBJ_BLOB, text.toByteArray(Charsets.UTF_8))
            inserter.flush()
            entries[h] = blobOid
        } finally {
            inserter.close()
        }

        val newTreeOid = buildNoteTree(entries)
        commitNoteTree(newTreeOid, "Notes added by 'git notes' on ${h.substring(0, 7)}")
    }

    /**
     * Delete the note for an Fs snapshot.
     *
     * @param fs Snapshot whose note to delete.
     * @throws NoSuchElementException If no note exists for this commit.
     */
    fun delete(fs: Fs) = delete(fs.commitHash)

    /**
     * Delete the note for a commit hash or ref name (branch/tag).
     *
     * @param target 40-char hex commit hash, branch name, or tag name.
     * @throws NoSuchElementException If no note exists for the resolved commit.
     * @throws IllegalArgumentException If [target] cannot be resolved.
     */
    fun delete(target: String) {
        val h = resolveTarget(target)
        val treeOid = treeOid() ?: throw NoSuchElementException(h)

        val entries = mutableMapOf<String, ObjectId>()
        for ((hash, blobOid) in iterNotes(treeOid)) {
            entries[hash] = blobOid
        }

        if (h !in entries) throw NoSuchElementException(h)
        entries.remove(h)

        val newTreeOid = buildNoteTree(entries)
        commitNoteTree(newTreeOid, "Notes removed by 'git notes' on ${h.substring(0, 7)}")
    }

    /**
     * Check if a note exists for an Fs snapshot.
     *
     * @param fs Snapshot to check.
     * @return True if a note exists for this commit.
     */
    operator fun contains(fs: Fs): Boolean = contains(fs.commitHash)

    /**
     * Check if a note exists for a commit hash or ref name (branch/tag).
     *
     * @param target 40-char hex commit hash, branch name, or tag name.
     * @return True if a note exists for the resolved commit.
     */
    operator fun contains(target: String): Boolean {
        val h = try { resolveTarget(target) } catch (_: IllegalArgumentException) { return false }
        val treeOid = treeOid() ?: return false
        return findNoteInTree(treeOid, h) != null
    }

    /** Return all commit hashes that have notes in this namespace. */
    fun keys(): List<String> {
        val treeOid = treeOid() ?: return emptyList()
        return iterNotes(treeOid).map { it.first }
    }

    /** Return the number of notes. */
    fun size(): Int {
        val treeOid = treeOid() ?: return 0
        return iterNotes(treeOid).size
    }

    // ── for_current_branch ────────────────────────────────────────────

    /** Get the note for the current HEAD commit. */
    fun getForCurrentBranch(): String {
        val currentFs = store.branches.current
            ?: throw IllegalStateException("HEAD is dangling - no current branch")
        return get(currentFs.commitHash)
    }

    /**
     * Set the note for the current HEAD commit.
     *
     * @param text Note text to set.
     * @throws IllegalStateException If HEAD is dangling (no current branch).
     */
    fun setForCurrentBranch(text: String) {
        val currentFs = store.branches.current
            ?: throw IllegalStateException("HEAD is dangling - no current branch")
        set(currentFs.commitHash, text)
    }

    // ── Batch ─────────────────────────────────────────────────────────

    /**
     * Return a [NotesBatch] context manager that batches writes into a single commit.
     *
     * @return A new [NotesBatch] instance.
     */
    fun batch(): NotesBatch = NotesBatch(this)
}

/**
 * Batches note writes/deletes into a single commit.
 */
class NotesBatch internal constructor(
    private val ns: NoteNamespace,
) : AutoCloseable {

    private val writes = mutableMapOf<String, String>()
    private val deletes = mutableSetOf<String>()
    private var closed = false

    /**
     * Stage a note write for an Fs snapshot.
     *
     * @param fs Snapshot whose commit to annotate.
     * @param text Note text to set.
     */
    operator fun set(fs: Fs, text: String) = set(fs.commitHash, text)

    /**
     * Stage a note write.
     *
     * @param target Commit hash or ref name (branch/tag).
     * @param text Note text to set.
     */
    operator fun set(target: String, text: String) {
        val h = ns.resolveTarget(target)
        deletes.remove(h)
        writes[h] = text
    }

    /**
     * Stage a note deletion for an Fs snapshot.
     *
     * @param fs Snapshot whose note to delete.
     */
    fun delete(fs: Fs) = delete(fs.commitHash)

    /**
     * Stage a note deletion.
     *
     * @param target Commit hash or ref name (branch/tag).
     * @throws NoSuchElementException If the note does not exist when committed.
     */
    fun delete(target: String) {
        val h = ns.resolveTarget(target)
        writes.remove(h)
        deletes.add(h)
    }

    /**
     * Explicitly commit the batch.
     *
     * After calling this the batch is closed and no further writes are allowed.
     */
    fun commit() {
        if (closed) throw IllegalStateException("NotesBatch is already closed")
        closed = true
        if (writes.isEmpty() && deletes.isEmpty()) return
        flush()
    }

    override fun close() {
        if (!closed) commit()
    }

    private fun flush() {
        val store = ns.store
        val repo = store.repo

        // Read existing entries
        val entries = mutableMapOf<String, ObjectId>()
        val treeOid = ns.treeOid()
        if (treeOid != null) {
            for ((hash, blobOid) in ns.iterNotes(treeOid)) {
                entries[hash] = blobOid
            }
        }

        // Apply deletes
        for (h in deletes) {
            if (h !in entries) throw NoSuchElementException(h)
            entries.remove(h)
        }

        // Apply writes
        val inserter = repo.newObjectInserter()
        try {
            for ((h, text) in writes) {
                val blobOid = inserter.insert(Constants.OBJ_BLOB, text.toByteArray(Charsets.UTF_8))
                entries[h] = blobOid
            }
            inserter.flush()
        } finally {
            inserter.close()
        }

        val newTreeOid = ns.buildNoteTree(entries)
        val count = writes.size + deletes.size
        ns.commitNoteTree(newTreeOid, "Notes batch update ($count changes)")
    }
}

/**
 * Outer container for git notes namespaces on a GitStore.
 *
 * `store.notes.commits` → default namespace (`refs/notes/commits`).
 * `store.notes["reviews"]` → custom namespace.
 */
class NoteDict internal constructor(
    private val store: GitStore,
) {
    override fun toString(): String = "NoteDict($store)"

    /**
     * Get a [NoteNamespace] by name.
     *
     * @param namespace Namespace name (e.g. "reviews"). Maps to `refs/notes/<namespace>`.
     */
    operator fun get(namespace: String): NoteNamespace = NoteNamespace(store, namespace)

    /** The default `refs/notes/commits` namespace. */
    val commits: NoteNamespace get() = NoteNamespace(store, "commits")
}
