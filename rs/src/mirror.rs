use std::collections::{HashMap, HashSet};
use std::io::Write as IoWrite;
use std::path::Path;
use std::process::{Command, Stdio};

use crate::error::{Error, Result};
use crate::types::{BackupOptions, MirrorDiff, RefChange, RestoreOptions};

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

/// Percent-encode a string for use in URL userinfo.
fn url_encode(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                result.push(b as char);
            }
            _ => {
                result.push_str(&format!("%{:02X}", b));
            }
        }
    }
    result
}

/// Inject credentials into an HTTPS URL if available.
///
/// Tries `git credential fill` first (works with any configured helper:
/// osxkeychain, wincred, libsecret, `gh auth setup-git`, etc.).  Falls
/// back to `gh auth token` for GitHub hosts.  Non-HTTPS URLs and URLs
/// that already contain credentials are returned unchanged.
pub fn resolve_credentials(url: &str) -> String {
    if !url.starts_with("https://") {
        return url.to_string();
    }

    let after_scheme = &url[8..]; // after "https://"
    let path_start = after_scheme.find('/').unwrap_or(after_scheme.len());
    let authority = &after_scheme[..path_start];

    // Already has credentials
    if authority.contains('@') {
        return url.to_string();
    }

    let host = authority; // may include :port
    let hostname = host.split(':').next().unwrap_or(host);
    let path_and_rest = &after_scheme[path_start..];

    // Try git credential fill
    if let Ok(mut child) = Command::new("git")
        .args(["credential", "fill"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        if let Some(ref mut stdin) = child.stdin {
            let _ = write!(stdin, "protocol=https\nhost={}\n\n", hostname);
        }
        // Drop stdin to signal EOF
        child.stdin.take();

        if let Ok(output) = child.wait_with_output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let mut username = None;
                let mut password = None;
                for line in stdout.lines() {
                    if let Some((k, v)) = line.split_once('=') {
                        match k {
                            "username" => username = Some(v.to_string()),
                            "password" => password = Some(v.to_string()),
                            _ => {}
                        }
                    }
                }
                if let (Some(user), Some(pass)) = (username, password) {
                    return format!(
                        "https://{}:{}@{}{}",
                        url_encode(&user),
                        url_encode(&pass),
                        host,
                        path_and_rest
                    );
                }
            }
        }
    }

    // Fallback: gh auth token (GitHub-specific)
    if let Ok(output) = Command::new("gh")
        .args(["auth", "token", "--hostname", hostname])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
    {
        let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if output.status.success() && !token.is_empty() {
            return format!(
                "https://x-access-token:{}@{}{}",
                token, host, path_and_rest
            );
        }
    }

    url.to_string()
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

/// Return true if `url` looks like a local filesystem path (no scheme prefix).
fn is_local_path(url: &str) -> bool {
    !url.starts_with("http://")
        && !url.starts_with("https://")
        && !url.starts_with("git://")
        && !url.starts_with("ssh://")
}

/// Reject scp-style URLs like `user@host:path`.
fn reject_scp_url(url: &str) -> Result<()> {
    if !is_local_path(url) || url.starts_with("file://") {
        return Ok(());
    }

    // user@host:path
    if url.contains('@') {
        let after_at = url.splitn(2, '@').nth(1).unwrap_or("");
        if after_at.contains(':') {
            return Err(Error::invalid_path(format!(
                "scp-style URL not supported: {:?} — use ssh:// format instead",
                url
            )));
        }
    }

    // host:path (no @)
    if let Some(colon_idx) = url.find(':') {
        if colon_idx > 1 {
            let prefix = &url[..colon_idx];
            if !prefix.contains('/') && !prefix.contains('\\') {
                return Err(Error::invalid_path(format!(
                    "scp-style URL not supported: {:?} — use ssh:// format instead",
                    url
                )));
            }
        }
    }

    Ok(())
}

/// Resolve `url` to a local filesystem path (stripping `file://` if present).
fn local_path(url: &str) -> &str {
    url.strip_prefix("file://").unwrap_or(url)
}

/// Auto-create a bare repository at a local path if it doesn't exist.
fn auto_create_bare_repo(url: &str) -> Result<()> {
    if !is_local_path(url) {
        return Ok(());
    }
    let path = Path::new(local_path(url));
    if path.exists() {
        return Ok(());
    }
    std::fs::create_dir_all(path).map_err(|e| Error::io(path, e))?;
    git2::Repository::init_bare(path).map_err(Error::git)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Bundle detection
// ---------------------------------------------------------------------------

/// Return true if `path` has a `.bundle` extension (case-insensitive).
fn is_bundle_path(path: &str) -> bool {
    path.to_lowercase().ends_with(".bundle")
}

// ---------------------------------------------------------------------------
// Ref name resolution
// ---------------------------------------------------------------------------

/// Resolve short ref names to full ref paths.
///
/// Names starting with `refs/` pass through unchanged.  Otherwise tries
/// `refs/heads/`, `refs/tags/`, `refs/notes/` prefixes against the
/// available refs.  If no match, assumes `refs/heads/`.
fn resolve_ref_names(names: &[String], available: &HashMap<String, String>) -> HashSet<String> {
    let available_keys: HashSet<&str> = available.keys().map(|s| s.as_str()).collect();
    let mut result = HashSet::new();
    for name in names {
        if name.starts_with("refs/") {
            result.insert(name.clone());
            continue;
        }
        let mut found = false;
        for prefix in &["refs/heads/", "refs/tags/", "refs/notes/"] {
            let candidate = format!("{}{}", prefix, name);
            if available_keys.contains(candidate.as_str()) {
                result.insert(candidate);
                found = true;
                break;
            }
        }
        if !found {
            result.insert(format!("refs/heads/{}", name));
        }
    }
    result
}

// ---------------------------------------------------------------------------
// Ref enumeration
// ---------------------------------------------------------------------------

/// Get all local refs as `{full_ref_name: 40-char hex SHA}`.
fn get_local_refs(repo_path: &Path) -> Result<HashMap<String, String>> {
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let mut refs = HashMap::new();

    let references = repo.references().map_err(Error::git)?;
    for r in references.flatten() {
        let name = match r.name() {
            Some(n) => n.to_string(),
            None => continue,
        };
        if name == "HEAD" {
            continue;
        }
        if let Some(oid) = r.target().or_else(|| r.resolve().ok().and_then(|r| r.target())) {
            refs.insert(name, oid.to_string());
        }
    }

    Ok(refs)
}

/// Get all remote refs, filtering HEAD and `^{}` markers.
///
/// For local paths, opens the repo directly.  For URLs, uses git2 remote API.
fn get_remote_refs(repo_path: &Path, url: &str) -> Result<HashMap<String, String>> {
    // Local path — open directly
    if is_local_path(url) || url.starts_with("file://") {
        let path = Path::new(local_path(url));
        if !path.exists() {
            return Ok(HashMap::new());
        }
        return get_local_refs(path);
    }

    // Remote URL — use git2 remote API
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let mut remote = match repo.remote_anonymous(url) {
        Ok(r) => r,
        Err(_) => return Ok(HashMap::new()),
    };

    if remote.connect(git2::Direction::Fetch).is_err() {
        return Ok(HashMap::new());
    }

    let mut refs = HashMap::new();
    if let Ok(heads) = remote.list() {
        for head in heads {
            let name = head.name();
            if name == "HEAD" || name.ends_with("^{}") {
                continue;
            }
            refs.insert(name.to_string(), head.oid().to_string());
        }
    }

    let _ = remote.disconnect();
    Ok(refs)
}

// ---------------------------------------------------------------------------
// Diff computation
// ---------------------------------------------------------------------------

fn diff_refs(
    src: &HashMap<String, String>,
    dest: &HashMap<String, String>,
) -> MirrorDiff {
    let mut add = Vec::new();
    let mut update = Vec::new();
    let mut delete = Vec::new();

    for (ref_name, sha) in src {
        match dest.get(ref_name) {
            None => {
                add.push(RefChange {
                    ref_name: ref_name.clone(),
                    old_target: None,
                    new_target: Some(sha.clone()),
                });
            }
            Some(dest_sha) if dest_sha != sha => {
                update.push(RefChange {
                    ref_name: ref_name.clone(),
                    old_target: Some(dest_sha.clone()),
                    new_target: Some(sha.clone()),
                });
            }
            _ => {}
        }
    }

    for (ref_name, sha) in dest {
        if !src.contains_key(ref_name) {
            delete.push(RefChange {
                ref_name: ref_name.clone(),
                old_target: Some(sha.clone()),
                new_target: None,
            });
        }
    }

    MirrorDiff { add, update, delete }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

/// Push all local refs to `url` via native git2 remote API (mirror mode).
///
/// Force-pushes all local refs and deletes any remote-only refs.
fn mirror_push(
    repo_path: &Path,
    url: &str,
    local_refs: &HashMap<String, String>,
    remote_refs: &HashMap<String, String>,
) -> Result<()> {
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let mut remote = repo.remote_anonymous(url).map_err(Error::git)?;

    // Build refspecs: force-push all local refs + delete remote-only refs
    let mut refspecs: Vec<String> = local_refs
        .keys()
        .map(|r| format!("+{}:{}", r, r))
        .collect();
    for name in remote_refs.keys() {
        if !local_refs.contains_key(name) {
            refspecs.push(format!(":{}", name));
        }
    }

    let refspec_strs: Vec<&str> = refspecs.iter().map(|s| s.as_str()).collect();
    remote.push(&refspec_strs, None).map_err(Error::git)?;

    Ok(())
}

/// Push only refs in `ref_filter` to `url` (no deletes).
fn targeted_push(repo_path: &Path, url: &str, ref_filter: &HashSet<String>) -> Result<()> {
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let mut remote = repo.remote_anonymous(url).map_err(Error::git)?;

    let refspecs: Vec<String> = ref_filter.iter().map(|r| format!("+{}:{}", r, r)).collect();
    let refspec_strs: Vec<&str> = refspecs.iter().map(|s| s.as_str()).collect();
    remote.push(&refspec_strs, None).map_err(Error::git)?;

    Ok(())
}

/// Fetch refs from `url` additively (no deletes).
///
/// If `refs` is given, only those refs are fetched via targeted refspecs.
/// Otherwise fetches all refs with `+refs/*:refs/*`.
fn additive_fetch(repo_path: &Path, url: &str, refs: Option<&[String]>) -> Result<()> {
    let remote_refs = get_remote_refs(repo_path, url)?;
    if remote_refs.is_empty() {
        return Ok(());
    }

    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let mut remote = repo.remote_anonymous(url).map_err(Error::git)?;

    if let Some(filter) = refs {
        // Targeted fetch: build refspecs for only the matching refs
        let resolved = resolve_ref_names(filter, &remote_refs);
        let refs_to_fetch: Vec<&String> = remote_refs
            .keys()
            .filter(|k| resolved.contains(k.as_str()))
            .collect();
        if refs_to_fetch.is_empty() {
            return Ok(());
        }

        let refspecs: Vec<String> = refs_to_fetch.iter().map(|r| format!("+{}:{}", r, r)).collect();
        let refspec_strs: Vec<&str> = refspecs.iter().map(|s| s.as_str()).collect();
        remote.fetch(&refspec_strs, None, None).map_err(Error::git)?;
    } else {
        // Fetch all refs
        let refspecs: Vec<String> = remote_refs
            .keys()
            .map(|r| format!("+{}:{}", r, r))
            .collect();
        let refspec_strs: Vec<&str> = refspecs.iter().map(|s| s.as_str()).collect();
        remote.fetch(&refspec_strs, None, None).map_err(Error::git)?;
    }

    // No deletes — that's what makes it additive
    Ok(())
}

// ---------------------------------------------------------------------------
// Bundle helpers
// ---------------------------------------------------------------------------

/// Parse a v2 git bundle header.
///
/// Returns `(refs_map, pack_data_byte_offset)`.
/// Skips prerequisite lines (starting with `-`) and `HEAD`.
fn parse_bundle_header(data: &[u8]) -> Result<(HashMap<String, String>, usize)> {
    let sig = b"# v2 git bundle\n";

    if data.len() < sig.len() || &data[..sig.len()] != sig {
        return Err(Error::git_msg("not a valid v2 git bundle"));
    }

    // Find the blank-line separator (\n\n) that marks end of header
    let header_end = data
        .windows(2)
        .position(|w| w == b"\n\n")
        .ok_or_else(|| Error::git_msg("bundle header: missing blank-line separator"))?;

    // Parse ref lines between signature and separator
    let header_section = &data[sig.len()..header_end];
    let header_str = String::from_utf8_lossy(header_section);

    let mut refs = HashMap::new();
    for line in header_str.lines() {
        if line.is_empty() || line.starts_with('-') {
            continue; // Skip empty and prerequisite lines
        }
        let mut parts = line.splitn(2, ' ');
        let sha = match parts.next() {
            Some(s) if !s.is_empty() => s,
            _ => continue,
        };
        let name = match parts.next() {
            Some(s) => s,
            None => continue,
        };
        if name == "HEAD" || name.ends_with("^{}") {
            continue;
        }
        refs.insert(name.to_string(), sha.to_string());
    }

    // Pack data starts after the second newline of \n\n
    let pack_offset = header_end + 2;
    Ok((refs, pack_offset))
}

/// Create a bundle file from local refs using native git2 PackBuilder.
pub fn bundle_export(repo_path: &Path, path: &str, refs: Option<&[String]>) -> Result<()> {
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    let local_refs = get_local_refs(repo_path)?;

    // Determine which refs to export
    let to_export: HashMap<String, String> = if let Some(filter) = refs {
        let resolved = resolve_ref_names(filter, &local_refs);
        local_refs
            .into_iter()
            .filter(|(k, _)| resolved.contains(k))
            .collect()
    } else {
        local_refs
    };

    if to_export.is_empty() {
        return Err(Error::git_msg("no refs to export"));
    }

    // Build packfile containing all commits and their objects.
    // Use RevWalk + insert_walk to include full ancestry (insert_commit
    // only adds a single commit and its tree, not parent commits).
    let mut pb = repo.packbuilder().map_err(Error::git)?;
    let mut revwalk = repo.revwalk().map_err(Error::git)?;
    for sha in to_export.values() {
        let oid = git2::Oid::from_str(sha).map_err(Error::git)?;
        revwalk.push(oid).map_err(Error::git)?;
    }
    pb.insert_walk(&mut revwalk).map_err(Error::git)?;

    let mut buf = git2::Buf::new();
    pb.write_buf(&mut buf).map_err(Error::git)?;

    // Build v2 bundle header
    let mut header = String::from("# v2 git bundle\n");
    for (name, sha) in &to_export {
        header.push_str(sha);
        header.push(' ');
        header.push_str(name);
        header.push('\n');
    }
    header.push('\n'); // Blank line separator

    // Write header + pack data to file
    let mut file = std::fs::File::create(path)
        .map_err(|e| Error::io(Path::new(path), e))?;
    file.write_all(header.as_bytes())
        .map_err(|e| Error::io(Path::new(path), e))?;
    file.write_all(&buf)
        .map_err(|e| Error::io(Path::new(path), e))?;

    Ok(())
}

/// List refs in a bundle file by parsing the v2 bundle header.
fn bundle_list_heads(path: &str) -> Result<HashMap<String, String>> {
    let data = std::fs::read(path)
        .map_err(|e| Error::io(Path::new(path), e))?;
    let (refs, _) = parse_bundle_header(&data)?;
    Ok(refs)
}

/// Import refs from a bundle file using native git2 Indexer (additive -- no deletes).
pub fn bundle_import(repo_path: &Path, path: &str, refs: Option<&[String]>) -> Result<()> {
    let data = std::fs::read(path)
        .map_err(|e| Error::io(Path::new(path), e))?;
    let (all_refs, pack_offset) = parse_bundle_header(&data)?;

    // Filter which refs to import
    let refs_to_set: HashMap<String, String> = if let Some(filter) = refs {
        let resolved = resolve_ref_names(filter, &all_refs);
        all_refs
            .into_iter()
            .filter(|(k, _)| resolved.contains(k))
            .collect()
    } else {
        all_refs
    };

    if refs_to_set.is_empty() {
        return Ok(());
    }

    // Index the pack data into the repo's object store
    let pack_data = &data[pack_offset..];
    let odb_pack = repo_path.join("objects").join("pack");
    std::fs::create_dir_all(&odb_pack)
        .map_err(|e| Error::io(&odb_pack, e))?;

    let mut indexer = git2::Indexer::new(None, &odb_pack, 0, false)
        .map_err(Error::git)?;
    indexer.write_all(pack_data)
        .map_err(|e| Error::git_msg(format!("indexer write failed: {}", e)))?;
    indexer.commit()
        .map_err(Error::git)?;

    // Create/update refs in the repo
    let repo = git2::Repository::open_bare(repo_path).map_err(Error::git)?;
    for (name, sha) in &refs_to_set {
        let oid = git2::Oid::from_str(sha).map_err(Error::git)?;
        repo.reference(name, oid, true, "bundle import")
            .map_err(Error::git)?;
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Bundle diff helpers
// ---------------------------------------------------------------------------

/// Compute diff for exporting a bundle (all local refs are "add").
fn diff_bundle_export(repo_path: &Path, refs: Option<&[String]>) -> Result<MirrorDiff> {
    let local_refs = get_local_refs(repo_path)?;
    let filtered: HashMap<String, String> = if let Some(filter) = refs {
        let resolved = resolve_ref_names(filter, &local_refs);
        local_refs
            .into_iter()
            .filter(|(k, _)| resolved.contains(k))
            .collect()
    } else {
        local_refs
    };

    let add = filtered
        .into_iter()
        .map(|(ref_name, sha)| RefChange {
            ref_name,
            old_target: None,
            new_target: Some(sha),
        })
        .collect();

    Ok(MirrorDiff {
        add,
        update: vec![],
        delete: vec![],
    })
}

/// Compute diff for importing a bundle (additive -- no deletes).
fn diff_bundle_import(
    repo_path: &Path,
    path: &str,
    refs: Option<&[String]>,
) -> Result<MirrorDiff> {
    let bundle_refs = bundle_list_heads(path)?;
    let filtered: HashMap<String, String> = if let Some(filter) = refs {
        let resolved = resolve_ref_names(filter, &bundle_refs);
        bundle_refs
            .into_iter()
            .filter(|(k, _)| resolved.contains(k))
            .collect()
    } else {
        bundle_refs
    };

    let local_refs = get_local_refs(repo_path)?;
    let mut diff = diff_refs(&filtered, &local_refs);
    diff.delete.clear(); // additive: no deletes
    Ok(diff)
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Push refs to `dest` (or write a bundle file).
///
/// Without `opts.refs` this is a full mirror: remote-only refs are deleted.
/// With `opts.refs` only the specified refs are pushed (no deletes).
///
/// Supports local paths and remote URLs (SSH, HTTPS, git).
/// Auto-creates a bare repository at local destinations.
///
/// # Arguments
/// * `repo_path` - Path to the local bare repository.
/// * `dest` - Destination URL or local path (or bundle file path).
/// * `opts` - [`BackupOptions`] controlling dry-run, refs filter, and format.
pub fn backup(repo_path: &Path, dest: &str, opts: &BackupOptions) -> Result<MirrorDiff> {
    reject_scp_url(dest)?;

    let use_bundle = opts.format.as_deref() == Some("bundle") || is_bundle_path(dest);

    if use_bundle {
        let diff = diff_bundle_export(repo_path, opts.refs.as_deref())?;
        if !opts.dry_run {
            bundle_export(repo_path, dest, opts.refs.as_deref())?;
        }
        return Ok(diff);
    }

    auto_create_bare_repo(dest)?;

    if let Some(ref refs) = opts.refs {
        let local_refs = get_local_refs(repo_path)?;
        let remote_refs = get_remote_refs(repo_path, dest)?;
        let ref_set = resolve_ref_names(refs, &local_refs);

        let mut diff = diff_refs(&local_refs, &remote_refs);
        diff.add.retain(|r| ref_set.contains(&r.ref_name));
        diff.update.retain(|r| ref_set.contains(&r.ref_name));
        diff.delete.clear(); // no deletes when using --ref

        if !opts.dry_run && !diff.in_sync() {
            targeted_push(repo_path, dest, &ref_set)?;
        }
        return Ok(diff);
    }

    let local_refs = get_local_refs(repo_path)?;
    let remote_refs = get_remote_refs(repo_path, dest)?;
    let diff = diff_refs(&local_refs, &remote_refs);

    if !opts.dry_run && !diff.in_sync() {
        mirror_push(repo_path, dest, &local_refs, &remote_refs)?;
    }

    Ok(diff)
}

/// Fetch refs from `src` (or import a bundle file).
///
/// Restore is **additive**: it adds and updates refs but never deletes
/// local-only refs.
///
/// Supports local paths and remote URLs (SSH, HTTPS, git).
///
/// # Arguments
/// * `repo_path` - Path to the local bare repository.
/// * `src` - Source URL or local path (or bundle file path).
/// * `opts` - [`RestoreOptions`] controlling dry-run, refs filter, and format.
pub fn restore(repo_path: &Path, src: &str, opts: &RestoreOptions) -> Result<MirrorDiff> {
    reject_scp_url(src)?;

    let use_bundle = opts.format.as_deref() == Some("bundle") || is_bundle_path(src);

    if use_bundle {
        let diff = diff_bundle_import(repo_path, src, opts.refs.as_deref())?;
        if !opts.dry_run && !diff.in_sync() {
            bundle_import(repo_path, src, opts.refs.as_deref())?;
        }
        return Ok(diff);
    }

    let local_refs = get_local_refs(repo_path)?;
    let remote_refs = get_remote_refs(repo_path, src)?;
    // For restore, remote is source, local is destination
    let mut diff = diff_refs(&remote_refs, &local_refs);

    if let Some(ref refs) = opts.refs {
        let ref_set = resolve_ref_names(refs, &remote_refs);
        diff.add.retain(|r| ref_set.contains(&r.ref_name));
        diff.update.retain(|r| ref_set.contains(&r.ref_name));
    }
    diff.delete.clear(); // additive: never delete

    if !opts.dry_run && !diff.in_sync() {
        additive_fetch(repo_path, src, opts.refs.as_deref())?;
    }

    Ok(diff)
}
