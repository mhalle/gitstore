mod common;

use std::path::Path;
use vost::fs::WriteOptions;
use vost::*;

fn create_remote_path(dir: &Path) -> String {
    dir.join("remote.git").to_string_lossy().to_string()
}

// ---------------------------------------------------------------------------
// backup
// ---------------------------------------------------------------------------

#[test]
fn backup_to_local_bare_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    let diff = store.backup(&remote_url, false).unwrap();

    assert!(!diff.in_sync());
    assert!(!diff.add.is_empty());

    // Verify remote has the refs
    let remote = GitStore::open(
        &remote_url,
        OpenOptions {
            create: false,
            ..Default::default()
        },
    )
    .unwrap();
    let branches = remote.branches().list().unwrap();
    assert!(branches.contains(&"main".to_string()));
    assert_eq!(
        remote
            .branches()
            .get("main")
            .unwrap()
            .read_text("a.txt")
            .unwrap(),
        "hello"
    );
}

// ---------------------------------------------------------------------------
// restore
// ---------------------------------------------------------------------------

#[test]
fn restore_from_local_bare_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Create a new empty store and restore into it
    let store2 = GitStore::open(
        dir.path().join("restored.git"),
        OpenOptions {
            create: true,
            branch: None,
            ..Default::default()
        },
    )
    .unwrap();

    let diff = store2.restore(&remote_url, false).unwrap();
    assert!(!diff.in_sync());
    assert!(!diff.add.is_empty());

    let branches = store2.branches().list().unwrap();
    assert!(branches.contains(&"main".to_string()));
    assert_eq!(
        store2
            .branches()
            .get("main")
            .unwrap()
            .read_text("a.txt")
            .unwrap(),
        "hello"
    );
}

// ---------------------------------------------------------------------------
// dry-run
// ---------------------------------------------------------------------------

#[test]
fn dry_run_backup_makes_no_changes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    // First do a real backup so remote exists
    store.backup(&remote_url, false).unwrap();

    // Write more data
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("b.txt", b"world", WriteOptions::default()).unwrap();

    // Dry-run should report changes but not push
    let diff = store.backup(&remote_url, true).unwrap();
    assert!(!diff.in_sync());

    // Remote should still only have the old data
    let remote = GitStore::open(
        &remote_url,
        OpenOptions {
            create: false,
            ..Default::default()
        },
    )
    .unwrap();
    assert!(!remote
        .branches()
        .get("main")
        .unwrap()
        .exists("b.txt")
        .unwrap());
}

#[test]
fn dry_run_restore_makes_no_changes() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Create empty store
    let store2 = GitStore::open(
        dir.path().join("restored.git"),
        OpenOptions {
            create: true,
            branch: None,
            ..Default::default()
        },
    )
    .unwrap();

    let diff = store2.restore(&remote_url, true).unwrap();
    assert!(!diff.in_sync());

    // Store2 should still be empty
    assert!(store2.branches().list().unwrap().is_empty());
}

// ---------------------------------------------------------------------------
// stale ref deletion
// ---------------------------------------------------------------------------

#[test]
fn backup_deletes_stale_remote_refs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    // Create a second branch
    store.branches().set("extra", &fs).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Verify remote has both branches
    {
        let remote = GitStore::open(
            &remote_url,
            OpenOptions {
                create: false,
                ..Default::default()
            },
        )
        .unwrap();
        assert!(remote.branches().list().unwrap().contains(&"extra".to_string()));
    }

    // Delete the extra branch locally
    store.branches().delete("extra").unwrap();

    // Backup again — should delete the remote extra branch
    let diff = store.backup(&remote_url, false).unwrap();
    assert!(diff.delete.iter().any(|r| r.ref_name.contains("extra")));

    // Verify remote no longer has the extra branch
    let remote = GitStore::open(
        &remote_url,
        OpenOptions {
            create: false,
            ..Default::default()
        },
    )
    .unwrap();
    assert!(!remote
        .branches()
        .list()
        .unwrap()
        .contains(&"extra".to_string()));
}

#[test]
fn restore_deletes_stale_local_refs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Create a local-only branch
    store.branches().set("local-only", &fs).unwrap();
    assert!(store
        .branches()
        .list()
        .unwrap()
        .contains(&"local-only".to_string()));

    // Restore from remote — should delete local-only branch
    let diff = store.restore(&remote_url, false).unwrap();
    assert!(diff
        .delete
        .iter()
        .any(|r| r.ref_name.contains("local-only")));
    assert!(!store
        .branches()
        .list()
        .unwrap()
        .contains(&"local-only".to_string()));
}

// ---------------------------------------------------------------------------
// round-trip
// ---------------------------------------------------------------------------

#[test]
fn round_trip_backup_then_restore() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"aaa", WriteOptions::default()).unwrap();
    let fs = fs.write("b.txt", b"bbb", WriteOptions::default()).unwrap();

    store.branches().set("feature", &fs).unwrap();
    let feat = store.branches().get("feature").unwrap();
    let _feat = feat
        .write("c.txt", b"ccc", WriteOptions::default())
        .unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Create new store and restore
    let store2 = GitStore::open(
        dir.path().join("restored.git"),
        OpenOptions {
            create: true,
            branch: None,
            ..Default::default()
        },
    )
    .unwrap();
    store2.restore(&remote_url, false).unwrap();

    assert_eq!(
        store2
            .branches()
            .get("main")
            .unwrap()
            .read_text("a.txt")
            .unwrap(),
        "aaa"
    );
    assert_eq!(
        store2
            .branches()
            .get("main")
            .unwrap()
            .read_text("b.txt")
            .unwrap(),
        "bbb"
    );
    let branches = store2.branches().list().unwrap();
    assert!(branches.contains(&"feature".to_string()));
    assert_eq!(
        store2
            .branches()
            .get("feature")
            .unwrap()
            .read_text("c.txt")
            .unwrap(),
        "ccc"
    );
}

// ---------------------------------------------------------------------------
// already in sync
// ---------------------------------------------------------------------------

#[test]
fn backup_when_already_in_sync() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    // Second backup should be in sync
    let diff = store.backup(&remote_url, false).unwrap();
    assert!(diff.in_sync());
    assert_eq!(diff.total(), 0);
}

// ---------------------------------------------------------------------------
// tags
// ---------------------------------------------------------------------------

#[test]
fn backup_with_tags() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"hello", WriteOptions::default()).unwrap();
    store.tags().set("v1.0", &fs).unwrap();

    let remote_url = create_remote_path(dir.path());
    store.backup(&remote_url, false).unwrap();

    let remote = GitStore::open(
        &remote_url,
        OpenOptions {
            create: false,
            ..Default::default()
        },
    )
    .unwrap();
    let tags = remote.tags().list().unwrap();
    assert!(tags.contains(&"v1.0".to_string()));
    assert_eq!(
        remote
            .tags()
            .get("v1.0")
            .unwrap()
            .read_text("a.txt")
            .unwrap(),
        "hello"
    );
}
