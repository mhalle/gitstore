mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// parent
// ---------------------------------------------------------------------------

#[test]
fn parent_root_is_none() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    // Initial commit has no parent
    assert!(fs.parent().unwrap().is_none());
}

#[test]
fn parent_chain() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    // Current -> parent -> grandparent (init)
    let parent = fs.parent().unwrap().unwrap();
    assert!(parent.exists("a.txt").unwrap());
    assert!(!parent.exists("b.txt").unwrap());

    let grandparent = parent.parent().unwrap().unwrap();
    assert!(!grandparent.exists("a.txt").unwrap());

    // Grandparent is root
    assert!(grandparent.parent().unwrap().is_none());
}

// ---------------------------------------------------------------------------
// back
// ---------------------------------------------------------------------------

#[test]
fn back_zero_is_self() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let fs0 = fs.back(0).unwrap();
    assert_eq!(fs0.commit_hash(), fs.commit_hash());
}

#[test]
fn back_one() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let h0 = fs.commit_hash().unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let prev = fs.back(1).unwrap();
    assert_eq!(prev.commit_hash().unwrap(), h0);
}

#[test]
fn back_n() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let h0 = fs.commit_hash().unwrap();

    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let back2 = fs.back(2).unwrap();
    assert_eq!(back2.commit_hash().unwrap(), h0);
}

#[test]
fn back_too_far_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    // Only 1 commit, going back 2 should fail
    assert!(fs.back(2).is_err());
}

// ---------------------------------------------------------------------------
// log
// ---------------------------------------------------------------------------

#[test]
fn log_length() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(Default::default()).unwrap();
    // init + 2 writes = 3
    assert_eq!(log.len(), 3);
}

#[test]
fn log_order_recent_first() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", fs::WriteOptions {
        message: Some("write a".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", fs::WriteOptions {
        message: Some("write b".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(Default::default()).unwrap();
    assert_eq!(log[0].message, "write b");
    assert_eq!(log[1].message, "write a");
}

#[test]
fn log_metadata_fields() {
    let dir = tempfile::tempdir().unwrap();
    let store = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: true,
        branch: Some("main".into()),
        author: Some("Alice".into()),
        email: Some("alice@example.com".into()),
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(Default::default()).unwrap();
    assert_eq!(log.len(), 1);
    assert_eq!(log[0].author_name.as_deref(), Some("Alice"));
    assert_eq!(log[0].author_email.as_deref(), Some("alice@example.com"));
    assert!(log[0].time.is_some());
    assert!(log[0].time.unwrap() > 0);
}

#[test]
fn log_limit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(fs::LogOptions {
        limit: Some(2),
        skip: None,
    })
    .unwrap();
    assert_eq!(log.len(), 2);
}

#[test]
fn log_skip() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", fs::WriteOptions {
        message: Some("write a".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", fs::WriteOptions {
        message: Some("write b".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(fs::LogOptions {
        limit: None,
        skip: Some(1),
    })
    .unwrap();
    // Skipped most recent, so first entry should be "write a"
    assert_eq!(log[0].message, "write a");
}

#[test]
fn log_skip_and_limit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("b.txt", b"b", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("c.txt", b"c", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(fs::LogOptions {
        limit: Some(1),
        skip: Some(1),
    })
    .unwrap();
    assert_eq!(log.len(), 1);
}

// ---------------------------------------------------------------------------
// undo
// ---------------------------------------------------------------------------

#[test]
fn undo_single_step() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let hash_before_undo = fs.commit_hash().unwrap();

    let undone = fs.undo().unwrap();
    assert_ne!(undone.commit_hash().unwrap(), hash_before_undo);
    assert!(!undone.exists("a.txt").unwrap());
}

#[test]
fn undo_updates_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let undone = fs.undo().unwrap();
    // Re-fetch from store — branch should have moved back
    let fs_fresh = store.fs(Some("main")).unwrap();
    assert_eq!(fs_fresh.commit_hash(), undone.commit_hash());
}

#[test]
fn undo_no_parent_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    // Only init commit, no parent to undo to
    assert!(fs.undo().is_err());
}

// ---------------------------------------------------------------------------
// redo
// ---------------------------------------------------------------------------

#[test]
fn redo_after_undo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let hash_with_a = fs.commit_hash().unwrap();

    let undone = fs.undo().unwrap();
    assert!(!undone.exists("a.txt").unwrap());

    let redone = undone.redo().unwrap();
    assert_eq!(redone.commit_hash().unwrap(), hash_with_a);
    assert!(redone.exists("a.txt").unwrap());
}

#[test]
fn redo_updates_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let undone = fs.undo().unwrap();
    let redone = undone.redo().unwrap();

    let fs_fresh = store.fs(Some("main")).unwrap();
    assert_eq!(fs_fresh.commit_hash(), redone.commit_hash());
}

// ---------------------------------------------------------------------------
// undo + redo sequence
// ---------------------------------------------------------------------------

#[test]
fn undo_redo_undo_sequence() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let hash_init = fs.commit_hash().unwrap();

    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let hash_with_a = fs.commit_hash().unwrap();

    // undo -> init
    let undone = fs.undo().unwrap();
    assert_eq!(undone.commit_hash().unwrap(), hash_init);

    // redo -> with_a
    let redone = undone.redo().unwrap();
    assert_eq!(redone.commit_hash().unwrap(), hash_with_a);

    // undo again -> init
    let undone2 = redone.undo().unwrap();
    assert_eq!(undone2.commit_hash().unwrap(), hash_init);
}

// ---------------------------------------------------------------------------
// reflog
// ---------------------------------------------------------------------------

#[test]
fn reflog_has_entries() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();

    let entries = store.branches().reflog("main").unwrap();
    assert!(!entries.is_empty());
}

#[test]
fn reflog_includes_undo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.undo().unwrap();

    let entries = store.branches().reflog("main").unwrap();
    let has_undo = entries.iter().any(|e| e.message.contains("undo"));
    assert!(has_undo);
}

// ---------------------------------------------------------------------------
// commit info
// ---------------------------------------------------------------------------

#[test]
fn commit_info_author() {
    let dir = tempfile::tempdir().unwrap();
    let store = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: true,
        branch: Some("main".into()),
        author: Some("Bob".into()),
        email: Some("bob@example.com".into()),
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(fs::LogOptions { limit: Some(1), skip: None }).unwrap();
    assert_eq!(log[0].author_name.as_deref(), Some("Bob"));
    assert_eq!(log[0].author_email.as_deref(), Some("bob@example.com"));
}

#[test]
fn commit_info_time_populated() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();

    let log = fs.log(Default::default()).unwrap();
    assert!(log[0].time.is_some());
    assert!(log[0].time.unwrap() > 0);
}
