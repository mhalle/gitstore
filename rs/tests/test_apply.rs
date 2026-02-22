mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// WriteEntry construction
// ---------------------------------------------------------------------------

#[test]
fn write_entry_from_bytes() {
    let e = WriteEntry::from_bytes(b"data".to_vec());
    assert_eq!(e.data.as_deref(), Some(b"data".as_ref()));
    assert!(e.target.is_none());
    assert_eq!(e.mode, MODE_BLOB);
}

#[test]
fn write_entry_from_text() {
    let e = WriteEntry::from_text("hello");
    assert_eq!(e.data.as_deref(), Some(b"hello".as_ref()));
    assert!(e.target.is_none());
    assert_eq!(e.mode, MODE_BLOB);
}

#[test]
fn write_entry_symlink() {
    let e = WriteEntry::symlink("target.txt");
    assert!(e.data.is_none());
    assert_eq!(e.target.as_deref(), Some("target.txt"));
    assert_eq!(e.mode, MODE_LINK);
}

// ---------------------------------------------------------------------------
// WriteEntry validation
// ---------------------------------------------------------------------------

#[test]
fn write_entry_validate_blob_ok() {
    let e = WriteEntry::from_bytes(b"data".to_vec());
    assert!(e.validate().is_ok());
}

#[test]
fn write_entry_validate_symlink_ok() {
    let e = WriteEntry::symlink("target");
    assert!(e.validate().is_ok());
}

#[test]
fn write_entry_validate_symlink_without_target() {
    let e = WriteEntry {
        data: None,
        target: None,
        mode: MODE_LINK,
    };
    assert!(e.validate().is_err());
}

#[test]
fn write_entry_validate_symlink_with_data() {
    let e = WriteEntry {
        data: Some(b"data".to_vec()),
        target: Some("target".into()),
        mode: MODE_LINK,
    };
    assert!(e.validate().is_err());
}

#[test]
fn write_entry_validate_blob_without_data() {
    let e = WriteEntry {
        data: None,
        target: None,
        mode: MODE_BLOB,
    };
    assert!(e.validate().is_err());
}

#[test]
fn write_entry_validate_blob_with_target() {
    let e = WriteEntry {
        data: Some(b"data".to_vec()),
        target: Some("target".into()),
        mode: MODE_BLOB,
    };
    assert!(e.validate().is_err());
}

#[test]
fn write_entry_validate_exec_ok() {
    let e = WriteEntry {
        data: Some(b"#!/bin/sh".to_vec()),
        target: None,
        mode: MODE_BLOB_EXEC,
    };
    assert!(e.validate().is_ok());
}

#[test]
fn write_entry_validate_unsupported_mode() {
    let e = WriteEntry {
        data: Some(b"data".to_vec()),
        target: None,
        mode: 0o777777,
    };
    assert!(e.validate().is_err());
}

// ---------------------------------------------------------------------------
// apply — basic writes
// ---------------------------------------------------------------------------

#[test]
fn apply_single_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.apply(
        &[("data.bin", WriteEntry::from_bytes(b"\x00\x01\x02".to_vec()))],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("data.bin").unwrap(), b"\x00\x01\x02");
}

#[test]
fn apply_single_text() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.apply(
        &[("hello.txt", WriteEntry::from_text("hello world"))],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "hello world");
}

#[cfg(unix)]
#[test]
fn apply_symlink_entry() {
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
fn apply_executable_entry() {
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
    assert_eq!(fs.read("run.sh").unwrap(), b"#!/bin/sh");
}

// ---------------------------------------------------------------------------
// apply — multiple entries
// ---------------------------------------------------------------------------

#[test]
fn apply_multiple_entries_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    fs.apply(
        &[
            ("a.txt", WriteEntry::from_text("aaa")),
            ("b.txt", WriteEntry::from_text("bbb")),
            ("c.txt", WriteEntry::from_text("ccc")),
        ],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_ne!(fs.commit_hash().unwrap(), hash_before);
    assert_eq!(fs.read_text("a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("b.txt").unwrap(), "bbb");
    assert_eq!(fs.read_text("c.txt").unwrap(), "ccc");

    // Single commit
    let log = fs.log(fs::LogOptions { limit: Some(5), ..Default::default() }).unwrap();
    assert_eq!(log.len(), 2); // init + apply
}

#[cfg(unix)]
#[test]
fn apply_mixed_types() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let exec_entry = WriteEntry {
        data: Some(b"#!/bin/sh".to_vec()),
        target: None,
        mode: MODE_BLOB_EXEC,
    };
    fs.apply(
        &[
            ("file.txt", WriteEntry::from_bytes(b"data".to_vec())),
            ("link", WriteEntry::symlink("file.txt")),
            ("script.sh", exec_entry),
        ],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.file_type("file.txt").unwrap(), FileType::Blob);
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
    assert_eq!(fs.file_type("script.sh").unwrap(), FileType::Executable);
}

// ---------------------------------------------------------------------------
// apply — nested paths
// ---------------------------------------------------------------------------

#[test]
fn apply_nested_paths() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    fs.apply(
        &[
            ("a/b/c/deep.txt", WriteEntry::from_text("deep")),
            ("a/b/sibling.txt", WriteEntry::from_text("sibling")),
        ],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("a/b/c/deep.txt").unwrap(), "deep");
    assert_eq!(fs.read_text("a/b/sibling.txt").unwrap(), "sibling");
    assert!(fs.is_dir("a").unwrap());
    assert!(fs.is_dir("a/b").unwrap());
}

// ---------------------------------------------------------------------------
// apply — custom message
// ---------------------------------------------------------------------------

#[test]
fn apply_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    fs.apply(
        &[("x.txt", WriteEntry::from_text("x"))],
        &[],
        fs::ApplyOptions {
            message: Some("custom apply msg".into()),
        },
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "custom apply msg");
}

// ---------------------------------------------------------------------------
// apply — no-op
// ---------------------------------------------------------------------------

#[test]
fn apply_noop_identical_content() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    fs.apply(
        &[("a.txt", WriteEntry::from_text("aaa"))],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash1 = fs.commit_hash().unwrap();

    // Same content again
    fs.apply(
        &[("a.txt", WriteEntry::from_text("aaa"))],
        &[],
        Default::default(),
    )
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let hash2 = fs.commit_hash().unwrap();

    assert_eq!(hash1, hash2);
}

// ---------------------------------------------------------------------------
// apply — stale
// ---------------------------------------------------------------------------

#[test]
fn apply_stale_snapshot_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs_old = store.branches().get("main").unwrap();

    // Advance
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
// apply — empty
// ---------------------------------------------------------------------------

#[test]
fn apply_empty_is_noop() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    fs.apply(&[], &[], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}

// ---------------------------------------------------------------------------
// apply — overwrite existing
// ---------------------------------------------------------------------------

#[test]
fn apply_overwrites_existing() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    fs.apply(
        &[("hello.txt", WriteEntry::from_text("overwritten"))],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "overwritten");
    // Other files preserved
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
}

// ---------------------------------------------------------------------------
// apply — invalid entry validation
// ---------------------------------------------------------------------------

#[test]
fn apply_invalid_entry_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let bad = WriteEntry {
        data: None,
        target: None,
        mode: MODE_BLOB,
    };
    assert!(fs.apply(&[("bad.txt", bad)], &[], Default::default()).is_err());
}

// ---------------------------------------------------------------------------
// apply — empty data
// ---------------------------------------------------------------------------

#[test]
fn apply_empty_file() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    fs.apply(
        &[("empty.txt", WriteEntry::from_bytes(vec![]))],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("empty.txt").unwrap(), b"");
    assert_eq!(fs.size("empty.txt").unwrap(), 0);
}

// ---------------------------------------------------------------------------
// apply — binary data
// ---------------------------------------------------------------------------

#[test]
fn apply_binary_data() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    let data: Vec<u8> = (0u8..=255).collect();
    fs.apply(
        &[("binary.bin", WriteEntry::from_bytes(data.clone()))],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("binary.bin").unwrap(), data);
}

// ---------------------------------------------------------------------------
// apply — preserves other files
// ---------------------------------------------------------------------------

#[test]
fn apply_preserves_existing_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    fs.apply(
        &[("new.txt", WriteEntry::from_text("new"))],
        &[],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("hello.txt").unwrap(), "hello");
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
    assert_eq!(fs.read_text("new.txt").unwrap(), "new");
}

// ---------------------------------------------------------------------------
// apply — removes
// ---------------------------------------------------------------------------

#[test]
fn apply_removes_single() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    fs.apply(&[], &["hello.txt"], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    // Other files preserved
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
}

#[test]
fn apply_removes_multiple() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    fs.apply(&[], &["hello.txt", "dir/a.txt"], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn apply_writes_and_removes_combined() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());

    fs.apply(
        &[("new.txt", WriteEntry::from_text("new"))],
        &["hello.txt"],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("new.txt").unwrap(), "new");
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
}

#[test]
fn apply_writes_and_removes_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    let log_before = fs.log(Default::default()).unwrap();

    fs.apply(
        &[("new.txt", WriteEntry::from_text("new"))],
        &["hello.txt"],
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    let log_after = fs.log(Default::default()).unwrap();
    assert_eq!(log_after.len(), log_before.len() + 1);
}

#[test]
fn apply_removes_only_is_noop_for_empty() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash_before = fs.commit_hash().unwrap();

    // No writes, no removes
    fs.apply(&[], &[], Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
}
