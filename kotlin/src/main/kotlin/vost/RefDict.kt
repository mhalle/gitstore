package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.Ref
import org.eclipse.jgit.revwalk.RevCommit
import org.eclipse.jgit.revwalk.RevTag
import org.eclipse.jgit.revwalk.RevWalk

/**
 * Dict-like access to branches or tags.
 *
 * store.branches and store.tags are both RefDict instances.
 * Supports get, set, delete, contains, list, and iteration.
 */
class RefDict internal constructor(
    private val store: GitStore,
    private val prefix: String,
    private val isTags: Boolean,
) {
    private fun refName(name: String): String = "$prefix$name"

    /**
     * Get an Fs snapshot for the named branch or tag.
     *
     * @param name Branch or tag name.
     * @return Fs snapshot bound to the ref.
     * @throws NoSuchElementException If the ref does not exist.
     */
    operator fun get(name: String): Fs {
        val ref = store.repo.findRef(refName(name))
            ?: throw NoSuchElementException("Not found: $name")

        if (isTags) {
            // Peel through annotated tags to find the commit
            val revWalk = RevWalk(store.repo)
            try {
                var obj = revWalk.parseAny(ref.objectId)
                for (i in 0 until 50) {
                    if (obj is RevCommit) {
                        return Fs(store, obj.toObjectId(), refName = name, writable = false)
                    }
                    if (obj is RevTag) {
                        obj = revWalk.parseAny(obj.getObject().id)
                    } else {
                        throw IllegalStateException("Tag '$name' does not point to a commit")
                    }
                }
                throw IllegalStateException("Tag '$name' does not point to a commit")
            } finally {
                revWalk.close()
            }
        } else {
            return Fs(store, ref.objectId, refName = name, writable = true)
        }
    }

    /**
     * Set branch/tag to point to the given Fs snapshot's commit.
     *
     * @param name Branch or tag name.
     * @param fs Fs snapshot whose commit to point to.
     * @throws IllegalArgumentException If the ref name is invalid or the Fs belongs to a different repository.
     * @throws IllegalStateException If a tag with the given name already exists.
     */
    operator fun set(name: String, fs: Fs) {
        validateRefName(name)
        require(fs.store === store) { "FS belongs to a different repository" }

        val fullRef = refName(name)
        val committer = store.signature

        RepoLock.withLock(store.repo.directory.path) {
            val existingRef = store.repo.findRef(fullRef)
            if (existingRef != null) {
                if (isTags) throw IllegalStateException("Tag '$name' already exists")

                // Update existing branch
                val refUpdate = store.repo.updateRef(fullRef)
                refUpdate.setNewObjectId(fs.commitId)
                refUpdate.setExpectedOldObjectId(existingRef.objectId)
                val commitMsg = readCommitMessage(store.repo, fs.commitId)
                refUpdate.setRefLogMessage("branch: set to $commitMsg", false)
                refUpdate.isForceUpdate = true
                refUpdate.update()
            } else {
                // Create new ref
                val refUpdate = store.repo.updateRef(fullRef)
                refUpdate.setNewObjectId(fs.commitId)
                refUpdate.setExpectedOldObjectId(ObjectId.zeroId())
                val commitMsg = readCommitMessage(store.repo, fs.commitId)
                refUpdate.setRefLogMessage("branch: Created from $commitMsg", false)
                refUpdate.update()
            }
        }
    }

    /**
     * Delete a branch or tag.
     *
     * @param name Branch or tag name.
     * @throws NoSuchElementException If the ref does not exist.
     */
    fun delete(name: String) {
        val fullRef = refName(name)
        RepoLock.withLock(store.repo.directory.path) {
            val ref = store.repo.findRef(fullRef)
                ?: throw NoSuchElementException("Not found: $name")
            val refUpdate = store.repo.updateRef(fullRef)
            refUpdate.setExpectedOldObjectId(ref.objectId)
            refUpdate.isForceUpdate = true
            refUpdate.delete()
        }
    }

    /**
     * Set branch to Fs snapshot and return a new writable Fs bound to it.
     *
     * Convenience method combining set and get:
     * ```
     * val fsNew = store.branches.setAndGet("feature", fs)
     * ```
     *
     * @param name Branch name.
     * @param fs Fs snapshot to set (can be read-only).
     * @return New writable Fs bound to the branch.
     */
    fun setAndGet(name: String, fs: Fs): Fs {
        this[name] = fs
        return this[name]
    }

    /**
     * Check if a branch or tag exists.
     *
     * @param name Branch or tag name.
     * @return True if the ref exists.
     */
    operator fun contains(name: String): Boolean =
        store.repo.findRef(refName(name)) != null

    /**
     * List all branch or tag names.
     *
     * @return List of ref names (without the refs/heads/ or refs/tags/ prefix).
     */
    fun list(): List<String> {
        val allRefs = store.repo.refDatabase.getRefsByPrefix(prefix)
        return allRefs.map { it.name.removePrefix(prefix) }
    }

    /**
     * Check if a ref exists (alias for [contains]).
     *
     * @param name Branch or tag name.
     * @return True if the ref exists.
     */
    fun exists(name: String): Boolean = contains(name)

    /** The number of branches or tags. */
    val size: Int get() = list().size

    /** Iterate over ref names. */
    operator fun iterator(): Iterator<String> = list().iterator()


    // ── Current branch (branches only) ────────────────────────────────

    /** The repository's current (HEAD) branch name, or null if HEAD is dangling. */
    val currentName: String?
        get() {
            if (isTags) throw IllegalStateException("Tags do not have a current branch")
            val headRef = store.repo.findRef(Constants.HEAD) ?: return null
            val target = headRef.target ?: return null
            val targetName = target.name
            return if (targetName.startsWith(prefix)) {
                targetName.removePrefix(prefix)
            } else {
                null
            }
        }

    /** The Fs for the repository's current (HEAD) branch, or null if HEAD is dangling. */
    val current: Fs?
        get() {
            if (isTags) throw IllegalStateException("Tags do not have a current branch")
            val name = currentName ?: return null
            return try {
                this[name]
            } catch (_: NoSuchElementException) {
                null
            }
        }

    /** Set the repository's current (HEAD) branch. */
    fun setCurrent(name: String) {
        if (isTags) throw IllegalStateException("Tags do not have a current branch")
        require(contains(name)) { "Branch not found: '$name'" }
        val refUpdate = store.repo.updateRef(Constants.HEAD)
        refUpdate.link("refs/heads/$name")
    }

    // ── Reflog (branches only) ────────────────────────────────────────

    /** Read reflog entries for a branch. */
    fun reflog(name: String): List<ReflogEntry> {
        if (isTags) throw IllegalStateException("Tags do not have reflog")

        val fullRef = refName(name)
        store.repo.findRef(fullRef) ?: throw NoSuchElementException("Not found: $name")

        val reflogReader = store.repo.getReflogReader(fullRef)
            ?: throw java.io.FileNotFoundException("No reflog found for branch '$name'")

        val entries = reflogReader.getReverseEntries()
        if (entries.isEmpty()) {
            throw java.io.FileNotFoundException("No reflog found for branch '$name'")
        }

        return entries.map { entry: org.eclipse.jgit.lib.ReflogEntry ->
            vost.ReflogEntry(
                oldSha = entry.oldId.name,
                newSha = entry.newId.name,
                committer = "${entry.who.name} <${entry.who.emailAddress}>",
                timestamp = entry.who.whenAsInstant.epochSecond,
                message = entry.comment ?: "",
            )
        }
    }
}

// ── Helpers ───────────────────────────────────────────────────────────

private fun readCommitMessage(repo: org.eclipse.jgit.lib.Repository, commitId: ObjectId): String {
    val revWalk = RevWalk(repo)
    try {
        val commit = revWalk.parseCommit(commitId)
        return commit.shortMessage
    } finally {
        revWalk.close()
    }
}

private fun validateRefName(name: String) {
    if (":" in name) throw IllegalArgumentException("Invalid ref name '$name': contains colon")
    if (name.isEmpty()) throw IllegalArgumentException("Ref name must not be empty")
    if (name.startsWith(".") || name.endsWith(".")) throw IllegalArgumentException("Invalid ref name: '$name'")
    if (name.contains("..")) throw IllegalArgumentException("Invalid ref name: '$name'")
    if (name.contains(" ")) throw IllegalArgumentException("Invalid ref name: '$name'")
    if (name.any { it.code < 0x20 || it == 0x7f.toChar() }) throw IllegalArgumentException("Invalid ref name: '$name'")
    if (name.contains("\\")) throw IllegalArgumentException("Invalid ref name: '$name'")
    if (name.contains("~") || name.contains("^") || name.contains("[")) {
        throw IllegalArgumentException("Invalid ref name: '$name'")
    }
}
