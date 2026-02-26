#include "internal.h"

namespace vost {
namespace glob {

/// Match a single pattern segment against a name.
/// Supports `*` (any sequence, not matching leading `.`),
///          `?` (any single char, not matching leading `.`),
///          `[...]` character classes.
bool fnmatch(const std::string& pattern, const std::string& name) {
    size_t pi = 0, ni = 0;
    size_t plen = pattern.size(), nlen = name.size();

    while (pi < plen && ni < nlen) {
        char pc = pattern[pi];
        if (pc == '*') {
            // Skip consecutive stars
            while (pi < plen && pattern[pi] == '*') ++pi;
            if (pi == plen) return true; // trailing * matches rest
            // Try matching rest of pattern at each position
            for (size_t k = ni; k <= nlen; ++k) {
                std::string rest_name = name.substr(k);
                std::string rest_pat  = pattern.substr(pi);
                if (fnmatch(rest_pat, rest_name)) return true;
            }
            return false;
        } else if (pc == '?') {
            ++pi; ++ni;
        } else if (pc == '[') {
            // Character class
            ++pi;
            bool negate = (pi < plen && pattern[pi] == '!');
            if (negate) ++pi;
            bool matched = false;
            char ch = name[ni];
            while (pi < plen && pattern[pi] != ']') {
                if (pi + 2 < plen && pattern[pi + 1] == '-') {
                    if (ch >= pattern[pi] && ch <= pattern[pi + 2])
                        matched = true;
                    pi += 3;
                } else {
                    if (ch == pattern[pi]) matched = true;
                    ++pi;
                }
            }
            if (pi < plen) ++pi; // skip ']'
            if (matched == negate) return false;
            ++ni;
        } else {
            if (pc != name[ni]) return false;
            ++pi; ++ni;
        }
    }

    // Consume trailing stars
    while (pi < plen && pattern[pi] == '*') ++pi;

    return pi == plen && ni == nlen;
}

/// Match a glob pattern against a string.
/// Leading dot in name requires explicit dot in pattern (unless pattern is `**`).
bool glob_match(const std::string& pattern, const std::string& name) {
    // For * and ? patterns, don't match names starting with '.'
    if (!name.empty() && name[0] == '.' &&
        !pattern.empty() && pattern[0] != '.') {
        // Exception: if pattern is just ** (for recursive glob)
        if (pattern != "**") return false;
    }
    return fnmatch(pattern, name);
}

} // namespace glob
} // namespace vost
