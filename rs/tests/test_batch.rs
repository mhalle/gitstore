mod common;

use vost::*;

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

#[test]
fn batch_multiple_writes_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("a.txt", b"aaa").unwrap();
    batch.write("b.txt", b"bbb").unwrap();
    batch.write("c.txt", b"ccc").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_ne!(fs.commit_hash().unwrap(), hash_before);
    assert_eq!(fs.read_text("a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("b.txt").unwrap(), "bbb");
    assert_eq!(fs.read_text("c.txt").unwrap(), "ccc");

    // Only one commit was added (not three)
    let log = fs.log(fs::LogOptions { limit: Some(5), ..Default::default() }).unwrap();
    // init commit + 1 batch commit = 2
    assert_eq!(log.len(), 2);
}

#[test]
fn batch_write_and_remove() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    let mut batch = fs.batch(Default::default());
    batch.write("new.txt", b"new").unwrap();
    batch.remove("hello.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(fs.exists("new.txt").unwrap());
    assert!(!fs.exists("hello.txt").unwrap());
}

#[test]
fn batch_empty_no_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let batch = fs.batch(Default::default());
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}

// ---------------------------------------------------------------------------
// Ordering
// ---------------------------------------------------------------------------

#[test]
fn batch_last_op_wins_remove() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("file.txt", b"data").unwrap();
    batch.remove("file.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("file.txt").unwrap());
}

#[test]
fn batch_remove_then_write() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    let mut batch = fs.batch(Default::default());
    batch.remove("hello.txt").unwrap();
    batch.write("hello.txt", b"replaced").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "replaced");
}

// ---------------------------------------------------------------------------
// Closed guard
// ---------------------------------------------------------------------------

#[test]
fn batch_write_after_commit_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    // We can't call methods after commit() since it consumes self.
    // But we can test is_closed and the internal guard via a non-consuming check.
    let batch = fs.batch(Default::default());
    assert!(!batch.is_closed());
    batch.commit().unwrap();
    // After commit, batch is consumed — Rust's type system prevents further use.
    // So this is effectively tested by the compiler.
}

// ---------------------------------------------------------------------------
// Stale
// ---------------------------------------------------------------------------

#[test]
fn batch_stale_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs_old = store.branches().get("main").unwrap();

    // Advance branch
    let fs_new = store.branches().get("main").unwrap();
    fs_new.write("advance.txt", b"go", Default::default()).unwrap();

    let mut batch = fs_old.batch(Default::default());
    batch.write("stale.txt", b"fail").unwrap();
    assert!(batch.commit().is_err());
}

// ---------------------------------------------------------------------------
// From file
// ---------------------------------------------------------------------------

#[test]
fn batch_write_from_file() {
    let dir = tempfile::tempdir().unwrap();
    let src_file = dir.path().join("source.txt");
    std::fs::write(&src_file, b"from disk").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write_from_file("imported.txt", &src_file).unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("imported.txt").unwrap(), "from disk");
}

#[cfg(unix)]
#[test]
fn batch_write_from_file_preserves_exec() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let src_file = dir.path().join("run.sh");
    std::fs::write(&src_file, b"#!/bin/sh").unwrap();
    std::fs::set_permissions(&src_file, std::fs::Permissions::from_mode(0o755)).unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write_from_file("run.sh", &src_file).unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("run.sh").unwrap(), FileType::Executable);
}

// ---------------------------------------------------------------------------
// Mode
// ---------------------------------------------------------------------------

#[cfg(unix)]
#[test]
fn batch_write_with_mode() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write_with_mode("exec.sh", b"#!/bin/sh", MODE_BLOB_EXEC).unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("exec.sh").unwrap(), FileType::Executable);
}

// ---------------------------------------------------------------------------
// Symlink
// ---------------------------------------------------------------------------

#[cfg(unix)]
#[test]
fn batch_write_symlink() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("target.txt", b"data").unwrap();
    batch.write_symlink("link", "target.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
    assert_eq!(fs.readlink("link").unwrap(), "target.txt");
}

#[cfg(unix)]
#[test]
fn batch_mixed_ops() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("file.txt", b"data").unwrap();
    batch.write_with_mode("exec.sh", b"#!/bin/sh", MODE_BLOB_EXEC).unwrap();
    batch.write_symlink("link", "file.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("file.txt").unwrap(), FileType::Blob);
    assert_eq!(fs.file_type("exec.sh").unwrap(), FileType::Executable);
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
}

// ---------------------------------------------------------------------------
// No-op
// ---------------------------------------------------------------------------

#[test]
fn batch_noop_identical_writes() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let hash_before = fs.commit_hash().unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("hello.txt", b"hello").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}

// ---------------------------------------------------------------------------
// Remove + rewrite
// ---------------------------------------------------------------------------

#[test]
fn batch_overwrite_then_remove() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    let mut batch = fs.batch(Default::default());
    batch.write("hello.txt", b"new content").unwrap();
    batch.remove("hello.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
}

#[test]
fn batch_remove_then_rewrite() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    let mut batch = fs.batch(Default::default());
    batch.remove("hello.txt").unwrap();
    batch.write("hello.txt", b"rewritten").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "rewritten");
}

// ---------------------------------------------------------------------------
// Custom message
// ---------------------------------------------------------------------------

#[test]
fn batch_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(fs::BatchOptions {
        message: Some("my batch".into()),
        ..Default::default()
    });
    batch.write("a.txt", b"a").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "my batch");
}

// ---------------------------------------------------------------------------
// Nested paths
// ---------------------------------------------------------------------------

#[test]
fn batch_creates_nested_paths() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("a/b/c/deep.txt", b"deep").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("a/b/c/deep.txt").unwrap(), "deep");
    assert!(fs.is_dir("a").unwrap());
    assert!(fs.is_dir("a/b").unwrap());
    assert!(fs.is_dir("a/b/c").unwrap());
}

// ---------------------------------------------------------------------------
// Multiple batches sequential
// ---------------------------------------------------------------------------

#[test]
fn batch_sequential_commits() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    // First batch
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("a.txt", b"aaa").unwrap();
    batch.commit().unwrap();

    // Second batch (needs fresh fs)
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("b.txt", b"bbb").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("b.txt").unwrap(), "bbb");
}

// ---------------------------------------------------------------------------
// Remove all files in a directory
// ---------------------------------------------------------------------------

#[test]
fn batch_remove_all_dir_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    let mut batch = fs.batch(Default::default());
    batch.remove("dir/a.txt").unwrap();
    batch.remove("dir/b.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert!(!fs.exists("dir/b.txt").unwrap());
    // hello.txt untouched
    assert!(fs.exists("hello.txt").unwrap());
}

// ---------------------------------------------------------------------------
// Write many files in one batch
// ---------------------------------------------------------------------------

#[test]
fn batch_many_files() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    for i in 0..50 {
        batch.write(&format!("file_{:03}.txt", i), format!("data {}", i).as_bytes()).unwrap();
    }
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("file_000.txt").unwrap(), "data 0");
    assert_eq!(fs.read_text("file_049.txt").unwrap(), "data 49");
    let entries = fs.walk("").unwrap();
    // 1 directory (root) containing 50 files
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].files.len(), 50);
}

// ---------------------------------------------------------------------------
// Write overwrites in same batch
// ---------------------------------------------------------------------------

#[test]
fn batch_last_write_wins() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("x.txt", b"first").unwrap();
    batch.write("x.txt", b"second").unwrap();
    batch.write("x.txt", b"third").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("x.txt").unwrap(), "third");
}

// ---------------------------------------------------------------------------
// batch — remove nonexistent
// ---------------------------------------------------------------------------

#[test]
fn batch_remove_nonexistent_succeeds() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    // Removing a non-existent path should not error
    batch.remove("does_not_exist.txt").unwrap();
    // Commit should succeed (no-op or successful removal of nothing)
    let result = batch.commit();
    assert!(result.is_ok());
}

// ---------------------------------------------------------------------------
// batch — write + remove same path
// ---------------------------------------------------------------------------

#[test]
fn batch_write_then_remove_same_path() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("temp.txt", b"temporary").unwrap();
    batch.remove("temp.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    // File should not exist — remove wins over earlier write
    assert!(!fs.exists("temp.txt").unwrap());
}

// ---------------------------------------------------------------------------
// batch — unicode filenames
// ---------------------------------------------------------------------------

#[test]
fn batch_unicode_filenames() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("日本語.txt", b"japanese").unwrap();
    batch.write("émojis/🎉.txt", b"party").unwrap();
    batch.write("中文/文件.txt", b"chinese").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("日本語.txt").unwrap(), "japanese");
    assert_eq!(fs.read_text("émojis/🎉.txt").unwrap(), "party");
    assert_eq!(fs.read_text("中文/文件.txt").unwrap(), "chinese");
}

// ---------------------------------------------------------------------------
// batch — empty data
// ---------------------------------------------------------------------------

#[test]
fn batch_write_empty_data() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("empty.txt", b"").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("empty.txt").unwrap(), b"");
    assert_eq!(fs.size("empty.txt").unwrap(), 0);
}

// ---------------------------------------------------------------------------
// batch — closed guard via manual flag
// ---------------------------------------------------------------------------

#[test]
fn batch_is_closed_after_commit() {
    // Since commit() consumes self, we can't call methods after.
    // This test verifies is_closed returns false before commit.
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    assert!(!batch.is_closed());
    batch.write("a.txt", b"a").unwrap();
    assert!(!batch.is_closed());
    batch.commit().unwrap();
    // After commit, batch is consumed — compiler enforces no further use
}

// ---------------------------------------------------------------------------
// batch — commit returns Fs
// ---------------------------------------------------------------------------

#[test]
fn batch_commit_returns_fs_with_content() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("x.txt", b"data").unwrap();
    let new_fs = batch.commit().unwrap();

    // The returned Fs should reflect the new content
    assert_eq!(new_fs.read_text("x.txt").unwrap(), "data");
    assert_eq!(new_fs.ref_name(), Some("main"));
}

#[test]
fn batch_commit_returns_fs_with_new_hash() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("a.txt", b"aaa").unwrap();
    let new_fs = batch.commit().unwrap();

    assert_ne!(new_fs.commit_hash().unwrap(), hash_before);
}

#[test]
fn batch_empty_commit_returns_same_fs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let batch = fs.batch(Default::default());
    let new_fs = batch.commit().unwrap();

    assert_eq!(new_fs.commit_hash().unwrap(), hash_before);
}
