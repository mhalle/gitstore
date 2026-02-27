package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.NullProgressMonitor
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.storage.file.FileRepositoryBuilder
import org.eclipse.jgit.transport.*
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

/**
 * Percent-encode a string for use in URL userinfo.
 */
private fun percentEncode(s: String): String {
    val sb = StringBuilder()
    for (b in s.toByteArray(Charsets.UTF_8)) {
        val c = b.toInt() and 0xFF
        if (c in 'A'.code..'Z'.code || c in 'a'.code..'z'.code ||
            c in '0'.code..'9'.code || c == '-'.code || c == '_'.code ||
            c == '.'.code || c == '~'.code
        ) {
            sb.append(c.toChar())
        } else {
            sb.append(String.format("%%%02X", c))
        }
    }
    return sb.toString()
}

/**
 * Inject credentials into an HTTPS URL if available.
 *
 * Tries `git credential fill` first (works with any configured helper:
 * osxkeychain, wincred, libsecret, `gh auth setup-git`, etc.).  Falls
 * back to `gh auth token` for GitHub hosts.  Non-HTTPS URLs and URLs
 * that already contain credentials are returned unchanged.
 *
 * @param url The URL to resolve credentials for.
 * @return The URL with credentials injected, or the original URL.
 */
fun resolveCredentials(url: String): String {
    if (!url.startsWith("https://")) return url

    val afterScheme = url.substring(8) // after "https://"
    val pathStart = afterScheme.indexOf('/').let { if (it < 0) afterScheme.length else it }
    val authority = afterScheme.substring(0, pathStart)

    // Already has credentials
    if ("@" in authority) return url

    val host = authority // may include :port
    val hostname = host.split(":").first()
    val pathAndRest = afterScheme.substring(pathStart)

    // Try git credential fill
    try {
        val proc = ProcessBuilder("git", "credential", "fill")
            .redirectErrorStream(false)
            .start()
        proc.outputStream.write("protocol=https\nhost=$hostname\n\n".toByteArray())
        proc.outputStream.close()
        val output = proc.inputStream.bufferedReader().readText()
        if (proc.waitFor(5, TimeUnit.SECONDS) && proc.exitValue() == 0) {
            val creds = mutableMapOf<String, String>()
            for (line in output.trim().lines()) {
                val eq = line.indexOf('=')
                if (eq > 0) {
                    creds[line.substring(0, eq)] = line.substring(eq + 1).trim()
                }
            }
            val username = creds["username"]
            val password = creds["password"]
            if (username != null && password != null) {
                return "https://${percentEncode(username)}:${percentEncode(password)}@$host$pathAndRest"
            }
        } else {
            proc.destroyForcibly()
        }
    } catch (_: Exception) {
    }

    // Fallback: gh auth token (GitHub-specific)
    try {
        val proc = ProcessBuilder("gh", "auth", "token", "--hostname", hostname)
            .redirectErrorStream(false)
            .start()
        val token = proc.inputStream.bufferedReader().readText().trim()
        if (proc.waitFor(5, TimeUnit.SECONDS) && proc.exitValue() == 0 && token.isNotEmpty()) {
            return "https://x-access-token:$token@$host$pathAndRest"
        } else {
            proc.destroyForcibly()
        }
    } catch (_: Exception) {
    }

    return url
}

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
     * Without [refs] this is a full mirror: remote-only refs are deleted.
     * With [refs] only the specified refs are pushed (no deletes).
     *
     * @param store The GitStore to back up.
     * @param url Destination URL (local path or remote URL), or bundle file path.
     * @param dryRun If true, compute diff but don't push.
     * @param refs Optional list of ref names to limit the backup to.
     * @param format Optional format string; "bundle" forces bundle output.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun backup(
        store: GitStore,
        url: String,
        dryRun: Boolean = false,
        refs: List<String>? = null,
        format: String? = null,
    ): MirrorDiff {
        val repo = store.repo
        val useBundle = format == "bundle" || isBundlePath(url)

        if (useBundle) {
            val diff = diffBundleExport(repo, refs)
            if (!dryRun) {
                bundleExport(repo, url, refs)
            }
            return diff
        }

        // Auto-create bare repo for local push targets
        autoCreateBareRepo(url)

        if (refs != null) {
            val localRefs = getLocalRefs(repo)
            val remoteRefs = getRemoteRefs(repo, url)
            val refSet = resolveRefNames(refs, localRefs.keys)
            val fullDiff = diffRefs(localRefs, remoteRefs)
            // Filter to only targeted refs, no deletes
            val diff = MirrorDiff(
                add = fullDiff.add.filter { it.refName in refSet },
                update = fullDiff.update.filter { it.refName in refSet },
                delete = emptyList(),
            )
            if (!dryRun && !diff.inSync) {
                targetedPush(repo, url, localRefs, refSet)
            }
            return diff
        }

        val localRefs = getLocalRefs(repo)
        val remoteRefs = getRemoteRefs(repo, url)
        val diff = diffRefs(localRefs, remoteRefs)

        if (!dryRun && !diff.inSync) {
            mirrorPush(repo, url, localRefs, remoteRefs)
        }

        return diff
    }

    /**
     * Fetch refs from url additively (no deletes).
     *
     * Restore is **additive**: it adds and updates refs but never deletes
     * local-only refs.
     *
     * @param store The GitStore to restore into.
     * @param url Source URL (local path or remote), or bundle file path.
     * @param dryRun If true, compute diff but don't fetch.
     * @param refs Optional list of ref names to limit the restore to.
     * @param format Optional format string; "bundle" forces bundle input.
     * @return MirrorDiff describing what changed (or would change).
     */
    fun restore(
        store: GitStore,
        url: String,
        dryRun: Boolean = false,
        refs: List<String>? = null,
        format: String? = null,
    ): MirrorDiff {
        val repo = store.repo
        val useBundle = format == "bundle" || isBundlePath(url)

        if (useBundle) {
            val diff = diffBundleImport(repo, url, refs)
            if (!dryRun) {
                bundleImport(repo, url, refs)
            }
            return diff
        }

        val localRefs = getLocalRefs(repo)
        val remoteRefs = getRemoteRefs(repo, url)
        // For restore, remote is source, local is destination
        var diff = diffRefs(remoteRefs, localRefs)

        if (refs != null) {
            val refSet = resolveRefNames(refs, remoteRefs.keys)
            diff = MirrorDiff(
                add = diff.add.filter { it.refName in refSet },
                update = diff.update.filter { it.refName in refSet },
                delete = emptyList(), // additive: never delete
            )
        } else {
            diff = diff.copy(delete = emptyList()) // additive: never delete
        }

        if (!dryRun && !diff.inSync) {
            additiveFetch(repo, url, remoteRefs, refs)
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
     * Fetch all remote refs, overwriting local state (destructive — deletes stale).
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
     * Push only refs in [refFilter] to url (no deletes).
     */
    private fun targetedPush(
        repo: Repository,
        url: String,
        localRefs: Map<String, String>,
        refFilter: Set<String>,
    ) {
        val transport = Transport.open(repo, URIish(url))
        try {
            val commands = mutableListOf<RemoteRefUpdate>()
            for (refName in refFilter) {
                val sha = localRefs[refName] ?: continue
                val oid = ObjectId.fromString(sha)
                commands.add(
                    RemoteRefUpdate(
                        repo,
                        null as String?,
                        oid,
                        refName,
                        true,
                        null,
                        null,
                    )
                )
            }
            if (commands.isNotEmpty()) {
                transport.push(NullProgressMonitor.INSTANCE, commands)
            }
        } finally {
            transport.close()
        }
    }

    /**
     * Fetch refs from url additively (no deletes).
     *
     * If [refs] is given, only those refs are fetched.
     */
    private fun additiveFetch(
        repo: Repository,
        url: String,
        remoteRefs: Map<String, String>,
        refs: List<String>?,
    ) {
        val refsToFetch: Set<String> = if (refs != null) {
            resolveRefNames(refs, remoteRefs.keys)
        } else {
            remoteRefs.keys.toSet()
        }

        val refSpecs = refsToFetch.filter { it in remoteRefs }.map { RefSpec("+$it:$it") }

        if (refSpecs.isNotEmpty()) {
            val transport = Transport.open(repo, URIish(url))
            try {
                transport.fetch(NullProgressMonitor.INSTANCE, refSpecs)
            } finally {
                transport.close()
            }
        }
        // No deletes — additive
    }

    // ── Bundle helpers ──────────────────────────────────────────────────

    /**
     * Return true if [path] has a `.bundle` extension.
     */
    private fun isBundlePath(path: String): Boolean =
        path.lowercase().endsWith(".bundle")

    /**
     * Resolve short ref names to full ref paths.
     *
     * Tries `refs/heads/`, `refs/tags/`, `refs/notes/` prefixes against
     * [available].  Full paths (starting with `refs/`) pass through
     * unchanged.  If no match is found the name is assumed to be a branch.
     */
    private fun resolveRefNames(names: List<String>, available: Set<String>): Set<String> {
        val result = mutableSetOf<String>()
        for (name in names) {
            if (name.startsWith("refs/")) {
                result.add(name)
                continue
            }
            var found = false
            for (prefix in listOf("refs/heads/", "refs/tags/", "refs/notes/")) {
                val candidate = "$prefix$name"
                if (candidate in available) {
                    result.add(candidate)
                    found = true
                    break
                }
            }
            if (!found) {
                result.add("refs/heads/$name")
            }
        }
        return result
    }

    /**
     * Create a bundle file from local refs.
     */
    private fun bundleExport(repo: Repository, path: String, refs: List<String>?) {
        val allRefs = getLocalRefs(repo)
        val refsToExport: Set<String> = if (refs != null) {
            resolveRefNames(refs, allRefs.keys)
        } else {
            allRefs.keys.toSet()
        }

        val writer = BundleWriter(repo)
        for (refName in refsToExport) {
            val sha = allRefs[refName] ?: continue
            writer.include(refName, ObjectId.fromString(sha))
        }
        FileOutputStream(path).use { fos ->
            writer.writeBundle(NullProgressMonitor.INSTANCE, fos)
        }
    }

    /**
     * Import refs from a bundle file (additive — no deletes).
     */
    private fun bundleImport(repo: Repository, path: String, refs: List<String>?) {
        val bundleRefs = bundleListHeads(repo, path)
        val refsToImport: Map<String, String> = if (refs != null) {
            val resolved = resolveRefNames(refs, bundleRefs.keys)
            bundleRefs.filterKeys { it in resolved }
        } else {
            bundleRefs
        }

        if (refsToImport.isEmpty()) return

        val refSpecs = refsToImport.keys.map { RefSpec("+$it:$it") }
        val uri = URIish(File(path).toURI().toString())
        val transport = Transport.open(repo, uri)
        try {
            transport.fetch(NullProgressMonitor.INSTANCE, refSpecs)
        } finally {
            transport.close()
        }
    }

    /**
     * List refs in a bundle file.
     */
    private fun bundleListHeads(repo: Repository, path: String): Map<String, String> {
        val uri = URIish(File(path).toURI().toString())
        val transport = Transport.open(repo, uri)
        val result = mutableMapOf<String, String>()
        try {
            val connection = transport.openFetch()
            try {
                for ((name, ref) in connection.refsMap) {
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
        return result
    }

    /**
     * Compute diff for exporting a bundle (all refs are 'add').
     */
    private fun diffBundleExport(repo: Repository, refs: List<String>?): MirrorDiff {
        val localRefs = getLocalRefs(repo)
        val filtered = if (refs != null) {
            val resolved = resolveRefNames(refs, localRefs.keys)
            localRefs.filterKeys { it in resolved }
        } else {
            localRefs
        }
        return MirrorDiff(
            add = filtered.map { (refName, sha) ->
                RefChange(refName = refName, oldTarget = null, newTarget = sha)
            },
        )
    }

    /**
     * Compute diff for importing a bundle (additive — no deletes).
     */
    private fun diffBundleImport(repo: Repository, path: String, refs: List<String>?): MirrorDiff {
        val bundleRefs = bundleListHeads(repo, path)
        val filtered = if (refs != null) {
            val resolved = resolveRefNames(refs, bundleRefs.keys)
            bundleRefs.filterKeys { it in resolved }
        } else {
            bundleRefs
        }
        val localRefs = getLocalRefs(repo)
        val diff = diffRefs(filtered, localRefs)
        // Additive: no deletes
        return diff.copy(delete = emptyList())
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
