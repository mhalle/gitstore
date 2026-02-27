#include "vost/mirror.h"
#include "vost/gitstore.h"
#include "vost/error.h"

#include <git2.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <map>
#include <mutex>
#include <set>
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
// Shell quoting helper
// ---------------------------------------------------------------------------

/// Escape a string for use inside single quotes in a shell command.
/// The strategy: replace each ' with '\'' (end quote, escaped quote, resume).
std::string shell_quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') {
            out += "'\\''";
        } else {
            out += c;
        }
    }
    out += "'";
    return out;
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
// Ref name resolution
// ---------------------------------------------------------------------------

/// Resolve short ref names to full ref paths (e.g. "main" -> "refs/heads/main").
/// Names already starting with "refs/" pass through.  Otherwise tries
/// refs/heads/, refs/tags/, refs/notes/ against available_refs.
/// If no match, defaults to refs/heads/<name>.
std::set<std::string> resolve_ref_names(
    const std::vector<std::string>& names,
    const RefMap& available)
{
    std::set<std::string> result;
    for (const auto& name : names) {
        if (name.compare(0, 5, "refs/") == 0) {
            result.insert(name);
            continue;
        }
        bool found = false;
        for (const char* prefix : {"refs/heads/", "refs/tags/", "refs/notes/"}) {
            auto candidate = std::string(prefix) + name;
            if (available.find(candidate) != available.end()) {
                result.insert(candidate);
                found = true;
                break;
            }
        }
        if (!found) {
            result.insert("refs/heads/" + name);
        }
    }
    return result;
}

// ---------------------------------------------------------------------------
// Bundle detection
// ---------------------------------------------------------------------------

bool is_bundle_path(const std::string& path) {
    if (path.size() < 7) return false;
    auto ext = path.substr(path.size() - 7);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    return ext == ".bundle";
}

// ---------------------------------------------------------------------------
// Shell command helpers (for bundle operations)
// ---------------------------------------------------------------------------

/// Run a shell command and return its stdout, or empty string on failure.
std::string run_cmd_output(const std::string& cmd) {
    FILE* fp = popen(cmd.c_str(), "r");
    if (!fp) return {};
    char buf[4096];
    std::string output;
    while (std::fgets(buf, sizeof(buf), fp)) output += buf;
    int status = pclose(fp);
    if (status != 0) return {};
    return output;
}

/// Trim trailing whitespace/newlines.
std::string rtrim_str(std::string s) {
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' '))
        s.pop_back();
    return s;
}

// ---------------------------------------------------------------------------
// Bundle helpers
// ---------------------------------------------------------------------------

void bundle_export(const std::string& repo_path, const std::string& path,
                   const std::vector<std::string>& refs, const RefMap& local_refs) {
    std::string cmd = "git -C " + shell_quote(repo_path) +
                      " bundle create " + shell_quote(path);
    if (refs.empty()) {
        cmd += " --all";
    } else {
        auto resolved = resolve_ref_names(refs, local_refs);
        for (const auto& r : resolved) {
            cmd += " " + shell_quote(r);
        }
    }
    cmd += " 2>/dev/null";
    int rc = std::system(cmd.c_str());
    if (rc != 0) {
        throw GitError("git bundle create failed");
    }
}

RefMap bundle_list_heads(const std::string& path) {
    std::string cmd = "git bundle list-heads " + shell_quote(path) + " 2>/dev/null";
    auto output = run_cmd_output(cmd);
    if (output.empty()) {
        // Try running again to distinguish empty output from error
        FILE* fp = popen(cmd.c_str(), "r");
        if (!fp) throw GitError("failed to run git bundle list-heads");
        char buf[4096];
        std::string out2;
        while (std::fgets(buf, sizeof(buf), fp)) out2 += buf;
        int status = pclose(fp);
        if (status != 0) throw GitError("git bundle list-heads failed");
        output = out2;
    }

    RefMap refs;
    std::istringstream iss(output);
    std::string line;
    while (std::getline(iss, line)) {
        line = rtrim_str(line);
        auto space = line.find(' ');
        if (space == std::string::npos) continue;
        auto sha = line.substr(0, space);
        auto name = line.substr(space + 1);
        if (name == "HEAD") continue;
        if (name.size() >= 3 && name.compare(name.size() - 3, 3, "^{}") == 0)
            continue;
        refs[name] = sha;
    }
    return refs;
}

void bundle_import(const std::string& repo_path, const std::string& path,
                   const std::vector<std::string>& refs) {
    auto bundle_refs = bundle_list_heads(path);

    RefMap refs_to_import;
    if (refs.empty()) {
        refs_to_import = bundle_refs;
    } else {
        auto resolved = resolve_ref_names(refs, bundle_refs);
        for (const auto& [k, v] : bundle_refs) {
            if (resolved.count(k)) refs_to_import[k] = v;
        }
    }

    if (refs_to_import.empty()) return;

    // Build fetch command with specific refspecs
    std::string cmd = "git -C " + shell_quote(repo_path) +
                      " fetch " + shell_quote(path);
    for (const auto& [name, sha] : refs_to_import) {
        cmd += " " + shell_quote("+" + name + ":" + name);
    }
    cmd += " 2>/dev/null";

    int rc = std::system(cmd.c_str());
    if (rc != 0) {
        throw GitError("git fetch from bundle failed");
    }
}

// ---------------------------------------------------------------------------
// Bundle diff helpers
// ---------------------------------------------------------------------------

MirrorDiff diff_bundle_export(git_repository* repo,
                               const std::vector<std::string>& refs) {
    auto local_refs = get_local_refs(repo);
    RefMap filtered;
    if (refs.empty()) {
        filtered = local_refs;
    } else {
        auto resolved = resolve_ref_names(refs, local_refs);
        for (const auto& [k, v] : local_refs) {
            if (resolved.count(k)) filtered[k] = v;
        }
    }

    MirrorDiff diff;
    for (const auto& [name, sha] : filtered) {
        diff.add.push_back({name, std::nullopt, sha});
    }
    return diff;
}

MirrorDiff diff_bundle_import(git_repository* repo, const std::string& path,
                               const std::vector<std::string>& refs) {
    auto bundle_refs = bundle_list_heads(path);
    RefMap filtered;
    if (refs.empty()) {
        filtered = bundle_refs;
    } else {
        auto resolved = resolve_ref_names(refs, bundle_refs);
        for (const auto& [k, v] : bundle_refs) {
            if (resolved.count(k)) filtered[k] = v;
        }
    }

    auto local_refs = get_local_refs(repo);
    auto diff = diff_refs(filtered, local_refs);
    diff.del.clear(); // additive: no deletes
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

/// Push only refs in ref_filter (no deletes on remote).
void targeted_push(git_repository* repo, const std::string& url,
                   const RefMap& local_refs, const std::set<std::string>& ref_filter) {
    git_remote* remote = nullptr;
    if (git_remote_create_anonymous(&remote, repo, url.c_str()) != 0) {
        throw_git("git_remote_create_anonymous");
    }

    std::vector<std::string> refspec_strs;
    for (const auto& name : ref_filter) {
        if (local_refs.find(name) != local_refs.end()) {
            refspec_strs.push_back("+" + name + ":" + name);
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

/// Fetch refs additively (no deletes).  If refs_filter is non-empty,
/// only fetches refs that match the filter.
void additive_fetch(git_repository* repo, const std::string& url,
                    const RefMap& remote_refs, const std::vector<std::string>& refs) {
    RefMap to_fetch;
    if (refs.empty()) {
        to_fetch = remote_refs;
    } else {
        auto resolved = resolve_ref_names(refs, remote_refs);
        for (const auto& [k, v] : remote_refs) {
            if (resolved.count(k)) to_fetch[k] = v;
        }
    }

    if (to_fetch.empty()) return;

    git_remote* remote = nullptr;
    if (git_remote_create_anonymous(&remote, repo, url.c_str()) != 0) {
        throw_git("git_remote_create_anonymous");
    }

    std::vector<std::string> refspec_strs;
    for (auto& [name, sha] : to_fetch) {
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

    // No deletes — that's what makes it additive
}

} // anonymous namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

MirrorDiff backup(const std::shared_ptr<GitStoreInner>& inner,
                  const std::string& dest, const BackupOptions& opts) {
    reject_scp_url(dest);

    bool use_bundle = opts.format == "bundle" || is_bundle_path(dest);

    std::lock_guard<std::mutex> lk(inner->mutex);

    if (use_bundle) {
        auto diff = diff_bundle_export(inner->repo, opts.refs);
        if (!opts.dry_run) {
            auto local_refs = get_local_refs(inner->repo);
            bundle_export(inner->path.string(), dest, opts.refs, local_refs);
        }
        return diff;
    }

    auto_create_bare_repo(dest);

    if (!opts.refs.empty()) {
        auto local_refs = get_local_refs(inner->repo);
        auto remote_refs = get_remote_refs(inner->repo, dest);
        auto ref_filter = resolve_ref_names(opts.refs, local_refs);
        auto diff = diff_refs(local_refs, remote_refs);

        // Filter to only targeted refs, no deletes
        std::vector<RefChange> filtered_add, filtered_update;
        for (auto& r : diff.add) {
            if (ref_filter.count(r.ref_name)) filtered_add.push_back(std::move(r));
        }
        for (auto& r : diff.update) {
            if (ref_filter.count(r.ref_name)) filtered_update.push_back(std::move(r));
        }
        diff.add = std::move(filtered_add);
        diff.update = std::move(filtered_update);
        diff.del.clear();

        if (!opts.dry_run && !diff.in_sync()) {
            targeted_push(inner->repo, dest, local_refs, ref_filter);
        }
        return diff;
    }

    auto local_refs = get_local_refs(inner->repo);
    auto remote_refs = get_remote_refs(inner->repo, dest);
    auto diff = diff_refs(local_refs, remote_refs);

    if (!opts.dry_run && !diff.in_sync()) {
        mirror_push(inner->repo, dest, local_refs, remote_refs);
    }

    return diff;
}

MirrorDiff restore(const std::shared_ptr<GitStoreInner>& inner,
                   const std::string& src, const RestoreOptions& opts) {
    reject_scp_url(src);

    bool use_bundle = opts.format == "bundle" || is_bundle_path(src);

    std::lock_guard<std::mutex> lk(inner->mutex);

    if (use_bundle) {
        auto diff = diff_bundle_import(inner->repo, src, opts.refs);
        if (!opts.dry_run) {
            bundle_import(inner->path.string(), src, opts.refs);
        }
        return diff;
    }

    auto local_refs = get_local_refs(inner->repo);
    auto remote_refs = get_remote_refs(inner->repo, src);
    auto diff = diff_refs(remote_refs, local_refs);

    if (!opts.refs.empty()) {
        auto ref_filter = resolve_ref_names(opts.refs, remote_refs);
        std::vector<RefChange> filtered_add, filtered_update;
        for (auto& r : diff.add) {
            if (ref_filter.count(r.ref_name)) filtered_add.push_back(std::move(r));
        }
        for (auto& r : diff.update) {
            if (ref_filter.count(r.ref_name)) filtered_update.push_back(std::move(r));
        }
        diff.add = std::move(filtered_add);
        diff.update = std::move(filtered_update);
    }
    diff.del.clear(); // additive: never delete

    if (!opts.dry_run && !diff.in_sync()) {
        additive_fetch(inner->repo, src, remote_refs, opts.refs);
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
