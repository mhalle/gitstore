#pragma once

/// @file mirror.h
/// Mirror (backup/restore) operations for vost.

#include "types.h"

#include <memory>
#include <string>

namespace vost {

struct GitStoreInner;

namespace mirror {

/// Push all local refs to @p dest, creating an exact mirror.
///
/// Supports local paths and remote URLs (SSH, HTTPS, git).
/// Auto-creates a bare repository at local destinations.
///
/// @param inner  Shared inner state of the GitStore.
/// @param dest   Destination URL or local path.
/// @param dry_run If true, compute diff but do not push.
/// @return MirrorDiff describing what changed (or would change).
/// @throws InvalidPathError for scp-style URLs.
/// @throws GitError on transport failures.
MirrorDiff backup(const std::shared_ptr<GitStoreInner>& inner,
                  const std::string& dest, bool dry_run = false);

/// Fetch all refs from @p src, overwriting local state.
///
/// Supports local paths and remote URLs (SSH, HTTPS, git).
///
/// @param inner  Shared inner state of the GitStore.
/// @param src    Source URL or local path.
/// @param dry_run If true, compute diff but do not fetch.
/// @return MirrorDiff describing what changed (or would change).
/// @throws InvalidPathError for scp-style URLs.
/// @throws GitError on transport failures.
MirrorDiff restore(const std::shared_ptr<GitStoreInner>& inner,
                   const std::string& src, bool dry_run = false);

} // namespace mirror

/// Inject credentials into an HTTPS URL if available.
///
/// Tries `git credential fill` first (works with any configured helper:
/// osxkeychain, wincred, libsecret, `gh auth setup-git`, etc.).  Falls
/// back to `gh auth token` for GitHub hosts.  Non-HTTPS URLs and URLs
/// that already contain credentials are returned unchanged.
///
/// @param url  The URL to resolve credentials for.
/// @return The URL with credentials injected, or the original URL.
std::string resolve_credentials(const std::string& url);

} // namespace vost
