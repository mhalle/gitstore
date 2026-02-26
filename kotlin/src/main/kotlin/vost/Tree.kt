package vost

import org.eclipse.jgit.lib.Constants
import org.eclipse.jgit.lib.FileMode
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.ObjectInserter
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.lib.TreeFormatter
import org.eclipse.jgit.revwalk.RevWalk
import org.eclipse.jgit.treewalk.TreeWalk

// ── Path helpers ──────────────────────────────────────────────────────

/** Return true if path represents the root (empty or only slashes). */
internal fun isRootPath(path: String): Boolean =
    path.replace("\\", "/").trim('/').isEmpty()

/**
 * Normalize a path: strip leading/trailing slashes, reject bad segments.
 * @throws IllegalArgumentException on empty, ".", "..", or double-slash paths.
 */
internal fun normalizePath(path: String): String {
    val p = path.replace("\\", "/").trim('/')
    if (p.isEmpty()) throw IllegalArgumentException("Path must not be empty")
    val segments = p.split("/")
    for (seg in segments) {
        if (seg.isEmpty()) throw IllegalArgumentException("Empty segment in path: '$path'")
        if (seg == "." || seg == "..") throw IllegalArgumentException("Invalid path segment: '$seg'")
    }
    return segments.joinToString("/")
}

// ── Tree read helpers ─────────────────────────────────────────────────

/**
 * Return (objectId, fileMode) of the entry at path, or null if missing.
 */
internal fun entryAtPath(repo: Repository, treeId: ObjectId, path: String): Pair<ObjectId, Int>? {
    val segments = path.split("/")
    var currentTreeId = treeId

    for ((i, seg) in segments.withIndex()) {
        val tw = TreeWalk(repo)
        try {
            tw.addTree(currentTreeId)
            tw.isRecursive = false
            var found = false
            while (tw.next()) {
                if (tw.nameString == seg) {
                    found = true
                    val entryMode = tw.getRawMode(0)
                    val entryId = tw.getObjectId(0)
                    if (i < segments.size - 1) {
                        // Not the last segment — must be a tree
                        if (entryMode != FileMode.TREE.bits) return null
                        currentTreeId = entryId
                    } else {
                        return Pair(entryId, entryMode)
                    }
                    break
                }
            }
            if (!found) return null
        } finally {
            tw.close()
        }
    }
    return null
}

/**
 * Walk tree to the object at the given path, returning (objectId, mode).
 * @throws java.io.FileNotFoundException if path does not exist.
 * @throws NotADirectoryException if an intermediate is not a tree.
 */
internal fun walkTo(repo: Repository, treeId: ObjectId, path: String): Pair<ObjectId, Int> {
    val segments = path.split("/")
    var currentId = treeId
    var currentMode = FileMode.TREE.bits

    for ((i, seg) in segments.withIndex()) {
        if (currentMode != FileMode.TREE.bits) {
            val partial = segments.subList(0, i).joinToString("/")
            throw NotADirectoryError(partial)
        }
        val tw = TreeWalk(repo)
        try {
            tw.addTree(currentId)
            tw.isRecursive = false
            var found = false
            while (tw.next()) {
                if (tw.nameString == seg) {
                    found = true
                    currentId = tw.getObjectId(0)
                    currentMode = tw.getRawMode(0)
                    break
                }
            }
            if (!found) throw java.io.FileNotFoundException(path)
        } finally {
            tw.close()
        }
    }
    return Pair(currentId, currentMode)
}

/** @deprecated Use NotADirectoryError instead. */
typealias NotADirectoryException = NotADirectoryError
/** @deprecated Use IsADirectoryError instead. */
typealias IsADirectoryException = IsADirectoryError

/**
 * Read blob bytes at the given path in the tree.
 * @throws java.io.FileNotFoundException if path does not exist.
 * @throws IsADirectoryException if path is a directory.
 */
internal fun readBlobAtPath(repo: Repository, treeId: ObjectId, path: String): ByteArray {
    val normalized = normalizePath(path)
    val (objId, mode) = walkTo(repo, treeId, normalized)
    if (mode == FileMode.TREE.bits) throw IsADirectoryError(normalized)
    val loader = repo.open(objId, Constants.OBJ_BLOB)
    return loader.bytes
}

/**
 * List entry names at path (or root if path is null).
 */
internal fun listTreeAtPath(repo: Repository, treeId: ObjectId, path: String? = null): List<String> =
    listEntriesAtPath(repo, treeId, path).map { it.name }

/**
 * List entries at path (or root if path is null) as WalkEntry objects.
 */
internal fun listEntriesAtPath(repo: Repository, treeId: ObjectId, path: String? = null): List<WalkEntry> {
    val targetTreeId = if (path == null || isRootPath(path)) {
        treeId
    } else {
        val normalized = normalizePath(path)
        val (objId, mode) = walkTo(repo, treeId, normalized)
        if (mode != FileMode.TREE.bits) throw NotADirectoryError(normalized)
        objId
    }

    val entries = mutableListOf<WalkEntry>()
    val tw = TreeWalk(repo)
    try {
        tw.addTree(targetTreeId)
        tw.isRecursive = false
        while (tw.next()) {
            entries.add(WalkEntry(
                name = tw.nameString,
                oid = tw.getObjectId(0).name,
                mode = tw.getRawMode(0),
            ))
        }
    } finally {
        tw.close()
    }
    return entries
}

/**
 * Walk the tree recursively, returning os.walk-style WalkDirEntry list.
 */
internal fun walkTree(repo: Repository, treeId: ObjectId, prefix: String = ""): List<WalkDirEntry> {
    val result = mutableListOf<WalkDirEntry>()
    walkTreeRecursive(repo, treeId, prefix, result)
    return result
}

private fun walkTreeRecursive(
    repo: Repository,
    treeId: ObjectId,
    prefix: String,
    result: MutableList<WalkDirEntry>,
) {
    val dirs = mutableListOf<String>()
    val files = mutableListOf<WalkEntry>()
    val dirOids = mutableListOf<Pair<String, ObjectId>>()

    val tw = TreeWalk(repo)
    try {
        tw.addTree(treeId)
        tw.isRecursive = false
        while (tw.next()) {
            val name = tw.nameString
            val mode = tw.getRawMode(0)
            val oid = tw.getObjectId(0)
            if (mode == FileMode.TREE.bits) {
                dirs.add(name)
                dirOids.add(Pair(name, oid))
            } else {
                files.add(WalkEntry(name, oid.name, mode))
            }
        }
    } finally {
        tw.close()
    }

    result.add(WalkDirEntry(prefix, dirs, files))

    for ((name, oid) in dirOids) {
        val childPrefix = if (prefix.isEmpty()) name else "$prefix/$name"
        walkTreeRecursive(repo, oid, childPrefix, result)
    }
}

/**
 * Count immediate subdirectory entries in a tree (no recursion).
 */
internal fun countSubdirs(repo: Repository, treeId: ObjectId): Int {
    var count = 0
    val tw = TreeWalk(repo)
    try {
        tw.addTree(treeId)
        tw.isRecursive = false
        while (tw.next()) {
            if (tw.getRawMode(0) == FileMode.TREE.bits) count++
        }
    } finally {
        tw.close()
    }
    return count
}

/**
 * Check if a path exists in the tree.
 */
internal fun existsAtPath(repo: Repository, treeId: ObjectId, path: String): Boolean {
    val normalized = try {
        normalizePath(path)
    } catch (_: IllegalArgumentException) {
        return false
    }
    return entryAtPath(repo, treeId, normalized) != null
}

/**
 * Get the size of a blob object without reading the full content into memory.
 */
internal fun blobSize(repo: Repository, blobId: ObjectId): Long {
    val loader = repo.open(blobId, Constants.OBJ_BLOB)
    return loader.size
}

// ── Tree rebuild (write path) ─────────────────────────────────────────

/**
 * Represents a blob to be written into the tree.
 * @property oid The ObjectId of the blob (already inserted into the repo).
 * @property mode The git filemode for this entry.
 */
internal data class TreeWrite(val oid: ObjectId, val mode: Int)

/**
 * Rebuild a tree with writes and removes applied.
 *
 * Only the ancestor chain from changed leaves to root is rebuilt.
 * Sibling subtrees are shared by hash reference.
 *
 * @param repo The JGit repository.
 * @param baseTreeId OID of the existing tree (or null for empty).
 * @param writes List of (normalized_path, TreeWrite?) — null value means remove.
 * @param inserter ObjectInserter for writing new trees and blobs.
 * @return OID of the new root tree.
 */
internal fun rebuildTree(
    repo: Repository,
    inserter: ObjectInserter,
    baseTreeId: ObjectId?,
    writes: List<Pair<String, TreeWrite?>>,
): ObjectId {
    // Group changes by first path segment
    val subWrites = mutableMapOf<String, MutableList<Pair<String, TreeWrite?>>>()
    val leafWrites = mutableMapOf<String, TreeWrite>()
    val leafRemoves = mutableSetOf<String>()

    for ((path, tw) in writes) {
        val slashIdx = path.indexOf('/')
        if (slashIdx < 0) {
            // Leaf level
            if (tw != null) {
                leafWrites[path] = tw
            } else {
                leafRemoves.add(path)
            }
        } else {
            val dir = path.substring(0, slashIdx)
            val rest = path.substring(slashIdx + 1)
            subWrites.getOrPut(dir) { mutableListOf() }.add(Pair(rest, tw))
        }
    }

    // Load existing entries from base tree
    val entries = sortedMapOf<String, Pair<ObjectId, Int>>()
    val existingSubtrees = mutableMapOf<String, ObjectId>()

    if (baseTreeId != null && !baseTreeId.equals(ObjectId.zeroId())) {
        val tw = TreeWalk(repo)
        try {
            tw.addTree(baseTreeId)
            tw.isRecursive = false
            while (tw.next()) {
                val name = tw.nameString
                val oid = tw.getObjectId(0)
                val mode = tw.getRawMode(0)
                entries[name] = Pair(oid, mode)
                if (mode == FileMode.TREE.bits) {
                    existingSubtrees[name] = oid
                }
            }
        } finally {
            tw.close()
        }
    }

    // Apply leaf writes
    for ((name, tw) in leafWrites) {
        entries[name] = Pair(tw.oid, tw.mode)
    }

    // Apply leaf removes
    for (name in leafRemoves) {
        entries.remove(name)
    }

    // Recurse into subdirectories
    for ((dir, subChanges) in subWrites) {
        val existingOid = existingSubtrees[dir]

        // Handle blob→tree transition: remove non-tree entry
        if (existingOid == null) {
            val existing = entries[dir]
            if (existing != null && existing.second != FileMode.TREE.bits) {
                entries.remove(dir)
            }
        }

        val newSubtreeId = rebuildTree(repo, inserter, existingOid, subChanges)

        // Prune empty directories
        if (isEmptyTree(repo, newSubtreeId)) {
            entries.remove(dir)
        } else {
            entries[dir] = Pair(newSubtreeId, FileMode.TREE.bits)
        }
    }

    // Build and write tree
    val formatter = TreeFormatter()
    for ((name, pair) in entries) {
        val (oid, mode) = pair
        formatter.append(name, FileMode.fromBits(mode), oid)
    }
    return inserter.insert(formatter)
}

/** Check if a tree is empty. */
private fun isEmptyTree(repo: Repository, treeId: ObjectId): Boolean {
    val tw = TreeWalk(repo)
    try {
        tw.addTree(treeId)
        tw.isRecursive = false
        return !tw.next()
    } finally {
        tw.close()
    }
}
