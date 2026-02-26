package vost

import java.io.File
import java.nio.file.FileSystems
import java.nio.file.PathMatcher

/**
 * Dotfile-aware glob matching.
 *
 * '*' and '?' do not match a leading '.' unless the pattern itself
 * starts with '.' (Unix/rsync convention).
 */
internal fun globMatch(pattern: String, name: String): Boolean {
    if (!pattern.startsWith(".") && name.startsWith(".")) return false
    return fnmatch(pattern, name)
}

/**
 * Simple fnmatch-style matching: supports * and ? wildcards.
 */
private fun fnmatch(pattern: String, name: String): Boolean {
    var pi = 0
    var ni = 0
    var starPi = -1
    var starNi = -1

    while (ni < name.length) {
        when {
            pi < pattern.length && (pattern[pi] == '?' || pattern[pi] == name[ni]) -> {
                pi++; ni++
            }
            pi < pattern.length && pattern[pi] == '*' -> {
                starPi = pi; starNi = ni; pi++
            }
            starPi >= 0 -> {
                pi = starPi + 1; starNi++; ni = starNi
            }
            else -> return false
        }
    }
    while (pi < pattern.length && pattern[pi] == '*') pi++
    return pi == pattern.length
}

/**
 * Expand a glob pattern against the local filesystem, respecting dotfile conventions.
 *
 * @param dir Base directory to search in.
 * @param pattern Glob pattern (relative to dir).
 * @return Sorted list of matching relative paths.
 */
fun diskGlob(dir: String, pattern: String): List<String> {
    val baseDir = File(dir)
    if (!baseDir.isDirectory) return emptyList()

    val segments = pattern.split("/")
    val results = mutableListOf<String>()
    diskGlobRecursive(baseDir, segments, 0, "", results)
    return results.sorted()
}

private fun diskGlobRecursive(
    dir: File,
    segments: List<String>,
    segIdx: Int,
    prefix: String,
    results: MutableList<String>,
) {
    if (segIdx >= segments.size) return
    val seg = segments[segIdx]
    val isLast = segIdx == segments.size - 1

    if (seg == "**") {
        // Match zero or more directory levels
        val entries = dir.listFiles() ?: return
        if (segIdx + 1 < segments.size) {
            // Zero dirs: try matching rest here
            diskGlobRecursive(dir, segments, segIdx + 1, prefix, results)
        } else {
            // ** at end: match all non-dot entries
            for (f in entries) {
                if (f.name.startsWith(".")) continue
                val full = if (prefix.isEmpty()) f.name else "$prefix/${f.name}"
                results.add(full)
            }
        }
        // One+ dirs: recurse into non-dot subdirs
        for (f in entries) {
            if (!f.isDirectory || f.name.startsWith(".")) continue
            val full = if (prefix.isEmpty()) f.name else "$prefix/${f.name}"
            diskGlobRecursive(f, segments, segIdx, full, results)
        }
        return
    }

    val hasWild = '*' in seg || '?' in seg
    val entries = dir.listFiles() ?: return

    if (hasWild) {
        for (f in entries) {
            if (!globMatch(seg, f.name)) continue
            val full = if (prefix.isEmpty()) f.name else "$prefix/${f.name}"
            if (isLast) {
                results.add(full)
            } else if (f.isDirectory) {
                diskGlobRecursive(f, segments, segIdx + 1, full, results)
            }
        }
    } else {
        // Literal segment
        val target = File(dir, seg)
        if (!target.exists()) return
        val full = if (prefix.isEmpty()) seg else "$prefix/$seg"
        if (isLast) {
            results.add(full)
        } else if (target.isDirectory) {
            diskGlobRecursive(target, segments, segIdx + 1, full, results)
        }
    }
}
