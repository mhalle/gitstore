mod common;

use gitstore::*;
use std::collections::HashSet;

fn paths(entries: &[FileEntry]) -> HashSet<String> {
    entries.iter().map(|e| e.path.clone()).collect()
}

/// Create a store with two branches: main and worker.
fn setup(dir: &std::path::Path) -> GitStore {
    let store = common::create_store(dir, "main");

    // Seed main
    let main = store.branches().get("main").unwrap();
    main.write("readme.txt", b"hello", Default::default()).unwrap();
    let main = store.branches().get("main").unwrap();
    main.write("data/x.txt", b"x-main", Default::default()).unwrap();

    // Create worker branch from main
    let main = store.branches().get("main").unwrap();
    store.branches().set("worker", &main).unwrap();

    let worker = store.branches().get("worker").unwrap();
    worker.write("results/a.json", b"{\"a\":1}", Default::default()).unwrap();
    let worker = store.branches().get("worker").unwrap();
    worker.write("results/b.json", b"{\"b\":2}", Default::default()).unwrap();
    let worker = store.branches().get("worker").unwrap();
    worker.write("data/x.txt", b"x-worker", Default::default()).unwrap();
    let worker = store.branches().get("worker").unwrap();
    worker.write("data/y.txt", b"y-worker", Default::default()).unwrap();

    store
}

// ---------------------------------------------------------------------------
// Basic
// ---------------------------------------------------------------------------

#[test]
fn copy_subtree_adds_files() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "results", None, Default::default()).unwrap();
    assert_eq!(main.read_text("results/a.json").unwrap(), "{\"a\":1}");
    assert_eq!(main.read_text("results/b.json").unwrap(), "{\"b\":2}");
    // Existing files untouched
    assert_eq!(main.read_text("readme.txt").unwrap(), "hello");
}

#[test]
fn copy_with_updates() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "data", None, Default::default()).unwrap();
    assert_eq!(main.read_text("data/x.txt").unwrap(), "x-worker");
    assert_eq!(main.read_text("data/y.txt").unwrap(), "y-worker");
}

#[test]
fn dest_defaults_to_src_path() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "results", None, Default::default()).unwrap();
    assert!(main.exists("results/a.json").unwrap());
    assert!(main.exists("results/b.json").unwrap());
}

#[test]
fn copy_to_different_dest() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main
        .copy_from_ref(&worker, "results", Some("backup/results"), Default::default())
        .unwrap();
    assert_eq!(
        main.read_text("backup/results/a.json").unwrap(),
        "{\"a\":1}"
    );
    assert_eq!(
        main.read_text("backup/results/b.json").unwrap(),
        "{\"b\":2}"
    );
    // Original path untouched
    assert!(!main.exists("results/a.json").unwrap());
}

#[test]
fn copy_root_to_root() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "", None, Default::default()).unwrap();
    assert_eq!(main.read_text("results/a.json").unwrap(), "{\"a\":1}");
    assert_eq!(main.read_text("data/x.txt").unwrap(), "x-worker");
    assert_eq!(main.read_text("data/y.txt").unwrap(), "y-worker");
    // Existing main files still present (no delete)
    assert_eq!(main.read_text("readme.txt").unwrap(), "hello");
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

#[test]
fn delete_removes_extra_dest_files() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    // First sync data/
    let main = main.copy_from_ref(&worker, "data", None, Default::default()).unwrap();
    assert!(main.exists("data/y.txt").unwrap());

    // Remove y from worker and sync with delete
    let worker = store.branches().get("worker").unwrap();
    let worker = worker
        .remove(&["data/y.txt"], Default::default())
        .unwrap();
    let _ = worker; // ensure commit
    let main = store.branches().get("main").unwrap();
    let main = main
        .copy_from_ref(
            &store.branches().get("worker").unwrap(),
            "data",
            None,
            fs::CopyFromRefOptions {
                delete: true,
                ..Default::default()
            },
        )
        .unwrap();
    assert!(main.exists("data/x.txt").unwrap());
    assert!(!main.exists("data/y.txt").unwrap());
}

#[test]
fn delete_only_affects_dest_path() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main
        .copy_from_ref(
            &worker,
            "results",
            None,
            fs::CopyFromRefOptions {
                delete: true,
                ..Default::default()
            },
        )
        .unwrap();
    // readme.txt is outside dest_path, should be untouched
    assert_eq!(main.read_text("readme.txt").unwrap(), "hello");
}

// ---------------------------------------------------------------------------
// Dry run
// ---------------------------------------------------------------------------

#[test]
fn dry_run_no_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();
    let original_hash = main.commit_hash().unwrap();

    let result = main
        .copy_from_ref(
            &worker,
            "results",
            None,
            fs::CopyFromRefOptions {
                dry_run: true,
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(result.commit_hash().unwrap(), original_hash);
    let changes = result.changes().unwrap();
    assert_eq!(changes.add.len(), 2);
    // Verify files not actually written
    assert!(!result.exists("results/a.json").unwrap());
}

#[test]
fn dry_run_with_updates() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let result = main
        .copy_from_ref(
            &worker,
            "data",
            None,
            fs::CopyFromRefOptions {
                dry_run: true,
                ..Default::default()
            },
        )
        .unwrap();
    let changes = result.changes().unwrap();
    assert_eq!(
        paths(&changes.update),
        HashSet::from(["data/x.txt".to_string()])
    );
    assert_eq!(
        paths(&changes.add),
        HashSet::from(["data/y.txt".to_string()])
    );
}

#[test]
fn dry_run_with_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    // Put extra file in main's results
    let main = main
        .write("results/extra.txt", b"extra", Default::default())
        .unwrap();

    let result = main
        .copy_from_ref(
            &worker,
            "results",
            None,
            fs::CopyFromRefOptions {
                delete: true,
                dry_run: true,
                ..Default::default()
            },
        )
        .unwrap();
    let changes = result.changes().unwrap();
    assert_eq!(
        paths(&changes.delete),
        HashSet::from(["results/extra.txt".to_string()])
    );
}

// ---------------------------------------------------------------------------
// From tag
// ---------------------------------------------------------------------------

#[test]
fn copy_from_tag() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let worker = store.branches().get("worker").unwrap();
    store.tags().set("v1.0", &worker).unwrap();

    let main = store.branches().get("main").unwrap();
    let tag_fs = store.tags().get("v1.0").unwrap();
    let main = main.copy_from_ref(&tag_fs, "results", None, Default::default()).unwrap();
    assert_eq!(main.read_text("results/a.json").unwrap(), "{\"a\":1}");
}

#[test]
fn copy_from_detached() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    // Create a tag snapshot (readonly) to use as source
    let worker = store.branches().get("worker").unwrap();
    store.tags().set("v-detached", &worker).unwrap();
    let detached = store.tags().get("v-detached").unwrap();
    assert_eq!(detached.ref_name(), Some("v-detached"));
    assert!(!detached.writable()); // confirm it's readonly

    let main = store.branches().get("main").unwrap();
    let main = main.copy_from_ref(&detached, "results", None, Default::default()).unwrap();
    assert_eq!(main.read_text("results/a.json").unwrap(), "{\"a\":1}");
}

// ---------------------------------------------------------------------------
// Noop
// ---------------------------------------------------------------------------

#[test]
fn noop_returns_same_fs() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "results", None, Default::default()).unwrap();
    let hash_after_first = main.commit_hash().unwrap();

    // Copy again — same content, should be a noop
    let worker = store.branches().get("worker").unwrap();
    let main = main.copy_from_ref(&worker, "results", None, Default::default()).unwrap();
    assert_eq!(main.commit_hash().unwrap(), hash_after_first);
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

#[test]
fn reject_cross_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store1 = common::create_store(&dir.path().join("r1"), "main");
    let store2 = common::create_store(&dir.path().join("r2"), "main");
    let fs1 = store1.branches().get("main").unwrap();
    let fs1 = fs1.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store2.branches().get("main").unwrap();
    let fs2 = fs2.write("b.txt", b"b", Default::default()).unwrap();

    let result = fs2.copy_from_ref(&fs1, "a.txt", None, Default::default());
    assert!(result.is_err());
    let err_msg = format!("{}", result.unwrap_err());
    assert!(err_msg.contains("same repo"));
}

#[test]
fn reject_readonly_dest() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let worker = store.branches().get("worker").unwrap();
    // Tags return a readonly (branch=None) Fs
    store.tags().set("v-readonly", &worker).unwrap();
    let readonly = store.tags().get("v-readonly").unwrap();

    let result = readonly.copy_from_ref(&worker, "results", None, Default::default());
    assert!(result.is_err());
}

#[test]
fn nonexistent_src_path_is_noop() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();
    let original_hash = main.commit_hash().unwrap();

    let main = main
        .copy_from_ref(&worker, "nonexistent", None, Default::default())
        .unwrap();
    assert_eq!(main.commit_hash().unwrap(), original_hash);
}

// ---------------------------------------------------------------------------
// Mode
// ---------------------------------------------------------------------------

#[test]
fn preserves_executable_mode() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let worker = store.branches().get("worker").unwrap();
    worker
        .write(
            "bin/run.sh",
            b"#!/bin/sh",
            fs::WriteOptions {
                mode: Some(MODE_BLOB_EXEC),
                ..Default::default()
            },
        )
        .unwrap();

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();
    let main = main.copy_from_ref(&worker, "bin", None, Default::default()).unwrap();
    assert_eq!(main.file_type("bin/run.sh").unwrap(), FileType::Executable);
}

#[test]
fn preserves_symlink() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let worker = store.branches().get("worker").unwrap();
    worker
        .write_symlink("links/readme", "../readme.txt", Default::default())
        .unwrap();

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();
    let main = main.copy_from_ref(&worker, "links", None, Default::default()).unwrap();
    assert_eq!(main.file_type("links/readme").unwrap(), FileType::Link);
    assert_eq!(main.readlink("links/readme").unwrap(), "../readme.txt");
}

// ---------------------------------------------------------------------------
// Message
// ---------------------------------------------------------------------------

#[test]
fn custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main
        .copy_from_ref(
            &worker,
            "results",
            None,
            fs::CopyFromRefOptions {
                message: Some("Import results from worker".into()),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(main.message().unwrap(), "Import results from worker");
}

#[test]
fn auto_message() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    let main = main.copy_from_ref(&worker, "results", None, Default::default()).unwrap();
    let msg = main.message().unwrap();
    assert!(!msg.is_empty());
}

// ---------------------------------------------------------------------------
// Stale
// ---------------------------------------------------------------------------

#[test]
fn stale_snapshot_propagates() {
    let dir = tempfile::tempdir().unwrap();
    let store = setup(dir.path());

    let main = store.branches().get("main").unwrap();
    let worker = store.branches().get("worker").unwrap();

    // Advance main behind our back
    let main2 = store.branches().get("main").unwrap();
    main2.write("conflict.txt", b"conflict", Default::default()).unwrap();

    let result = main.copy_from_ref(&worker, "results", None, Default::default());
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, Error::StaleSnapshot(_)));
}
