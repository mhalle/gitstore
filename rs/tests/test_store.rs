mod common;

use vost::*;

// ---------------------------------------------------------------------------
// Open / create
// ---------------------------------------------------------------------------

#[test]
fn create_with_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
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
    // No branch created — HEAD points to a ref that doesn't exist,
    // so get() on the default branch name should fail
    let default_name = store.branches().get_current_name().unwrap();
    if let Some(name) = default_name {
        assert!(store.branches().get(&name).is_err());
    }
    // Either way, no branch is accessible
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
    let fs = store2.branches().get("main").unwrap();
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
    assert_eq!(store.signature().name, "vost");
    assert_eq!(store.signature().email, "vost@localhost");
}

// ---------------------------------------------------------------------------
// RefDict — branches
// ---------------------------------------------------------------------------

#[test]
fn branches_get() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let sha = fs.commit_hash().unwrap();
    assert_eq!(sha.len(), 40);
}

#[test]
fn branches_get_missing() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    assert!(store.branches().get("nope").is_err());
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
    let main_fs = store.branches().get("main").unwrap();
    let sha = main_fs.commit_hash().unwrap();

    // Fork: create "dev" pointing at same commit
    store.branches().set("dev", &main_fs).unwrap();
    assert!(store.branches().has("dev").unwrap());
    assert_eq!(store.branches().get("dev").unwrap().commit_hash().unwrap(), sha);
}

#[test]
fn branches_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("tmp", &main_fs).unwrap();

    store.branches().delete("tmp").unwrap();
    assert!(!store.branches().has("tmp").unwrap());
}

#[test]
fn branches_iter() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("dev", &main_fs).unwrap();

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
    let main_fs = store.branches().get("main").unwrap();
    let sha = main_fs.commit_hash().unwrap();

    store.tags().set("v1", &main_fs).unwrap();
    assert_eq!(store.tags().get("v1").unwrap().commit_hash().unwrap(), sha);
}

#[test]
fn tags_list() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.tags().set("v1", &main_fs).unwrap();
    store.tags().set("v2", &main_fs).unwrap();

    let tags = store.tags().list().unwrap();
    assert_eq!(tags, vec!["v1", "v2"]);
}

#[test]
fn tags_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.tags().set("v1", &main_fs).unwrap();

    store.tags().delete("v1").unwrap();
    assert!(!store.tags().has("v1").unwrap());
}

// ---------------------------------------------------------------------------
// RefDict — default
// ---------------------------------------------------------------------------

#[test]
fn get_current_name() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let default = store.branches().get_current_name().unwrap();
    assert_eq!(default, Some("main".to_string()));
}

#[test]
fn set_current() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("dev", &main_fs).unwrap();

    store.branches().set_current("dev").unwrap();
    assert_eq!(
        store.branches().get_current_name().unwrap(),
        Some("dev".to_string())
    );
}

#[test]
fn custom_initial_branch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "develop");
    assert_eq!(
        store.branches().get_current_name().unwrap(),
        Some("develop".to_string())
    );
    assert!(store.branches().has("develop").unwrap());
}

#[test]
fn fs_default_branch_via_get() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let name = store.branches().get_current_name().unwrap().unwrap();
    let fs = store.branches().get(&name).unwrap();
    assert!(fs.commit_hash().is_some());
}

#[test]
fn set_current_to_nonexistent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    // set_current to a ref that doesn't exist — this sets HEAD symbolic but
    // get() will fail because the ref doesn't exist
    store.branches().set_current("nope").unwrap();
    let name = store.branches().get_current_name().unwrap().unwrap();
    assert!(store.branches().get(&name).is_err());
}

// ---------------------------------------------------------------------------
// RefDict — set_and_get
// ---------------------------------------------------------------------------

#[test]
fn branches_set_and_get_returns_old() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    let sha = main_fs.commit_hash().unwrap();
    store.branches().set("dev", &main_fs).unwrap();

    // Advance dev
    let fs = store.branches().get("dev").unwrap();
    fs.write("new.txt", b"data", Default::default()).unwrap();
    let new_sha = store.branches().get("dev").unwrap().commit_hash().unwrap();

    // set_and_get returns old value
    let old = store.branches().set_and_get("dev", &main_fs).unwrap();
    assert_eq!(old.unwrap().commit_hash().unwrap(), new_sha);
    // Now dev points back to original
    assert_eq!(store.branches().get("dev").unwrap().commit_hash().unwrap(), sha);
}

#[test]
fn branches_set_and_get_new_ref() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    let sha = main_fs.commit_hash().unwrap();

    let old = store.branches().set_and_get("brand_new", &main_fs).unwrap();
    assert!(old.is_none());
    assert_eq!(store.branches().get("brand_new").unwrap().commit_hash().unwrap(), sha);
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
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("zebra", &main_fs).unwrap();
    store.branches().set("alpha", &main_fs).unwrap();
    store.branches().set("beta", &main_fs).unwrap();

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
    let main_fs = store.branches().get("main").unwrap();
    let sha = main_fs.commit_hash().unwrap();
    store.tags().set("v1", &main_fs).unwrap();
    store.tags().set("v2", &main_fs).unwrap();

    let pairs = store.tags().iter().unwrap();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0].0, "v1");
    assert_eq!(pairs[1].0, "v2");
    assert_eq!(pairs[0].1.commit_hash().unwrap(), sha);
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
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("tmp", &main_fs).unwrap();
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
    let fs = store1.branches().get("main").unwrap();
    fs.write("shared.txt", b"data", Default::default()).unwrap();

    // Read via store2
    let fs2 = store2.branches().get("main").unwrap();
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
fn tags_set_overwrite_rejected() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs1 = store.branches().get("main").unwrap();
    store.tags().set("v1", &fs1).unwrap();

    // Advance branch to get a new SHA
    let fs = store.branches().get("main").unwrap();
    fs.write("new.txt", b"data", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();

    // Overwriting an existing tag should be rejected
    let result = store.tags().set("v1", &fs2);
    assert!(result.is_err());
    // Original tag should be unchanged
    assert_eq!(store.tags().get("v1").unwrap().commit_hash().unwrap(), fs1.commit_hash().unwrap());
}

// ---------------------------------------------------------------------------
// RefDict::set — validations (Fix 4)
// ---------------------------------------------------------------------------

#[test]
fn branches_set_rejects_invalid_ref_name() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    // Invalid ref names should be rejected
    let result = store.branches().set("bad..name", &fs);
    assert!(result.is_err());

    let result = store.branches().set("bad/./name", &fs);
    assert!(result.is_err());

    let result = store.branches().set(".hidden", &fs);
    assert!(result.is_err());
}

#[test]
fn branches_set_rejects_cross_repo_fs() {
    let dir1 = tempfile::tempdir().unwrap();
    let dir2 = tempfile::tempdir().unwrap();
    let store1 = common::create_store(dir1.path(), "main");
    let store2 = common::create_store(dir2.path(), "main");

    let fs2 = store2.branches().get("main").unwrap();

    // Setting a branch with an Fs from a different repo should fail
    let result = store1.branches().set("cross", &fs2);
    assert!(result.is_err());
}

#[test]
fn tags_set_rejects_cross_repo_fs() {
    let dir1 = tempfile::tempdir().unwrap();
    let dir2 = tempfile::tempdir().unwrap();
    let store1 = common::create_store(dir1.path(), "main");
    let store2 = common::create_store(dir2.path(), "main");

    let fs2 = store2.branches().get("main").unwrap();

    let result = store1.tags().set("v1", &fs2);
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// Tags — branch-only operations rejected (Fix 6)
// ---------------------------------------------------------------------------

#[test]
fn tags_set_current_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    store.tags().set("v1", &fs).unwrap();

    let result = store.tags().set_current("v1");
    assert!(result.is_err());
}

#[test]
fn tags_get_current_name_returns_none() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let result = store.tags().get_current_name().unwrap();
    assert!(result.is_none());
}

#[test]
fn tags_get_current_returns_none() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let result = store.tags().get_current().unwrap();
    assert!(result.is_none());
}

#[test]
fn tags_reflog_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    store.tags().set("v1", &fs).unwrap();

    let result = store.tags().reflog("v1");
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// RefDict::set — reflog entry written (Fix 4)
// ---------------------------------------------------------------------------

#[test]
fn branches_set_writes_reflog() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();

    store.branches().set("dev", &fs).unwrap();

    // The reflog for "dev" should have at least one entry
    let entries = store.branches().reflog("dev").unwrap();
    assert!(!entries.is_empty());
}

// ---------------------------------------------------------------------------
// fs on detached — write should error
// ---------------------------------------------------------------------------

#[test]
fn fs_on_back_is_readonly() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    // back(1) gives a detached (readonly) Fs
    let detached = fs.back(1).unwrap();
    let result = detached.write("should_fail.txt", b"fail", Default::default());
    assert!(result.is_err());
}

#[test]
fn fs_on_back_batch_is_readonly() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    // back(1) gives a detached (readonly) Fs — batch commit should error
    let detached = fs.back(1).unwrap();
    let mut batch = detached.batch(Default::default());
    batch.write("x.txt", b"x").unwrap();
    let result = batch.commit();
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// store.fs(hash) — open by commit hash
// ---------------------------------------------------------------------------

#[test]
fn fs_by_hash_readonly() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"hello", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let sha = fs.commit_hash().unwrap();

    // Open by hash — should be readable
    let detached = store.fs(&sha).unwrap();
    assert_eq!(detached.read_text("a.txt").unwrap(), "hello");

    // Should be readonly (no branch)
    let result = detached.write("b.txt", b"fail", Default::default());
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// Multiple branches with different content
// ---------------------------------------------------------------------------

#[test]
fn branches_independent_content() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    store.branches().set("dev", &main_fs).unwrap();

    // Write different content to each
    let fs = store.branches().get("main").unwrap();
    fs.write("main_only.txt", b"main", Default::default()).unwrap();

    let fs = store.branches().get("dev").unwrap();
    fs.write("dev_only.txt", b"dev", Default::default()).unwrap();

    // Verify isolation
    let main_fs = store.branches().get("main").unwrap();
    let dev_fs = store.branches().get("dev").unwrap();
    assert!(main_fs.exists("main_only.txt").unwrap());
    assert!(!main_fs.exists("dev_only.txt").unwrap());
    assert!(!dev_fs.exists("main_only.txt").unwrap());
    assert!(dev_fs.exists("dev_only.txt").unwrap());
}

// ---------------------------------------------------------------------------
// set_to — returns writable Fs
// ---------------------------------------------------------------------------

#[test]
fn branches_set_to_returns_writable_fs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    main_fs.write("a.txt", b"hello", Default::default()).unwrap();
    let main_fs = store.branches().get("main").unwrap();

    // Create a new branch using set_to
    let new_fs = store.branches().set_to("dev", &main_fs).unwrap();

    // The returned Fs should be writable (has branch "dev")
    assert_eq!(new_fs.ref_name(), Some("dev"));
    assert_eq!(new_fs.read_text("a.txt").unwrap(), "hello");

    // Should be writable
    new_fs.write("b.txt", b"world", Default::default()).unwrap();
    let dev_fs = store.branches().get("dev").unwrap();
    assert_eq!(dev_fs.read_text("b.txt").unwrap(), "world");
}

#[test]
fn branches_set_to_updates_existing() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let main_fs = store.branches().get("main").unwrap();
    main_fs.write("a.txt", b"a", Default::default()).unwrap();
    let main_fs = store.branches().get("main").unwrap();

    // Create dev branch
    store.branches().set("dev", &main_fs).unwrap();

    // Write to main
    main_fs.write("b.txt", b"b", Default::default()).unwrap();
    let main_fs = store.branches().get("main").unwrap();

    // Update dev to match main
    let dev_fs = store.branches().set_to("dev", &main_fs).unwrap();
    assert!(dev_fs.exists("b.txt").unwrap());
}
