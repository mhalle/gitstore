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
