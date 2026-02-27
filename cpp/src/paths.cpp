#include "internal.h"
#include "vost/error.h"

#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace vost {
namespace paths {

/// Normalize a store path: strip leading/trailing slashes, reject ./..,
/// collapse repeated slashes.  An empty input returns "" (root).
std::string normalize(const std::string& path) {
    if (path.empty()) return {};

    std::vector<std::string_view> segments;
    std::string_view sv(path);
    size_t start = 0;

    while (start < sv.size()) {
        size_t end = sv.find('/', start);
        if (end == std::string_view::npos) end = sv.size();

        std::string_view seg = sv.substr(start, end - start);
        start = end + 1;

        if (seg.empty()) continue; // skip empty from leading/trailing/double slashes
        if (seg == "..") {
            throw InvalidPathError(std::string("path segment '") +
                                   std::string(seg) + "' is not allowed");
        }
        if (seg == ".") continue; // collapse current-directory markers
        segments.push_back(seg);
    }

    if (segments.empty()) {
        // Only-slash paths like "///" mean root (empty string).
        // Paths with actual content that collapsed away (e.g. ".") are errors.
        bool all_slashes = true;
        for (char c : path) {
            if (c != '/') { all_slashes = false; break; }
        }
        if (all_slashes) return {};
        throw InvalidPathError("path must not be empty");
    }

    std::string out;
    out.reserve(path.size());
    for (size_t i = 0; i < segments.size(); ++i) {
        if (i > 0) out += '/';
        out += std::string(segments[i]);
    }
    return out;
}

/// Validate a git reference name.
/// Rejects colons, spaces, tabs, control chars, .., @{, trailing dot, .lock suffix.
void validate_ref_name(const std::string& name) {
    if (name.empty()) {
        throw InvalidRefNameError("ref name must not be empty");
    }

    for (char ch : name) {
        switch (ch) {
            case ':': case ' ': case '\t': case '\n': case '\r':
            case '\\': case '^': case '~': case '?': case '*': case '[':
                throw InvalidRefNameError(
                    std::string("ref name contains invalid character: '") +
                    ch + "'");
            default: break;
        }
    }

    if (name.find("..") != std::string::npos) {
        throw InvalidRefNameError("ref name must not contain '..'");
    }

    if (name.find("@{") != std::string::npos) {
        throw InvalidRefNameError("ref name must not contain '@{'");
    }

    if (!name.empty() && name.back() == '.') {
        throw InvalidRefNameError("ref name must not end with '.'");
    }

    if (name.size() >= 5 && name.substr(name.size() - 5) == ".lock") {
        throw InvalidRefNameError("ref name must not end with '.lock'");
    }
}

/// Returns true when path is the root (empty or all slashes).
bool is_root(const std::string& path) {
    for (char c : path) {
        if (c != '/') return false;
    }
    return true;
}

/// Format a commit message: use `message` if provided, otherwise `operation`.
std::string format_message(const std::string& operation,
                           const std::optional<std::string>& message) {
    return message ? *message : operation;
}

} // namespace paths
} // namespace vost
