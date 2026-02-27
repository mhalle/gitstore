use crate::error::{Error, Result};

/// Normalize a store path: strip leading/trailing slashes, reject `.`/`..`
/// segments, and collapse repeated slashes.
///
/// An empty input returns an empty string (root).
///
/// # Arguments
/// * `path` - The raw path string to normalize.
///
/// # Errors
/// Returns [`Error::InvalidPath`] if the path contains `.` or `..` segments.
pub fn normalize_path(path: &str) -> Result<String> {
    if path.is_empty() {
        return Ok(String::new());
    }

    let mut segments: Vec<&str> = Vec::new();
    for seg in path.split('/') {
        if seg.is_empty() {
            // skip empty segments (from leading/trailing/double slashes)
            continue;
        }
        if seg == ".." {
            return Err(Error::invalid_path(format!(
                "path segment '{}' is not allowed",
                seg,
            )));
        }
        if seg == "." {
            continue; // collapse current-directory markers
        }
        segments.push(seg);
    }

    if segments.is_empty() {
        // Only-slash paths like "///" mean root (empty string).
        // Paths with actual content that collapsed away (e.g. ".") are errors.
        if path.bytes().all(|b| b == b'/') {
            return Ok(String::new());
        }
        return Err(Error::invalid_path("path must not be empty"));
    }

    Ok(segments.join("/"))
}

/// Validate a git reference name.
///
/// Rejects colons (conflict with vost's `ref:path` syntax), spaces,
/// tabs, control characters, `..`, `@{`, trailing `.`, and `.lock` suffix
/// per git's `check-ref-format` rules.
///
/// # Arguments
/// * `name` - Reference name to validate (without `refs/heads/` prefix).
///
/// # Errors
/// Returns [`Error::InvalidRefName`] if the name violates any rule.
pub fn validate_ref_name(name: &str) -> Result<()> {
    if name.is_empty() {
        return Err(Error::invalid_ref_name("ref name must not be empty"));
    }

    for ch in name.chars() {
        match ch {
            ':' | ' ' | '\t' | '\n' | '\r' | '\\' | '^' | '~' | '?' | '*' | '[' => {
                return Err(Error::invalid_ref_name(format!(
                    "ref name contains invalid character: {:?}",
                    ch,
                )));
            }
            _ => {}
        }
    }

    if name.contains("..") {
        return Err(Error::invalid_ref_name(
            "ref name must not contain '..'",
        ));
    }

    if name.contains("@{") {
        return Err(Error::invalid_ref_name(
            "ref name must not contain '@{'",
        ));
    }

    if name.ends_with('.') {
        return Err(Error::invalid_ref_name(
            "ref name must not end with '.'",
        ));
    }

    if name.ends_with(".lock") {
        return Err(Error::invalid_ref_name(
            "ref name must not end with '.lock'",
        ));
    }

    Ok(())
}

/// Returns `true` when the path refers to the root of the tree
/// (empty string or only slashes).
pub fn is_root_path(path: &str) -> bool {
    path.is_empty() || path.chars().all(|c| c == '/')
}

/// Format a commit message from an operation and optional user message.
///
/// If `message` is `Some`, it is used directly; otherwise `operation` becomes
/// the message.
pub fn format_commit_message(operation: &str, message: Option<&str>) -> String {
    match message {
        Some(msg) => msg.to_string(),
        None => operation.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_empty() {
        assert_eq!(normalize_path("").unwrap(), "");
    }

    #[test]
    fn normalize_strips_slashes() {
        assert_eq!(normalize_path("/a/b/c/").unwrap(), "a/b/c");
    }

    #[test]
    fn normalize_collapses_double_slashes() {
        assert_eq!(normalize_path("a//b///c").unwrap(), "a/b/c");
    }

    #[test]
    fn normalize_collapses_dot() {
        assert_eq!(normalize_path("a/./b").unwrap(), "a/b");
        assert_eq!(normalize_path("./a/b").unwrap(), "a/b");
        assert_eq!(normalize_path("a/b/.").unwrap(), "a/b");
        assert_eq!(normalize_path("./a/./b/.").unwrap(), "a/b");
    }

    #[test]
    fn normalize_only_dots_is_error() {
        assert!(normalize_path(".").is_err());
        assert!(normalize_path("./.").is_err());
    }

    #[test]
    fn normalize_rejects_dotdot() {
        assert!(normalize_path("a/../b").is_err());
    }

    #[test]
    fn validate_ref_ok() {
        assert!(validate_ref_name("refs/heads/main").is_ok());
    }

    #[test]
    fn validate_ref_rejects_space() {
        assert!(validate_ref_name("refs/heads/my branch").is_err());
    }

    #[test]
    fn validate_ref_rejects_colon() {
        assert!(validate_ref_name("refs:heads").is_err());
    }

    #[test]
    fn validate_ref_rejects_dotdot() {
        assert!(validate_ref_name("refs/heads/a..b").is_err());
    }

    #[test]
    fn validate_ref_rejects_at_brace() {
        assert!(validate_ref_name("refs/heads/a@{0}").is_err());
    }

    #[test]
    fn validate_ref_rejects_trailing_dot() {
        assert!(validate_ref_name("refs/heads/a.").is_err());
    }

    #[test]
    fn validate_ref_rejects_dot_lock() {
        assert!(validate_ref_name("refs/heads/a.lock").is_err());
    }

    #[test]
    fn validate_ref_rejects_empty() {
        assert!(validate_ref_name("").is_err());
    }

    #[test]
    fn is_root_empty() {
        assert!(is_root_path(""));
    }

    #[test]
    fn is_root_slashes() {
        assert!(is_root_path("///"));
    }

    #[test]
    fn is_root_non_root() {
        assert!(!is_root_path("a"));
    }
}
