#include "vost/mirror.h"
#include "vost/gitstore.h"
#include "vost/error.h"

#include <git2.h>

#include <algorithm>
#include <filesystem>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

namespace vost {
namespace mirror {

namespace {

// ---------------------------------------------------------------------------
// libgit2 helpers (local to this TU, same pattern as gitstore.cpp)
// ---------------------------------------------------------------------------

[[noreturn]] void throw_git(const std::string& ctx) {
    const git_error* e = git_error_last();
    std::string msg = ctx;
    if (e && e->message) { msg += ": "; msg += e->message; }
    throw GitError(msg);
}

std::string oid_hex(const git_oid* o) {
    char buf[41];
    git_oid_tostr(buf, sizeof(buf), o);
    return std::string(buf);
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

bool is_local_path(const std::string& url) {
    return url.compare(0, 7, "http://") != 0 &&
           url.compare(0, 8, "https://") != 0 &&
           url.compare(0, 6, "git://") != 0 &&
           url.compare(0, 6, "ssh://") != 0;
}

void reject_scp_url(const std::string& url) {
    if (!is_local_path(url) || url.compare(0, 7, "file://") == 0) return;

    // user@host:path
    auto at_pos = url.find('@');
    if (at_pos != std::string::npos) {
        auto after_at = url.substr(at_pos + 1);
        if (after_at.find(':') != std::string::npos) {
            throw InvalidPathError("scp-style URL not supported: \"" + url +
                                   "\" \xe2\x80\x94 use ssh:// format instead");
        }
    }

    // host:path (no @)
    auto colon_pos = url.find(':');
    if (colon_pos != std::string::npos && colon_pos > 1) {
        auto prefix = url.substr(0, colon_pos);
        if (prefix.find('/') == std::string::npos &&
            prefix.find('\\') == std::string::npos) {
            throw InvalidPathError("scp-style URL not supported: \"" + url +
                                   "\" \xe2\x80\x94 use ssh:// format instead");
        }
    }
}

std::string local_path_from_url(const std::string& url) {
    if (url.compare(0, 7, "file://") == 0) return url.substr(7);
    return url;
}

void auto_create_bare_repo(const std::string& url) {
    if (!is_local_path(url)) return;
    auto path = local_path_from_url(url);
    if (std::filesystem::exists(path)) return;

    std::filesystem::create_directories(path);
    git_repository* repo = nullptr;
    if (git_repository_init(&repo, path.c_str(), 1 /*bare*/) != 0) {
        throw_git("git_repository_init (auto-create)");
    }
    git_repository_free(repo);
}

// ---------------------------------------------------------------------------
// Ref enumeration
// ---------------------------------------------------------------------------

using RefMap = std::map<std::string, std::string>;

/// Get all refs from a git_repository, excluding HEAD.
RefMap get_refs_from_repo(git_repository* repo) {
    RefMap refs;
    git_reference_iterator* iter = nullptr;
    if (git_reference_iterator_new(&iter, repo) != 0) return refs;

    git_reference* ref = nullptr;
    while (git_reference_next(&ref, iter) == 0) {
        const char* name = git_reference_name(ref);
        if (!name || std::string(name) == "HEAD") {
            git_reference_free(ref);
            continue;
        }

        // Resolve symbolic refs to get the direct OID
        git_reference* resolved = nullptr;
        if (git_reference_resolve(&resolved, ref) == 0) {
            const git_oid* oid = git_reference_target(resolved);
            if (oid) {
                refs[name] = oid_hex(oid);
            }
            git_reference_free(resolved);
        }
        git_reference_free(ref);
    }
    git_reference_iterator_free(iter);
    return refs;
}

/// Get all local refs from the inner repo.
RefMap get_local_refs(git_repository* repo) {
    return get_refs_from_repo(repo);
}

/// Get remote refs. For local paths, opens repo directly. For URLs, uses
/// git_remote_ls.
RefMap get_remote_refs(git_repository* repo, const std::string& url) {
    // Local path — open directly
    if (is_local_path(url) || url.compare(0, 7, "file://") == 0) {
        auto path = local_path_from_url(url);
        if (!std::filesystem::exists(path)) return {};

        git_repository* remote_repo = nullptr;
        if (git_repository_open_bare(&remote_repo, path.c_str()) != 0) {
            return {};
        }
        auto refs = get_refs_from_repo(remote_repo);
        git_repository_free(remote_repo);
        return refs;
    }

    // Remote URL: use git_remote_ls
    RefMap refs;
    git_remote* remote = nullptr;
    if (git_remote_create_anonymous(&remote, repo, url.c_str()) != 0) return refs;

    git_remote_callbacks cbs = GIT_REMOTE_CALLBACKS_INIT;
    if (git_remote_connect(remote, GIT_DIRECTION_FETCH, &cbs, nullptr, nullptr) != 0) {
        git_remote_free(remote);
        return refs;
    }

    const git_remote_head** heads = nullptr;
    size_t count = 0;
    if (git_remote_ls(&heads, &count, remote) == 0) {
        for (size_t i = 0; i < count; ++i) {
            std::string name = heads[i]->name;
            if (name == "HEAD") continue;
            if (name.size() >= 3 &&
                name.compare(name.size() - 3, 3, "^{}") == 0) continue;
            refs[name] = oid_hex(&heads[i]->oid);
        }
    }

    git_remote_disconnect(remote);
    git_remote_free(remote);
    return refs;
}

// ---------------------------------------------------------------------------
// Diff computation
// ---------------------------------------------------------------------------

MirrorDiff diff_refs(const RefMap& src, const RefMap& dest) {
    MirrorDiff diff;

    for (auto& [ref_name, sha] : src) {
        auto it = dest.find(ref_name);
        if (it == dest.end()) {
            diff.add.push_back({ref_name, std::nullopt, sha});
        } else if (it->second != sha) {
            diff.update.push_back({ref_name, it->second, sha});
        }
    }

    for (auto& [ref_name, sha] : dest) {
        if (src.find(ref_name) == src.end()) {
            diff.del.push_back({ref_name, sha, std::nullopt});
        }
    }

    return diff;
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

void mirror_push(git_repository* repo, const std::string& url,
                 const RefMap& local_refs, const RefMap& remote_refs) {
    git_remote* remote = nullptr;
    if (git_remote_create_anonymous(&remote, repo, url.c_str()) != 0) {
        throw_git("git_remote_create_anonymous");
    }

    // Build refspecs: force-push all local, delete stale remote
    std::vector<std::string> refspec_strs;
    for (auto& [name, sha] : local_refs) {
        refspec_strs.push_back("+" + name + ":" + name);
    }
    for (auto& [name, sha] : remote_refs) {
        if (local_refs.find(name) == local_refs.end()) {
            refspec_strs.push_back(":" + name);  // delete
        }
    }

    std::vector<char*> refspec_ptrs;
    refspec_ptrs.reserve(refspec_strs.size());
    for (auto& s : refspec_strs) {
        refspec_ptrs.push_back(const_cast<char*>(s.c_str()));
    }

    git_strarray arr;
    arr.strings = refspec_ptrs.data();
    arr.count = refspec_ptrs.size();

    git_push_options push_opts;
    git_push_options_init(&push_opts, GIT_PUSH_OPTIONS_VERSION);

    int rc = git_remote_push(remote, &arr, &push_opts);
    git_remote_free(remote);
    if (rc != 0) throw_git("git_remote_push");
}

void mirror_fetch(git_repository* repo, const std::string& url,
                  const RefMap& remote_refs, const RefMap& local_refs) {
    // Step 1: Fetch objects for all remote refs
    if (!remote_refs.empty()) {
        git_remote* remote = nullptr;
        if (git_remote_create_anonymous(&remote, repo, url.c_str()) != 0) {
            throw_git("git_remote_create_anonymous");
        }

        std::vector<std::string> refspec_strs;
        for (auto& [name, sha] : remote_refs) {
            refspec_strs.push_back("+" + name + ":" + name);
        }

        std::vector<char*> refspec_ptrs;
        refspec_ptrs.reserve(refspec_strs.size());
        for (auto& s : refspec_strs) {
            refspec_ptrs.push_back(const_cast<char*>(s.c_str()));
        }

        git_strarray arr;
        arr.strings = refspec_ptrs.data();
        arr.count = refspec_ptrs.size();

        git_fetch_options fetch_opts;
        git_fetch_options_init(&fetch_opts, GIT_FETCH_OPTIONS_VERSION);

        int rc = git_remote_fetch(remote, &arr, &fetch_opts, nullptr);
        git_remote_free(remote);
        if (rc != 0) throw_git("git_remote_fetch");
    }

    // Step 2: Delete local refs not in remote
    for (auto& [name, sha] : local_refs) {
        if (remote_refs.find(name) == remote_refs.end()) {
            git_reference* ref = nullptr;
            if (git_reference_lookup(&ref, repo, name.c_str()) == 0) {
                git_reference_delete(ref);
                git_reference_free(ref);
            }
        }
    }
}

} // anonymous namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

MirrorDiff backup(const std::shared_ptr<GitStoreInner>& inner,
                  const std::string& dest, bool dry_run) {
    reject_scp_url(dest);
    auto_create_bare_repo(dest);

    std::lock_guard<std::mutex> lk(inner->mutex);
    auto local_refs = get_local_refs(inner->repo);
    auto remote_refs = get_remote_refs(inner->repo, dest);
    auto diff = diff_refs(local_refs, remote_refs);

    if (!dry_run && !diff.in_sync()) {
        mirror_push(inner->repo, dest, local_refs, remote_refs);
    }

    return diff;
}

MirrorDiff restore(const std::shared_ptr<GitStoreInner>& inner,
                   const std::string& src, bool dry_run) {
    reject_scp_url(src);

    std::lock_guard<std::mutex> lk(inner->mutex);
    auto local_refs = get_local_refs(inner->repo);
    auto remote_refs = get_remote_refs(inner->repo, src);
    // For restore, remote is source, local is destination
    auto diff = diff_refs(remote_refs, local_refs);

    if (!dry_run && !diff.in_sync()) {
        mirror_fetch(inner->repo, src, remote_refs, local_refs);
    }

    return diff;
}

} // namespace mirror

// ---------------------------------------------------------------------------
// resolve_credentials — in vost namespace
// ---------------------------------------------------------------------------

namespace {

std::string percent_encode(const std::string& s) {
    static const char* hex = "0123456789ABCDEF";
    std::string result;
    result.reserve(s.size());
    for (unsigned char c : s) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
            result += static_cast<char>(c);
        } else {
            result += '%';
            result += hex[c >> 4];
            result += hex[c & 0x0F];
        }
    }
    return result;
}

/// Run a shell command and return its stdout, or empty string on failure.
std::string run_cmd(const std::string& cmd) {
    FILE* fp = popen(cmd.c_str(), "r");
    if (!fp) return {};
    char buf[4096];
    std::string output;
    while (std::fgets(buf, sizeof(buf), fp)) output += buf;
    int status = pclose(fp);
    if (status != 0) return {};
    return output;
}

/// Trim trailing whitespace.
std::string rtrim(std::string s) {
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' '))
        s.pop_back();
    return s;
}

/// Return true if hostname contains only safe characters.
bool hostname_safe(const std::string& h) {
    for (char c : h) {
        if (!std::isalnum(static_cast<unsigned char>(c)) && c != '.' && c != '-')
            return false;
    }
    return !h.empty();
}

} // anonymous namespace

std::string resolve_credentials(const std::string& url) {
    if (url.compare(0, 8, "https://") != 0) return url;

    auto after_scheme = url.substr(8);
    auto path_start = after_scheme.find('/');
    if (path_start == std::string::npos) path_start = after_scheme.size();
    auto authority = after_scheme.substr(0, path_start);

    // Already has credentials
    if (authority.find('@') != std::string::npos) return url;

    auto host = authority; // may include :port
    auto colon_pos = host.find(':');
    auto hostname = (colon_pos != std::string::npos) ? host.substr(0, colon_pos) : host;
    auto path_and_rest = after_scheme.substr(path_start);

    // Validate hostname to prevent shell injection
    if (!hostname_safe(hostname)) return url;

    // Try git credential fill
    {
        std::string cmd = "printf 'protocol=https\\nhost=" + hostname +
                          "\\n\\n' | git credential fill 2>/dev/null";
        auto output = run_cmd(cmd);
        if (!output.empty()) {
            std::string username, password;
            std::istringstream iss(output);
            std::string line;
            while (std::getline(iss, line)) {
                auto eq = line.find('=');
                if (eq != std::string::npos) {
                    auto key = line.substr(0, eq);
                    auto val = rtrim(line.substr(eq + 1));
                    if (key == "username") username = val;
                    if (key == "password") password = val;
                }
            }
            if (!username.empty() && !password.empty()) {
                return "https://" + percent_encode(username) + ":" +
                       percent_encode(password) + "@" + host + path_and_rest;
            }
        }
    }

    // Fallback: gh auth token (GitHub-specific)
    {
        std::string cmd = "gh auth token --hostname " + hostname + " 2>/dev/null";
        auto token = rtrim(run_cmd(cmd));
        if (!token.empty()) {
            return "https://x-access-token:" + token + "@" + host + path_and_rest;
        }
    }

    return url;
}

} // namespace vost
