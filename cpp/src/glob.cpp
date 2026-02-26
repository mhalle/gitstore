#include "internal.h"
#include "vost/vost.h"

#include <algorithm>
#include <filesystem>
#include <sstream>

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

// ---------------------------------------------------------------------------
// disk_glob
// ---------------------------------------------------------------------------

namespace {

void disk_glob_recursive(const std::filesystem::path& root,
                          const std::filesystem::path& current,
                          const std::vector<std::string>& segments,
                          size_t seg_idx,
                          std::vector<std::string>& results) {
    namespace fss = std::filesystem;
    if (seg_idx >= segments.size()) return;

    const std::string& seg = segments[seg_idx];
    bool is_last = (seg_idx + 1 == segments.size());

    if (seg == "**") {
        // Match zero directory levels: try remaining segments at this level
        disk_glob_recursive(root, current, segments, seg_idx + 1, results);

        // Match one or more: recurse into non-dotfile subdirectories
        if (fss::exists(current) && fss::is_directory(current)) {
            for (auto& entry : fss::directory_iterator(current)) {
                if (entry.is_directory()) {
                    std::string name = entry.path().filename().string();
                    if (!name.empty() && name[0] == '.') continue;
                    disk_glob_recursive(root, entry.path(), segments, seg_idx, results);
                }
            }
        }
    } else {
        if (!fss::exists(current) || !fss::is_directory(current)) return;

        for (auto& entry : fss::directory_iterator(current)) {
            std::string name = entry.path().filename().string();
            if (!glob::glob_match(seg, name)) continue;

            if (is_last) {
                // Last segment: match files only
                if (!entry.is_directory()) {
                    auto rel = fss::relative(entry.path(), root).string();
                    results.push_back(rel);
                }
            } else if (entry.is_directory()) {
                disk_glob_recursive(root, entry.path(), segments, seg_idx + 1, results);
            }
        }
    }
}

} // anonymous namespace

std::vector<std::string> disk_glob(const std::string& pattern,
                                    const std::string& root) {
    // Split pattern by '/'
    std::vector<std::string> segments;
    {
        std::istringstream iss(pattern);
        std::string seg;
        while (std::getline(iss, seg, '/')) {
            if (!seg.empty()) segments.push_back(seg);
        }
    }
    if (segments.empty()) return {};

    std::filesystem::path root_path(root);
    std::vector<std::string> results;
    disk_glob_recursive(root_path, root_path, segments, 0, results);
    std::sort(results.begin(), results.end());
    return results;
}

} // namespace vost
