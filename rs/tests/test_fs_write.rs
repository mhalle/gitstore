mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// write
// ---------------------------------------------------------------------------

#[test]
fn write_changes_commit_hash() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    fs.write("new.txt", b"data", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    assert_ne!(fs2.commit_hash().unwrap(), hash_before);
}

#[test]
fn write_old_fs_unchanged() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    fs.write("new.txt", b"data", Default::default()).unwrap();
    // Old fs still has old commit hash
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}

#[test]
fn write_data_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("data.bin", b"\x00\x01\x02\xff", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("data.bin").unwrap(), b"\x00\x01\x02\xff");
}

#[test]
fn write_nested_paths() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a/b/c/deep.txt", b"deep", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("a/b/c/deep.txt").unwrap(), "deep");
}

#[test]
fn write_branch_advances() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs1 = store.branches().get("main").unwrap();
    let h1 = fs1.commit_hash().unwrap();

    fs1.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    fs2.write("b.txt", b"b", Default::default()).unwrap();
    let fs3 = store.branches().get("main").unwrap();
    let h3 = fs3.commit_hash().unwrap();

    assert_ne!(h1, h2);
    assert_ne!(h2, h3);
}

#[test]
fn write_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("x.txt", b"x", fs::WriteOptions {
        message: Some("custom msg".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "custom msg");
}

#[cfg(unix)]
#[test]
fn write_with_executable_mode() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("run.sh", b"#!/bin/sh", fs::WriteOptions {
        mode: Some(MODE_BLOB_EXEC),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("run.sh").unwrap(), FileType::Executable);
    assert_eq!(fs.read("run.sh").unwrap(), b"#!/bin/sh");
}

// ---------------------------------------------------------------------------
// write_text
// ---------------------------------------------------------------------------

#[test]
fn write_text_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_text("msg.txt", "hello world", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("msg.txt").unwrap(), "hello world");
}

// ---------------------------------------------------------------------------
// write_symlink
// ---------------------------------------------------------------------------

#[cfg(unix)]
#[test]
fn write_symlink_basic() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "target.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(fs.exists("link").unwrap());
}

#[cfg(unix)]
#[test]
fn write_symlink_file_type() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "target.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
}

#[cfg(unix)]
#[test]
fn write_symlink_readlink() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "some/target", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.readlink("link").unwrap(), "some/target");
}

// ---------------------------------------------------------------------------
// write_from_file
// ---------------------------------------------------------------------------

#[test]
fn write_from_file_basic() {
    let dir = tempfile::tempdir().unwrap();
    let src_file = dir.path().join("source.txt");
    std::fs::write(&src_file, b"from disk").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_from_file("imported.txt", &src_file, Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("imported.txt").unwrap(), "from disk");
}

#[cfg(unix)]
#[test]
fn write_from_file_preserves_executable() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let src_file = dir.path().join("run.sh");
    std::fs::write(&src_file, b"#!/bin/sh").unwrap();
    std::fs::set_permissions(&src_file, std::fs::Permissions::from_mode(0o755)).unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_from_file("run.sh", &src_file, Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("run.sh").unwrap(), FileType::Executable);
}

#[test]
fn write_from_file_missing_source_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    assert!(
        fs.write_from_file("x.txt", &dir.path().join("nope.txt"), Default::default())
            .is_err()
    );
}

// ---------------------------------------------------------------------------
// stale snapshot
// ---------------------------------------------------------------------------

#[test]
fn write_on_stale_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs_old = store.branches().get("main").unwrap();

    // Advance branch
    let fs_new = store.branches().get("main").unwrap();
    fs_new.write("advance.txt", b"go", Default::default()).unwrap();

    // Old snapshot is stale
    let result = fs_old.write("stale.txt", b"fail", Default::default());
    assert!(result.is_err());
    assert!(matches!(result.unwrap_err(), Error::StaleSnapshot(_)));
}

#[test]
fn batch_on_stale_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs_old = store.branches().get("main").unwrap();

    // Advance branch
    let fs_new = store.branches().get("main").unwrap();
    fs_new.write("advance.txt", b"go", Default::default()).unwrap();

    // Batch from old snapshot
    let mut batch = fs_old.batch(Default::default());
    batch.write("stale.txt", b"fail").unwrap();
    let result = batch.commit();
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// no-op
// ---------------------------------------------------------------------------

#[test]
fn noop_identical_content_same_hash() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"hello", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash1 = fs.commit_hash().unwrap();

    // Write same content again
    fs.write("a.txt", b"hello", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash2 = fs.commit_hash().unwrap();

    assert_eq!(hash1, hash2);
}

// ---------------------------------------------------------------------------
// apply
// ---------------------------------------------------------------------------

#[test]
fn apply_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.apply(
        &[
            ("a.txt", WriteEntry::from_bytes(b"aaa".to_vec())),
            ("b.txt", WriteEntry::from_bytes(b"bbb".to_vec())),
        ],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("b.txt").unwrap(), "bbb");
}

#[cfg(unix)]
#[test]
fn apply_symlink() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.apply(
        &[("link", WriteEntry::symlink("target.txt"))],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
    assert_eq!(fs.readlink("link").unwrap(), "target.txt");
}

#[cfg(unix)]
#[test]
fn apply_executable() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let entry = WriteEntry {
        data: Some(b"#!/bin/sh".to_vec()),
        target: None,
        mode: MODE_BLOB_EXEC,
    };
    fs.apply(&[("run.sh", entry)], &[], Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("run.sh").unwrap(), FileType::Executable);
}

#[test]
fn apply_multiple() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();
    fs.apply(
        &[
            ("x.txt", WriteEntry::from_text("x")),
            ("y.txt", WriteEntry::from_text("y")),
            ("z.txt", WriteEntry::from_text("z")),
        ],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    // Single commit for all three
    assert_ne!(fs.commit_hash().unwrap(), hash_before);
    assert_eq!(fs.read_text("x.txt").unwrap(), "x");
    assert_eq!(fs.read_text("y.txt").unwrap(), "y");
    assert_eq!(fs.read_text("z.txt").unwrap(), "z");
}

#[test]
fn apply_stale_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs_old = store.branches().get("main").unwrap();

    let fs_new = store.branches().get("main").unwrap();
    fs_new.write("advance.txt", b"go", Default::default()).unwrap();

    let result = fs_old.apply(
        &[("stale.txt", WriteEntry::from_text("fail"))],
        &[],
        Default::default(),
    );
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// rename
// ---------------------------------------------------------------------------

#[test]
fn rename_file() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "goodbye.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("goodbye.txt").unwrap(), "hello");
}

#[test]
fn rename_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("dir", "renamed", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir").unwrap());
    assert_eq!(fs.read_text("renamed/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("renamed/b.txt").unwrap(), "bbb");
}

#[test]
fn rename_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.rename("nope.txt", "also_nope.txt", Default::default()).is_err());
}

// ---------------------------------------------------------------------------
// retry_write
// ---------------------------------------------------------------------------

#[test]
fn retry_write_succeeds() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let result = fs::retry_write(|| {
        let fs = store.branches().get("main").unwrap();
        fs.write("retried.txt", b"ok", Default::default())
    });
    assert!(result.is_ok());
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("retried.txt").unwrap(), "ok");
}

// ---------------------------------------------------------------------------
// write — edge cases
// ---------------------------------------------------------------------------

#[test]
fn write_empty_data() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("empty.txt", b"", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("empty.txt").unwrap(), b"");
}

#[test]
fn write_overwrite_existing() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.write("hello.txt", b"overwritten", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "overwritten");
}

#[test]
fn write_binary_with_null_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let data: Vec<u8> = (0u8..=255).collect();
    fs.write("binary.bin", &data, Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("binary.bin").unwrap(), data);
    assert_eq!(fs.size("binary.bin").unwrap(), 256);
}

#[test]
fn write_preserves_other_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.write("new.txt", b"new", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    // Existing files still present
    assert_eq!(fs.read_text("hello.txt").unwrap(), "hello");
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("new.txt").unwrap(), "new");
}

// ---------------------------------------------------------------------------
// write_symlink — edge cases
// ---------------------------------------------------------------------------

#[cfg(unix)]
#[test]
fn write_symlink_nested_target() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "a/b/c/deep.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.readlink("link").unwrap(), "a/b/c/deep.txt");
}

#[cfg(unix)]
#[test]
fn read_on_symlink_returns_target_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "target.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    // read() on symlink returns the target path as bytes
    assert_eq!(fs.read("link").unwrap(), b"target.txt");
}

#[cfg(unix)]
#[test]
fn write_symlink_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "target.txt", fs::WriteOptions {
        message: Some("add symlink".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "add symlink");
}

// ---------------------------------------------------------------------------
// retry_write — stale retry
// ---------------------------------------------------------------------------

#[test]
fn retry_write_retries_on_stale() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let attempt = AtomicUsize::new(0);

    let result = fs::retry_write(|| {
        let n = attempt.fetch_add(1, Ordering::SeqCst);
        let fs = store.branches().get("main").unwrap();
        if n == 0 {
            // Simulate stale by advancing the branch before writing
            let fs2 = store.branches().get("main").unwrap();
            fs2.write("advance.txt", b"go", Default::default()).unwrap();
            // Now fs is stale
            fs.write("retried.txt", b"ok", Default::default())
        } else {
            // Second attempt gets fresh fs, should succeed
            fs.write("retried.txt", b"ok", Default::default())
        }
    });
    assert!(result.is_ok());
    assert!(attempt.load(Ordering::SeqCst) >= 2);
}

// ---------------------------------------------------------------------------
// write — detached errors
// ---------------------------------------------------------------------------

#[test]
fn write_on_detached_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    let detached = fs.back(1).unwrap();
    let result = detached.write("x.txt", b"x", Default::default());
    assert!(result.is_err());
}

#[test]
fn batch_on_detached_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    let detached = fs.back(1).unwrap();
    let mut batch = detached.batch(Default::default());
    batch.write("x.txt", b"x").unwrap();
    let result = batch.commit();
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// write — large and unicode edge cases
// ---------------------------------------------------------------------------

#[test]
fn write_large_binary() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let data: Vec<u8> = (0..1_000_000).map(|i| (i % 256) as u8).collect();
    fs.write("large.bin", &data, Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("large.bin").unwrap(), data);
    assert_eq!(fs.size("large.bin").unwrap(), 1_000_000);
}

#[test]
fn write_unicode_filename() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("café.txt", b"latte", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("café.txt").unwrap(), "latte");
}

#[test]
fn write_deep_nested_path() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let deep_path = "a/b/c/d/e/f/g/h/i/j/k/deep.txt";
    fs.write(deep_path, b"very deep", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text(deep_path).unwrap(), "very deep");
}

#[test]
fn noop_write_same_text_no_new_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_text("a.txt", "hello", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash1 = fs.commit_hash().unwrap();

    // Write same text content again
    fs.write_text("a.txt", "hello", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash2 = fs.commit_hash().unwrap();

    assert_eq!(hash1, hash2);
}

// ---------------------------------------------------------------------------
// remove via batch — custom message
// ---------------------------------------------------------------------------

#[test]
fn remove_file_via_batch_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let mut batch = fs.batch(fs::BatchOptions {
        message: Some("remove hello".into()),
    });
    batch.remove("hello.txt").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "remove hello");
}

// ---------------------------------------------------------------------------
// remove via batch
// ---------------------------------------------------------------------------

#[test]
fn remove_file_via_batch() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let mut batch = fs.batch(Default::default());
    batch.remove("hello.txt").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    // Other files still present
    assert!(fs.exists("dir/a.txt").unwrap());
}

#[test]
fn remove_nested_file_via_batch() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let mut batch = fs.batch(Default::default());
    batch.remove("dir/a.txt").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert!(fs.exists("dir/b.txt").unwrap());
}

// ---------------------------------------------------------------------------
// rename — edge cases
// ---------------------------------------------------------------------------

#[test]
fn rename_preserves_other_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "renamed.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    // dir/* still present
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn rename_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let log_before = fs.log(Default::default()).unwrap();
    fs.rename("hello.txt", "renamed.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let log_after = fs.log(Default::default()).unwrap();
    // Rename adds exactly one commit
    assert_eq!(log_after.len(), log_before.len() + 1);
}

#[test]
fn rename_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "moved.txt", fs::WriteOptions {
        message: Some("move file".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "move file");
}

// ---------------------------------------------------------------------------
// remove (repo-level)
// ---------------------------------------------------------------------------

#[test]
fn remove_single_file() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let new_fs = fs.remove(&["hello.txt"], Default::default()).unwrap();

    // Verify via the returned Fs
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");

    // Changes report attached
    let changes = new_fs.changes().unwrap();
    assert_eq!(changes.delete.len(), 1);
    assert_eq!(changes.delete[0].path, "hello.txt");
}

#[test]
fn remove_multiple_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.remove(&["hello.txt", "dir/a.txt"], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn remove_directory_requires_recursive() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let result = fs.remove(&["dir"], Default::default());
    assert!(result.is_err());
}

#[test]
fn remove_directory_recursive() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let new_fs = fs.remove(&["dir"], fs::RemoveOptions {
        recursive: true,
        ..Default::default()
    })
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert!(!fs.exists("dir/b.txt").unwrap());
    assert_eq!(fs.read_text("hello.txt").unwrap(), "hello");

    let changes = new_fs.changes().unwrap();
    assert_eq!(changes.delete.len(), 2);
}

#[test]
fn remove_nonexistent_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.remove(&["missing.txt"], Default::default()).is_err());
}

#[test]
fn remove_dry_run() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let hash_before = fs.commit_hash().unwrap();

    let new_fs = fs.remove(&["hello.txt"], fs::RemoveOptions {
        dry_run: true,
        ..Default::default()
    })
    .unwrap();

    // No commit was made
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
    assert!(fs.exists("hello.txt").unwrap());

    // But report shows what would be deleted
    let changes = new_fs.changes().unwrap();
    assert_eq!(changes.delete.len(), 1);
    assert_eq!(changes.delete[0].path, "hello.txt");
}

#[test]
fn remove_dry_run_recursive() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let hash_before = fs.commit_hash().unwrap();

    let new_fs = fs.remove(&["dir"], fs::RemoveOptions {
        recursive: true,
        dry_run: true,
        ..Default::default()
    })
    .unwrap();

    // No commit
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);

    // Report shows planned deletes
    let changes = new_fs.changes().unwrap();
    assert_eq!(changes.delete.len(), 2);
}

#[test]
fn remove_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.remove(&["hello.txt"], fs::RemoveOptions {
        message: Some("deleted hello".into()),
        ..Default::default()
    })
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "deleted hello");
}

#[test]
fn remove_is_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let log_before = fs.log(Default::default()).unwrap();

    fs.remove(&["hello.txt", "dir/a.txt"], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    let log_after = fs.log(Default::default()).unwrap();
    assert_eq!(log_after.len(), log_before.len() + 1);
}
