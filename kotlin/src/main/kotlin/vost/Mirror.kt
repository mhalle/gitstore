package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.NullProgressMonitor
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.storage.file.FileRepositoryBuilder
import org.eclipse.jgit.transport.*
import java.io.File

/**
 * Mirror (backup/restore) operations for vost.
 *
 * Ref-level mirroring: push all local refs to a remote (backup) or fetch
 * all remote refs to local (restore).
 */
internal object MirrorOps {

    /**
     * Push all local refs to url, creating an exact mirror.
     *
     * @param store The GitStore to back up.
     * @param url Destination URL (local path or remote URL).
     * @param dryRun If true, compute diff but don't push.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun backup(store: GitStore, url: String, dryRun: Boolean = false): MirrorDiff {
        val repo = store.repo

        // Auto-create bare repo for local push targets
        autoCreateBareRepo(url)

        val localRefs = getLocalRefs(repo)
        val remoteRefs = getRemoteRefs(repo, url)
        val diff = diffRefs(localRefs, remoteRefs)

        if (!dryRun && !diff.inSync) {
            mirrorPush(repo, url, localRefs, remoteRefs)
        }

        return diff
    }

    /**
     * Fetch all refs from url, overwriting local state.
     *
     * @param store The GitStore to restore into.
     * @param url Source URL (local path or remote).
     * @param dryRun If true, compute diff but don't fetch.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun restore(store: GitStore, url: String, dryRun: Boolean = false): MirrorDiff {
        val repo = store.repo
        val localRefs = getLocalRefs(repo)
        val remoteRefs = getRemoteRefs(repo, url)
        // For restore, remote is source, local is destination
        val diff = diffRefs(remoteRefs, localRefs)

        if (!dryRun && !diff.inSync) {
            mirrorFetch(repo, url, remoteRefs, localRefs)
        }

        return diff
    }

    // ── Internal helpers ─────────────────────────────────────────────

    /**
     * Get all local refs (excluding HEAD) as {refName: sha_hex}.
     */
    private fun getLocalRefs(repo: Repository): Map<String, String> {
        val result = mutableMapOf<String, String>()
        for (ref in repo.refDatabase.refs) {
            val name = ref.name
            if (name == Constants.HEAD) continue
            val peeled = repo.refDatabase.peel(ref)
            val oid = peeled.peeledObjectId ?: peeled.objectId ?: continue
            result[name] = oid.name
        }
        return result
    }

    /**
     * Get all remote refs (excluding HEAD and ^{} markers) as {refName: sha_hex}.
     */
    private fun getRemoteRefs(repo: Repository, url: String): Map<String, String> {
        val result = mutableMapOf<String, String>()
        try {
            val transport = Transport.open(repo, URIish(url))
            try {
                val connection = transport.openFetch()
                try {
                    val refs = connection.refsMap
                    for ((name, ref) in refs) {
                        if (name == Constants.HEAD) continue
                        if (name.endsWith("^{}")) continue
                        val oid = ref.objectId ?: continue
                        result[name] = oid.name
                    }
                } finally {
                    connection.close()
                }
            } finally {
                transport.close()
            }
        } catch (_: Exception) {
            // Remote doesn't exist or is inaccessible — treat as empty
        }
        return result
    }

    /**
     * Compare source and destination refs, producing a MirrorDiff.
     *
     * @param src The source refs (what we want the dest to look like).
     * @param dest The destination refs (current state).
     */
    private fun diffRefs(src: Map<String, String>, dest: Map<String, String>): MirrorDiff {
        val add = mutableListOf<RefChange>()
        val update = mutableListOf<RefChange>()
        val delete = mutableListOf<RefChange>()

        for ((ref, sha) in src) {
            if (ref !in dest) {
                add.add(RefChange(refName = ref, oldTarget = null, newTarget = sha))
            } else if (dest[ref] != sha) {
                update.add(RefChange(refName = ref, oldTarget = dest[ref], newTarget = sha))
            }
        }

        for ((ref, sha) in dest) {
            if (ref !in src) {
                delete.add(RefChange(refName = ref, oldTarget = sha, newTarget = null))
            }
        }

        return MirrorDiff(add = add, update = update, delete = delete)
    }

    /**
     * Push all local refs to remote, force-updating and deleting stale refs.
     */
    private fun mirrorPush(
        repo: Repository,
        url: String,
        localRefs: Map<String, String>,
        remoteRefs: Map<String, String>,
    ) {
        val transport = Transport.open(repo, URIish(url))
        try {
            val commands = mutableListOf<RemoteRefUpdate>()

            // Push all local refs (force)
            for ((refName, sha) in localRefs) {
                val oid = ObjectId.fromString(sha)
                commands.add(
                    RemoteRefUpdate(
                        repo,
                        null as String?,  // source ref name
                        oid,
                        refName,          // remote ref name
                        true,             // force update
                        null,             // tracking ref
                        null,             // expected old object id
                    )
                )
            }

            // Delete stale remote refs
            for (refName in remoteRefs.keys) {
                if (refName !in localRefs) {
                    commands.add(
                        RemoteRefUpdate(
                            repo,
                            null as String?,
                            ObjectId.zeroId(),
                            refName,
                            true,
                            null,
                            null,
                        )
                    )
                }
            }

            if (commands.isNotEmpty()) {
                transport.push(NullProgressMonitor.INSTANCE, commands)
            }
        } finally {
            transport.close()
        }
    }

    /**
     * Fetch all remote refs, overwriting local state.
     */
    private fun mirrorFetch(
        repo: Repository,
        url: String,
        remoteRefs: Map<String, String>,
        localRefs: Map<String, String>,
    ) {
        // Build fetch ref specs for all remote refs
        val refSpecs = remoteRefs.keys.map { refName ->
            RefSpec("+$refName:$refName")
        }

        if (refSpecs.isNotEmpty()) {
            val transport = Transport.open(repo, URIish(url))
            try {
                transport.fetch(NullProgressMonitor.INSTANCE, refSpecs)
            } finally {
                transport.close()
            }
        }

        // Delete local refs that are not on remote
        for (refName in localRefs.keys) {
            if (refName !in remoteRefs) {
                val refUpdate = repo.updateRef(refName)
                refUpdate.isForceUpdate = true
                refUpdate.delete()
            }
        }
    }

    /**
     * Auto-create a bare git repo at a local path if it doesn't exist.
     */
    private fun autoCreateBareRepo(url: String) {
        // Only for local paths (not remote URLs)
        if (url.startsWith("http://") || url.startsWith("https://") ||
            url.startsWith("git://") || url.startsWith("ssh://")) {
            return
        }

        val path = if (url.startsWith("file://")) url.removePrefix("file://") else url

        // Detect scp-style URLs
        if ("@" in url && ":" in url.split("@", limit = 2)[1]) return
        val colonIdx = url.indexOf(':')
        if (colonIdx > 1) {
            val prefix = url.substring(0, colonIdx)
            if ('/' !in prefix && '\\' !in prefix) return
        }

        val dir = File(path)
        if (dir.exists()) return

        // Create bare repo
        dir.mkdirs()
        val repo = FileRepositoryBuilder()
            .setBare()
            .setGitDir(dir)
            .build()
        repo.create(true)
        repo.close()
    }
}
