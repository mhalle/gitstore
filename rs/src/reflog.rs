use std::path::Path;

use crate::error::{Error, Result};
use crate::types::ReflogEntry;

/// The SHA used to represent "no previous commit" in reflogs.
pub const ZERO_SHA: &str = "0000000000000000000000000000000000000000";

/// Read all reflog entries for the given ref.
///
/// Parses `<gitdir>/logs/<refname>` line by line. Returns an empty vec
/// if the reflog file does not exist.
///
/// # Arguments
/// * `gitdir` - Path to the bare repository directory.
/// * `refname` - Full ref name (e.g. `"refs/heads/main"`).
pub fn read_reflog(gitdir: &Path, refname: &str) -> Result<Vec<ReflogEntry>> {
    let log_path = gitdir.join("logs").join(refname);
    if !log_path.exists() {
        return Ok(vec![]);
    }

    let content = std::fs::read_to_string(&log_path).map_err(|e| Error::io(&log_path, e))?;
    let mut entries = Vec::new();

    for line in content.lines() {
        if line.is_empty() {
            continue;
        }
        // Format: <old_sha> <new_sha> <committer> <timestamp> <tz>\t<message>
        let (before_tab, message) = line.split_once('\t').unwrap_or((line, ""));
        let parts: Vec<&str> = before_tab.splitn(5, ' ').collect();
        if parts.len() >= 4 {
            // committer can contain spaces, timestamp and tz are last two tokens
            // Actually format is: old new Name <email> timestamp tz
            // Let's parse more carefully
            let old_sha = parts[0].to_string();
            let new_sha = parts[1].to_string();
            // The rest is "Name <email> timestamp tz"
            let rest = &before_tab[old_sha.len() + 1 + new_sha.len() + 1..];
            // Find timestamp: look for pattern " NNNNNNNNNN +NNNN" at end
            let mut committer = rest.to_string();
            let mut timestamp = 0u64;
            if let Some(last_space) = rest.rfind(' ') {
                // timezone
                if let Some(second_last) = rest[..last_space].rfind(' ') {
                    if let Ok(ts) = rest[second_last + 1..last_space].parse::<u64>() {
                        committer = rest[..second_last].to_string();
                        timestamp = ts;
                    }
                }
            }
            entries.push(ReflogEntry {
                old_sha,
                new_sha,
                committer,
                timestamp,
                message: message.to_string(),
            });
        }
    }

    Ok(entries)
}

/// Append a single reflog entry to `<gitdir>/logs/<refname>`.
///
/// Creates the parent directories if they do not exist. The entry is
/// written in standard git reflog format: `<old> <new> <committer> <ts> +0000\t<msg>`.
///
/// # Arguments
/// * `gitdir` - Path to the bare repository directory.
/// * `refname` - Full ref name (e.g. `"refs/heads/main"`).
/// * `entry` - The [`ReflogEntry`] to append.
pub fn write_reflog_entry(
    gitdir: &Path,
    refname: &str,
    entry: &ReflogEntry,
) -> Result<()> {
    let log_path = gitdir.join("logs").join(refname);
    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| Error::io(parent, e))?;
    }

    use std::io::Write;
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| Error::io(&log_path, e))?;

    writeln!(
        f,
        "{} {} {} {} +0000\t{}",
        entry.old_sha, entry.new_sha, entry.committer, entry.timestamp, entry.message,
    )
    .map_err(|e| Error::io(&log_path, e))?;

    Ok(())
}
