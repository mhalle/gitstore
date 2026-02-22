/// Match a glob pattern against a file name.
///
/// Dotfiles (names starting with `.`) are excluded unless the pattern
/// explicitly starts with `.`.
pub fn glob_match(pattern: &str, name: &str) -> bool {
    // Dotfile guard
    if name.starts_with('.') && !pattern.starts_with('.') {
        return false;
    }

    fnmatch(pattern.as_bytes(), name.as_bytes())
}

/// Simple fnmatch implementation: `*` matches any chars, `?` matches single char.
fn fnmatch(pat: &[u8], name: &[u8]) -> bool {
    let mut pi = 0;
    let mut ni = 0;
    let mut star_pi = usize::MAX;
    let mut star_ni = 0;

    while ni < name.len() {
        if pi < pat.len() && (pat[pi] == b'?' || pat[pi] == name[ni]) {
            pi += 1;
            ni += 1;
        } else if pi < pat.len() && pat[pi] == b'*' {
            star_pi = pi;
            star_ni = ni;
            pi += 1;
        } else if star_pi != usize::MAX {
            pi = star_pi + 1;
            star_ni += 1;
            ni = star_ni;
        } else {
            return false;
        }
    }

    while pi < pat.len() && pat[pi] == b'*' {
        pi += 1;
    }

    pi == pat.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_star() {
        assert!(glob_match("*", "hello"));
        assert!(glob_match("*.txt", "hello.txt"));
        assert!(!glob_match("*.txt", "hello.rs"));
        assert!(glob_match("h*o", "hello"));
    }

    #[test]
    fn test_question() {
        assert!(glob_match("h?llo", "hello"));
        assert!(!glob_match("h?llo", "hllo"));
    }

    #[test]
    fn test_dotfile_guard() {
        assert!(!glob_match("*", ".hidden"));
        assert!(glob_match(".*", ".hidden"));
        assert!(glob_match(".hidden", ".hidden"));
    }

    #[test]
    fn test_exact() {
        assert!(glob_match("hello", "hello"));
        assert!(!glob_match("hello", "world"));
    }
}
