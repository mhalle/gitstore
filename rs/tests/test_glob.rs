mod common;

use vost::*;

fn store_with_glob_files(dir: &std::path::Path) -> (GitStore, Fs) {
    let store = common::create_store(dir, "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("readme.txt", b"readme").unwrap();
    batch.write("notes.txt", b"notes").unwrap();
    batch.write("data.csv", b"data").unwrap();
    batch.write(".hidden", b"hidden").unwrap();
    batch.write("src/main.py", b"main").unwrap();
    batch.write("src/lib.py", b"lib").unwrap();
    batch.write("src/util.rs", b"util").unwrap();
    batch.write("src/deep/mod.py", b"mod").unwrap();
    batch.write("src/deep/nested/core.py", b"core").unwrap();
    batch.write("docs/guide.md", b"guide").unwrap();
    batch.write("docs/api.md", b"api").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    (store, fs)
}

// ---------------------------------------------------------------------------
// Star (*)
// ---------------------------------------------------------------------------

#[test]
fn glob_star_txt() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("*.txt").unwrap();
    assert_eq!(matches, vec!["notes.txt", "readme.txt"]);
}

#[test]
fn glob_star_excludes_dotfiles() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("*").unwrap();
    // Should not include .hidden
    assert!(!matches.contains(&".hidden".to_string()));
    // But should include regular files
    assert!(matches.contains(&"data.csv".to_string()));
}

#[test]
fn glob_dotstar_matches_dotfiles() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob(".*").unwrap();
    assert_eq!(matches, vec![".hidden"]);
}

#[test]
fn glob_star_in_subdir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/*.py").unwrap();
    assert_eq!(matches, vec!["src/lib.py", "src/main.py"]);
}

#[test]
fn glob_extension_filter() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("*.csv").unwrap();
    assert_eq!(matches, vec!["data.csv"]);
}

// ---------------------------------------------------------------------------
// Question mark (?)
// ---------------------------------------------------------------------------

#[test]
fn glob_question_mark() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("abc.md", b"a").unwrap();
    batch.write("xyz.md", b"b").unwrap();
    batch.write("ab.md", b"c").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    let matches = fs.glob("???.md").unwrap();
    assert_eq!(matches, vec!["abc.md", "xyz.md"]);
}

// ---------------------------------------------------------------------------
// Mixed patterns
// ---------------------------------------------------------------------------

#[test]
fn glob_literal_then_glob() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("docs/*.md").unwrap();
    assert_eq!(matches, vec!["docs/api.md", "docs/guide.md"]);
}

#[test]
fn glob_glob_then_literal() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/util.rs").unwrap();
    assert_eq!(matches, vec!["src/util.rs"]);
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

#[test]
fn glob_no_matches() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("*.xyz").unwrap();
    assert!(matches.is_empty());
}

#[test]
fn glob_literal_path() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("readme.txt").unwrap();
    assert_eq!(matches, vec!["readme.txt"]);
}

#[test]
fn glob_literal_missing() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("nonexistent.txt").unwrap();
    assert!(matches.is_empty());
}

#[test]
fn glob_results_sorted() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("*.txt").unwrap();
    let mut sorted = matches.clone();
    sorted.sort();
    assert_eq!(matches, sorted);
}

// ---------------------------------------------------------------------------
// Double star (**)
// ---------------------------------------------------------------------------

#[test]
fn glob_doublestar_recursive() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("**/*.py").unwrap();
    assert!(matches.contains(&"src/main.py".to_string()));
    assert!(matches.contains(&"src/lib.py".to_string()));
    assert!(matches.contains(&"src/deep/mod.py".to_string()));
    assert!(matches.contains(&"src/deep/nested/core.py".to_string()));
}

#[test]
fn glob_doublestar_prefix() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/**/*.py").unwrap();
    assert!(matches.contains(&"src/main.py".to_string()));
    assert!(matches.contains(&"src/lib.py".to_string()));
    assert!(matches.contains(&"src/deep/mod.py".to_string()));
    assert!(matches.contains(&"src/deep/nested/core.py".to_string()));
    // Should not include non-src files
    assert!(!matches.iter().any(|m| m.starts_with("docs/")));
}

#[test]
fn glob_doublestar_deep() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/**/core.py").unwrap();
    assert_eq!(matches, vec!["src/deep/nested/core.py"]);
}

#[test]
fn glob_doublestar_no_dotfiles() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write(".dotdir/file.txt", b"a").unwrap();
    batch.write("normal/file.txt", b"b").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    let matches = fs.glob("**/*.txt").unwrap();
    // .dotdir should be skipped
    assert!(!matches.iter().any(|m| m.contains(".dotdir")));
    assert!(matches.contains(&"normal/file.txt".to_string()));
}

#[test]
fn glob_doublestar_no_duplicates() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("**/*.py").unwrap();
    let mut unique = matches.clone();
    unique.sort();
    unique.dedup();
    assert_eq!(matches.len(), unique.len());
}

#[test]
fn glob_doublestar_empty_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let matches = fs.glob("**/*.txt").unwrap();
    assert!(matches.is_empty());
}

#[test]
fn glob_doublestar_sorted() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("**/*.py").unwrap();
    let mut sorted = matches.clone();
    sorted.sort();
    assert_eq!(matches, sorted);
}

// ---------------------------------------------------------------------------
// iglob (if available — same as glob, just iterator)
// ---------------------------------------------------------------------------

#[test]
fn glob_star_rs_extension() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/*.rs").unwrap();
    assert_eq!(matches, vec!["src/util.rs"]);
}

#[test]
fn glob_doublestar_all_md() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("**/*.md").unwrap();
    assert!(matches.contains(&"docs/api.md".to_string()));
    assert!(matches.contains(&"docs/guide.md".to_string()));
    assert_eq!(matches.len(), 2);
}

#[test]
fn glob_doublestar_mixed_extensions() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let py_matches = fs.glob("**/*.py").unwrap();
    let rs_matches = fs.glob("**/*.rs").unwrap();
    assert_eq!(py_matches.len(), 4); // main.py, lib.py, mod.py, core.py
    assert_eq!(rs_matches.len(), 1); // util.rs
}

#[test]
fn glob_star_empty_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let matches = fs.glob("*.txt").unwrap();
    assert!(matches.is_empty());
}

#[test]
fn glob_doublestar_all_files() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("**/*").unwrap();
    // Should get all non-dotfiles
    assert!(matches.contains(&"readme.txt".to_string()));
    assert!(matches.contains(&"src/main.py".to_string()));
    assert!(matches.contains(&"src/deep/nested/core.py".to_string()));
    assert!(!matches.contains(&".hidden".to_string()));
}

#[test]
fn glob_question_mark_in_subdir() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("dir/ab.txt", b"a").unwrap();
    batch.write("dir/cd.txt", b"b").unwrap();
    batch.write("dir/abc.txt", b"c").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    let matches = fs.glob("dir/??.txt").unwrap();
    assert_eq!(matches, vec!["dir/ab.txt", "dir/cd.txt"]);
}

#[test]
fn glob_doublestar_star_at_end() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_glob_files(dir.path());
    let matches = fs.glob("src/**/*").unwrap();
    // Should include all files under src/
    assert!(matches.contains(&"src/main.py".to_string()));
    assert!(matches.contains(&"src/lib.py".to_string()));
    assert!(matches.contains(&"src/util.rs".to_string()));
    assert!(matches.contains(&"src/deep/mod.py".to_string()));
    assert!(matches.contains(&"src/deep/nested/core.py".to_string()));
}
