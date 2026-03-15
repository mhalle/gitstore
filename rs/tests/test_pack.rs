mod common;

use vost::*;

#[test]
fn pack_returns_count() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"aaa", Default::default()).unwrap();
    let _fs = fs.write("b.txt", b"bbb", Default::default()).unwrap();
    let count = store.pack().unwrap();
    assert!(count > 0, "expected packed objects, got {count}");
}

#[test]
fn pack_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"aaa", Default::default()).unwrap();
    store.pack().unwrap();
    let count = store.pack().unwrap();
    assert_eq!(count, 0, "second pack should return 0");
}

#[test]
fn pack_preserves_data() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs.write("a.txt", b"hello", Default::default()).unwrap();
    let _fs = fs.write("b.txt", b"world", Default::default()).unwrap();
    store.pack().unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("a.txt").unwrap(), b"hello");
    assert_eq!(fs.read("b.txt").unwrap(), b"world");
}

#[test]
fn pack_empty_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = GitStore::open(dir.path().join("test.git"), OpenOptions {
        create: true,
        branch: None,
        ..Default::default()
    }).unwrap();
    let count = store.pack().unwrap();
    assert_eq!(count, 0);
}

#[test]
fn gc_returns_count() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"aaa", Default::default()).unwrap();
    let count = store.gc().unwrap();
    assert!(count > 0);
}

#[test]
fn gc_preserves_data() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let _fs = fs.write("a.txt", b"hello", Default::default()).unwrap();
    store.gc().unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read("a.txt").unwrap(), b"hello");
}
