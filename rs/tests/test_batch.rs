mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

#[test]
fn batch_multiple_writes_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("a.txt", b"aaa").unwrap();
    batch.write("b.txt", b"bbb").unwrap();
    batch.write("c.txt", b"ccc").unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_ne!(fs.commit_hash().unwrap(), hash_before);
    assert_eq!(fs.read_text("a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("b.txt").unwrap(), "bbb");
    assert_eq!(fs.read_text("c.txt").unwrap(), "ccc");

    // Only one commit was added (not three)
    let log = fs.log(fs::LogOptions { limit: Some(5), skip: None }).unwrap();
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

    let fs = store.fs(Some("main")).unwrap();
    assert!(fs.exists("new.txt").unwrap());
    assert!(!fs.exists("hello.txt").unwrap());
}

#[test]
fn batch_empty_no_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let hash_before = fs.commit_hash().unwrap();

    let batch = fs.batch(Default::default());
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}

// ---------------------------------------------------------------------------
// Ordering
// ---------------------------------------------------------------------------

#[test]
fn batch_last_op_wins_remove() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("file.txt", b"data").unwrap();
    batch.remove("file.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
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

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "replaced");
}

// ---------------------------------------------------------------------------
// Closed guard
// ---------------------------------------------------------------------------

#[test]
fn batch_write_after_commit_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();

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
    let fs_old = store.fs(Some("main")).unwrap();

    // Advance branch
    let fs_new = store.fs(Some("main")).unwrap();
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
    let fs = store.fs(Some("main")).unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write_from_file("imported.txt", &src_file).unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
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
    let fs = store.fs(Some("main")).unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write_from_file("run.sh", &src_file).unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
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
    let fs = store.fs(Some("main")).unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write_with_mode("exec.sh", b"#!/bin/sh", MODE_BLOB_EXEC).unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
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
    let fs = store.fs(Some("main")).unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("target.txt", b"data").unwrap();
    batch.write_symlink("link", "target.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
    assert_eq!(fs.readlink("link").unwrap(), "target.txt");
}

#[cfg(unix)]
#[test]
fn batch_mixed_ops() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();

    let mut batch = fs.batch(Default::default());
    batch.write("file.txt", b"data").unwrap();
    batch.write_with_mode("exec.sh", b"#!/bin/sh", MODE_BLOB_EXEC).unwrap();
    batch.write_symlink("link", "file.txt").unwrap();
    batch.commit().unwrap();

    let fs = store.fs(Some("main")).unwrap();
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

    let fs = store.fs(Some("main")).unwrap();
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

    let fs = store.fs(Some("main")).unwrap();
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

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "rewritten");
}
