package vost

import java.io.File

/**
 * Gitignore-style exclude filter for disk-to-repo copy/sync operations.
 *
 * Supports `!` negation, `/` suffix for directory-only patterns,
 * and anchored patterns (containing `/`). Last matching rule wins.
 *
 * @param patterns Initial patterns to add.
 * @param excludeFrom Path to a file containing patterns (one per line).
 */
class ExcludeFilter(
    patterns: List<String>? = null,
    excludeFrom: String? = null,
) {
    private data class Pattern(
        val raw: String,
        val negated: Boolean,
        val dirOnly: Boolean,
    )

    private val patterns_ = mutableListOf<Pattern>()

    init {
        if (patterns != null) addPatterns(patterns)
        if (excludeFrom != null) loadFromFile(excludeFrom)
    }

    /** Whether any patterns have been loaded. */
    val active: Boolean get() = patterns_.isNotEmpty()

    /** Add gitignore-style patterns. */
    fun addPatterns(patterns: List<String>) {
        for (raw in patterns) {
            if (raw.isBlank() || raw.startsWith("#")) continue

            var s = raw
            var negated = false
            var dirOnly = false

            if (s.startsWith("!")) {
                negated = true
                s = s.substring(1)
            }

            if (s.endsWith("/")) {
                dirOnly = true
                s = s.dropLast(1)
            }

            if (s.isNotEmpty()) {
                patterns_.add(Pattern(raw = s, negated = negated, dirOnly = dirOnly))
            }
        }
    }

    /** Load patterns from a file (one per line, ignoring blank/comment lines). */
    fun loadFromFile(path: String) {
        val file = File(path)
        if (!file.exists()) return
        val lines = file.readLines().map { line ->
            // Trim trailing whitespace (but not leading, to preserve negation)
            line.trimEnd()
        }.filter { it.isNotEmpty() }
        addPatterns(lines)
    }

    /**
     * Check if a relative path is excluded.
     *
     * @param relPath Relative path using forward slashes.
     * @param isDir Whether the path is a directory.
     * @return True if the path should be excluded.
     */
    fun isExcluded(relPath: String, isDir: Boolean = false): Boolean {
        var excluded = false
        for (p in patterns_) {
            if (p.dirOnly && !isDir) continue
            if (matchPattern(p.raw, relPath)) {
                excluded = !p.negated
            }
        }
        return excluded
    }

    private fun matchPattern(pattern: String, path: String): Boolean {
        // If pattern contains /, match against full relative path
        if ('/' in pattern) {
            return fnmatchSimple(pattern, path)
        }
        // Otherwise match against basename only
        val basename = path.substringAfterLast('/')
        return fnmatchSimple(pattern, basename)
    }

    /**
     * Simple fnmatch: supports * and ? wildcards.
     * Unlike globMatch, does NOT apply dotfile protection — gitignore
     * patterns like *.pyc should match .hidden.pyc.
     */
    private fun fnmatchSimple(pattern: String, name: String): Boolean {
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
}
