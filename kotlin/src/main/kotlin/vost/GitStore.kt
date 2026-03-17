package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.lib.StoredConfig
import org.eclipse.jgit.storage.file.FileRepositoryBuilder
import java.io.File

/**
 * A versioned filesystem backed by a bare git repository.
 *
 * Open or create a store with [open]. Access snapshots via
 * [branches], [tags], and [notes].
 */
class GitStore private constructor(
    internal val repo: Repository,
    internal val signature: Signature,
) : AutoCloseable {

    /** Dict-like access to branches. */
    val branches = RefDict(this, "refs/heads/", isTags = false)

    /** Dict-like access to tags. */
    val tags = RefDict(this, "refs/tags/", isTags = true)

    /** Git notes namespaces. */
    val notes = NoteDict(this)

    /**
     * Get an Fs snapshot for any ref (branch, tag, or commit hash).
     *
     * Resolution order: branches -> tags -> commit hash.
     * Writable for branches, read-only for tags and hashes.
     *
     * @param ref Branch name, tag name, or commit hash.
     * @param back Walk back N ancestor commits (default 0).
     * @return Fs snapshot for the resolved ref.
     * @throws NoSuchElementException If the ref cannot be resolved.
     */
    fun fs(ref: String, back: Int = 0): Fs {
        val result = when {
            ref in branches -> branches[ref]
            ref in tags -> tags[ref]
            else -> {
                // Try as commit hash
                val objectId = try {
                    ObjectId.fromString(ref)
                } catch (e: Exception) {
                    throw NoSuchElementException("ref not found: '$ref'")
                }
                val revWalk = org.eclipse.jgit.revwalk.RevWalk(repo)
                try {
                    try {
                        revWalk.parseCommit(objectId)
                    } catch (e: Exception) {
                        throw NoSuchElementException("ref not found: '$ref'")
                    }
                    Fs(this, objectId, writable = false)
                } finally {
                    revWalk.close()
                }
            }
        }
        return if (back > 0) result.back(back) else result
    }

    /**
     * Read raw blob data by hash, bypassing tree/ref resolution.
     * Direct object store lookup — the fastest path to blob data.
     *
     * @param hash 40-char hex SHA of the blob.
     * @param offset Byte offset to start reading from.
     * @param size Maximum number of bytes to return (null for all).
     */
    fun readByHash(hash: String, offset: Int = 0, size: Int? = null): ByteArray {
        val oid = ObjectId.fromString(hash)
        val loader = repo.open(oid, Constants.OBJ_BLOB)
        val data = loader.bytes
        if (offset > 0 || size != null) {
            val start = minOf(offset, data.size)
            val end = if (size != null) minOf(start.toLong() + size.toLong(), data.size.toLong()).toInt() else data.size
            return data.copyOfRange(start, end)
        }
        return data
    }

    /**
     * Check if a blob with the given hash exists in the object store.
     *
     * @param hash 40-char hex SHA of the blob.
     * @return true if the blob exists, false otherwise.
     */
    fun hasHash(hash: String): Boolean {
        return try {
            readByHash(hash, size = 0)
            true
        } catch (e: Exception) {
            false
        }
    }

    override fun toString(): String = "GitStore(${repo.directory})"

    override fun close() {
        repo.close()
    }

    /**
     * Push refs to url (or write a bundle file).
     *
     * Without [refs] this is a full mirror: remote-only refs are deleted.
     * With [refs] only the specified refs are pushed (no deletes).
     * With [refMap] refs are renamed during push (keys=source, values=dest);
     * takes precedence over [refs].
     *
     * @param url Destination URL (local path or remote), or bundle file path.
     * @param dryRun If true, compute diff but don't push.
     * @param refs Optional list of ref names to limit the backup to.
     * @param refMap Optional mapping of source ref names to dest ref names.
     * @param format Optional format string; "bundle" forces bundle output.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun backup(
        url: String,
        dryRun: Boolean = false,
        refs: List<String>? = null,
        refMap: Map<String, String>? = null,
        format: String? = null,
        squash: Boolean = false,
    ): MirrorDiff = MirrorOps.backup(this, url, dryRun, refs, refMap, format, squash)

    /**
     * Fetch refs from url (or import a bundle file).
     *
     * Restore is **additive**: it adds and updates refs but never deletes
     * local-only refs.  HEAD (the current branch pointer) is not changed —
     * use `store.branches.setCurrent("name")` afterwards if needed.
     * With [refMap] refs are renamed when written locally (keys=source,
     * values=dest); takes precedence over [refs].
     *
     * @param url Source URL (local path or remote), or bundle file path.
     * @param dryRun If true, compute diff but don't fetch.
     * @param refs Optional list of ref names to limit the restore to.
     * @param refMap Optional mapping of source ref names to dest ref names.
     * @param format Optional format string; "bundle" forces bundle input.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun restore(
        url: String,
        dryRun: Boolean = false,
        refs: List<String>? = null,
        refMap: Map<String, String>? = null,
        format: String? = null,
    ): MirrorDiff = MirrorOps.restore(this, url, dryRun, refs, refMap, format)

    /**
     * Pack loose objects into a packfile.
     *
     * Consolidates loose git objects into a single packfile for better
     * performance and disk usage.  This implementation uses JGit's GC
     * repack which may also perform additional housekeeping.
     *
     * @return Number of objects packed (as reported by the repacker).
     */
    fun pack(): Int {
        val fileRepo = repo as org.eclipse.jgit.internal.storage.file.FileRepository
        val jgitGc = org.eclipse.jgit.internal.storage.file.GC(fileRepo)
        jgitGc.setExpireAgeMillis(Long.MAX_VALUE)  // don't prune
        jgitGc.setPackExpireAgeMillis(Long.MAX_VALUE)
        val looseCount = jgitGc.getStatistics().numberOfLooseObjects
        jgitGc.repack()
        jgitGc.prunePacked()
        return looseCount.toInt()
    }

    /**
     * Run garbage collection: clean up and pack loose objects.
     *
     * Uses JGit's built-in GC which packs loose objects and may
     * prune unreachable objects.
     *
     * @return Number of objects packed.
     */
    fun gc(): Int {
        val fileRepo = repo as org.eclipse.jgit.internal.storage.file.FileRepository
        val jgitGc = org.eclipse.jgit.internal.storage.file.GC(fileRepo)
        val looseCount = jgitGc.getStatistics().numberOfLooseObjects
        jgitGc.gc().get()  // blocking call
        return looseCount.toInt()
    }

    companion object {
        /**
         * Open or create a bare git repository.
         *
         * @param path Path to the bare repository.
         * @param create If true (default), create the repo when it doesn't exist.
         * @param branch Initial branch name when creating (default "main").
         *               Null to create a bare repo with no branches.
         * @param author Default author name for commits.
         * @param email Default author email for commits.
         * @param compression Zlib compression level for git objects (0-9). Null uses the git default.
         * @param bigFileThreshold Blobs larger than this (bytes) skip delta compression. 0 = all blobs skip deltas. Null uses the git default.
         */
        fun open(
            path: String,
            create: Boolean = true,
            branch: String? = "main",
            author: String = "vost",
            email: String = "vost@localhost",
            compression: Int? = null,
            bigFileThreshold: Long? = null,
        ): GitStore {
            val dir = File(path)

            if (dir.exists()) {
                val repo = FileRepositoryBuilder()
                    .setBare()
                    .setGitDir(dir)
                    .build()
                configureForBareRepo(repo)
                applyConfig(repo, compression, bigFileThreshold)
                return GitStore(repo, Signature(author, email))
            }

            if (!create) {
                throw java.io.FileNotFoundException("Repository not found: $path")
            }

            // Create new bare repo
            dir.mkdirs()
            val repo = FileRepositoryBuilder()
                .setBare()
                .setGitDir(dir)
                .build()
            repo.create(true)
            configureForBareRepo(repo)
            applyConfig(repo, compression, bigFileThreshold)

            val store = GitStore(repo, Signature(author, email))

            if (branch != null) {
                val sig = store.signature
                val inserter = repo.newObjectInserter()
                try {
                    // Create empty tree
                    val emptyTreeId = inserter.insert(org.eclipse.jgit.lib.TreeFormatter())

                    // Create initial commit
                    val commit = org.eclipse.jgit.lib.CommitBuilder()
                    commit.setTreeId(emptyTreeId)
                    commit.setAuthor(org.eclipse.jgit.lib.PersonIdent(sig.name, sig.email))
                    commit.setCommitter(commit.author)
                    commit.setMessage("Initialize $branch\n")

                    val commitId = inserter.insert(commit)
                    inserter.flush()

                    // Set the branch ref
                    val refUpdate = repo.updateRef("refs/heads/$branch")
                    refUpdate.setNewObjectId(commitId)
                    refUpdate.setExpectedOldObjectId(ObjectId.zeroId())
                    refUpdate.setRefLogMessage("commit: Initialize $branch", false)
                    refUpdate.update()

                    // Set HEAD to point to this branch
                    val headUpdate = repo.updateRef(Constants.HEAD)
                    headUpdate.link("refs/heads/$branch")
                } finally {
                    inserter.close()
                }
            }

            return store
        }

        /** Configure bare repo to write reflogs (needed for undo/redo). */
        private fun configureForBareRepo(repo: Repository) {
            val config: StoredConfig = repo.config
            config.setString("core", null, "logAllRefUpdates", "always")
            config.save()
        }

        /** Apply compression and bigFileThreshold config to the repository. */
        private fun applyConfig(repo: Repository, compression: Int?, bigFileThreshold: Long?) {
            if (compression == null && bigFileThreshold == null) return
            val config: StoredConfig = repo.config
            if (compression != null) {
                config.setInt("core", null, "compression", compression)
            }
            if (bigFileThreshold != null) {
                config.setLong("core", null, "bigFileThreshold", bigFileThreshold)
            }
            config.save()
        }
    }
}
