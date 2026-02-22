mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// Open / create
// ---------------------------------------------------------------------------

#[test]
fn create_with_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    assert!(fs.commit_hash().is_some());
}

#[test]
fn create_no_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: true,
        branch: None,
        ..Default::default()
    })
    .unwrap();
    // No branch created, so fs(None) should fail
    assert!(store.fs(None).is_err());
}

#[test]
fn open_existing() {
    let dir = tempfile::tempdir().unwrap();
    let _store = common::create_store(dir.path(), "main");

    // Reopen without create
    let store2 = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: false,
        ..Default::default()
    })
    .unwrap();
    let fs = store2.fs(Some("main")).unwrap();
    assert!(fs.commit_hash().is_some());
}

#[test]
fn open_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let result = GitStore::open(dir.path().join("nope.git"), OpenOptions {
        create: false,
        ..Default::default()
    });
    assert!(result.is_err());
}

#[test]
fn custom_author_email() {
    let dir = tempfile::tempdir().unwrap();
    let store = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: true,
        branch: Some("main".into()),
        author: Some("Alice".into()),
        email: Some("alice@example.com".into()),
    })
    .unwrap();
    assert_eq!(store.signature().name, "Alice");
    assert_eq!(store.signature().email, "alice@example.com");
}

#[test]
fn path_accessor() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert_eq!(store.path(), dir.path().join("test.git"));
}

#[test]
fn signature_accessor() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert_eq!(store.signature().name, "gitstore");
    assert_eq!(store.signature().email, "gitstore@localhost");
}

// ---------------------------------------------------------------------------
// RefDict — branches
// ---------------------------------------------------------------------------

#[test]
fn branches_get() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap();
    assert!(sha.is_some());
    assert_eq!(sha.unwrap().len(), 40);
}

#[test]
fn branches_get_missing() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert!(store.branches().get("nope").unwrap().is_none());
}

#[test]
fn branches_has() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert!(store.branches().has("main").unwrap());
    assert!(!store.branches().has("nope").unwrap());
}

#[test]
fn branches_list() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let branches = store.branches().list().unwrap();
    assert_eq!(branches, vec!["main"]);
}

#[test]
fn branches_set_fork() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();

    // Fork: create "dev" pointing at same commit
    store.branches().set("dev", &sha).unwrap();
    assert!(store.branches().has("dev").unwrap());
    assert_eq!(store.branches().get("dev").unwrap().unwrap(), sha);
}

#[test]
fn branches_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("tmp", &sha).unwrap();

    store.branches().delete("tmp").unwrap();
    assert!(!store.branches().has("tmp").unwrap());
}

#[test]
fn branches_iter() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("dev", &sha).unwrap();

    let pairs = store.branches().iter().unwrap();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0].0, "dev");
    assert_eq!(pairs[1].0, "main");
}

// ---------------------------------------------------------------------------
// RefDict — tags
// ---------------------------------------------------------------------------

#[test]
fn tags_set_get() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();

    store.tags().set("v1", &sha).unwrap();
    assert_eq!(store.tags().get("v1").unwrap().unwrap(), sha);
}

#[test]
fn tags_list() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.tags().set("v1", &sha).unwrap();
    store.tags().set("v2", &sha).unwrap();

    let tags = store.tags().list().unwrap();
    assert_eq!(tags, vec!["v1", "v2"]);
}

#[test]
fn tags_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.tags().set("v1", &sha).unwrap();

    store.tags().delete("v1").unwrap();
    assert!(!store.tags().has("v1").unwrap());
}

// ---------------------------------------------------------------------------
// RefDict — default
// ---------------------------------------------------------------------------

#[test]
fn get_default() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let default = store.branches().get_default().unwrap();
    assert_eq!(default, Some("main".to_string()));
}

#[test]
fn set_default() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("dev", &sha).unwrap();

    store.branches().set_default("dev").unwrap();
    assert_eq!(
        store.branches().get_default().unwrap(),
        Some("dev".to_string())
    );
}

#[test]
fn custom_initial_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "develop");
    assert_eq!(
        store.branches().get_default().unwrap(),
        Some("develop".to_string())
    );
    assert!(store.branches().has("develop").unwrap());
}

#[test]
fn fs_none_uses_default() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(None).unwrap();
    assert!(fs.commit_hash().is_some());
}

#[test]
fn set_default_to_nonexistent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    // set_default to a ref that doesn't exist — this sets HEAD symbolic but
    // fs resolution will fail
    store.branches().set_default("nope").unwrap();
    assert!(store.fs(None).is_err());
}

// ---------------------------------------------------------------------------
// RefDict — set_and_get
// ---------------------------------------------------------------------------

#[test]
fn branches_set_and_get_returns_old() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("dev", &sha).unwrap();

    // Advance dev
    let fs = store.fs(Some("dev")).unwrap();
    fs.write("new.txt", b"data", Default::default()).unwrap();
    let new_sha = store.branches().get("dev").unwrap().unwrap();

    // set_and_get returns old value
    let old = store.branches().set_and_get("dev", &sha).unwrap();
    assert_eq!(old, Some(new_sha));
    // Now dev points back to original
    assert_eq!(store.branches().get("dev").unwrap().unwrap(), sha);
}

#[test]
fn branches_set_and_get_new_ref() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();

    let old = store.branches().set_and_get("brand_new", &sha).unwrap();
    assert!(old.is_none());
    assert_eq!(store.branches().get("brand_new").unwrap().unwrap(), sha);
}

// ---------------------------------------------------------------------------
// RefDict — branches iteration
// ---------------------------------------------------------------------------

#[test]
fn branches_iter_empty_after_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    store.branches().delete("main").unwrap();
    let list = store.branches().list().unwrap();
    assert!(list.is_empty());
}

#[test]
fn branches_list_sorted() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("zebra", &sha).unwrap();
    store.branches().set("alpha", &sha).unwrap();
    store.branches().set("beta", &sha).unwrap();

    let list = store.branches().list().unwrap();
    assert_eq!(list, vec!["alpha", "beta", "main", "zebra"]);
}

// ---------------------------------------------------------------------------
// RefDict — tags iteration
// ---------------------------------------------------------------------------

#[test]
fn tags_iter_pairs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.tags().set("v1", &sha).unwrap();
    store.tags().set("v2", &sha).unwrap();

    let pairs = store.tags().iter().unwrap();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0].0, "v1");
    assert_eq!(pairs[1].0, "v2");
    assert_eq!(pairs[0].1, sha);
}

#[test]
fn tags_empty_list() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert!(store.tags().list().unwrap().is_empty());
}

// ---------------------------------------------------------------------------
// RefDict — branches has after operations
// ---------------------------------------------------------------------------

#[test]
fn branches_has_after_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("tmp", &sha).unwrap();
    assert!(store.branches().has("tmp").unwrap());
    store.branches().delete("tmp").unwrap();
    assert!(!store.branches().has("tmp").unwrap());
}

// ---------------------------------------------------------------------------
// Store clone
// ---------------------------------------------------------------------------

#[test]
fn store_clone_shares_state() {
    let dir = tempfile::tempdir().unwrap();
    let store1 = common::create_store(dir.path(), "main");
    let store2 = store1.clone();

    // Write via store1
    let fs = store1.fs(Some("main")).unwrap();
    fs.write("shared.txt", b"data", Default::default()).unwrap();

    // Read via store2
    let fs2 = store2.fs(Some("main")).unwrap();
    assert_eq!(fs2.read_text("shared.txt").unwrap(), "data");
}

// ---------------------------------------------------------------------------
// Multiple branches with different content
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// branches — delete nonexistent
// ---------------------------------------------------------------------------

#[test]
fn branches_delete_nonexistent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    // Deleting a branch that doesn't exist should not panic
    let result = store.branches().delete("nonexistent");
    // May succeed silently or error — either way, no panic
    let _ = result;
}

// ---------------------------------------------------------------------------
// tags — overwrite
// ---------------------------------------------------------------------------

#[test]
fn tags_set_overwrite() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha1 = store.branches().get("main").unwrap().unwrap();
    store.tags().set("v1", &sha1).unwrap();

    // Advance branch to get a new SHA
    let fs = store.fs(Some("main")).unwrap();
    fs.write("new.txt", b"data", Default::default()).unwrap();
    let sha2 = store.branches().get("main").unwrap().unwrap();
    assert_ne!(sha1, sha2);

    // Overwrite tag to point at new SHA
    store.tags().set("v1", &sha2).unwrap();
    assert_eq!(store.tags().get("v1").unwrap().unwrap(), sha2);
}

// ---------------------------------------------------------------------------
// fs on detached — write should error
// ---------------------------------------------------------------------------

#[test]
fn fs_on_back_is_readonly() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    // back(1) gives a detached (readonly) Fs
    let detached = fs.back(1).unwrap();
    let result = detached.write("should_fail.txt", b"fail", Default::default());
    assert!(result.is_err());
}

#[test]
fn fs_on_back_batch_is_readonly() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();

    // back(1) gives a detached (readonly) Fs — batch commit should error
    let detached = fs.back(1).unwrap();
    let mut batch = detached.batch(Default::default());
    batch.write("x.txt", b"x").unwrap();
    let result = batch.commit();
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// branches — invalid SHA errors
// ---------------------------------------------------------------------------

#[test]
fn branches_set_invalid_sha_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let result = store.branches().set("bad", "not_a_valid_hex_sha");
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// Multiple branches with different content
// ---------------------------------------------------------------------------

#[test]
fn branches_independent_content() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let sha = store.branches().get("main").unwrap().unwrap();
    store.branches().set("dev", &sha).unwrap();

    // Write different content to each
    let fs = store.fs(Some("main")).unwrap();
    fs.write("main_only.txt", b"main", Default::default()).unwrap();

    let fs = store.fs(Some("dev")).unwrap();
    fs.write("dev_only.txt", b"dev", Default::default()).unwrap();

    // Verify isolation
    let main_fs = store.fs(Some("main")).unwrap();
    let dev_fs = store.fs(Some("dev")).unwrap();
    assert!(main_fs.exists("main_only.txt").unwrap());
    assert!(!main_fs.exists("dev_only.txt").unwrap());
    assert!(!dev_fs.exists("main_only.txt").unwrap());
    assert!(dev_fs.exists("dev_only.txt").unwrap());
}
