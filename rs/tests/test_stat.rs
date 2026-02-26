mod common;

use vost::*;

// ---------------------------------------------------------------------------
// stat — files
// ---------------------------------------------------------------------------

#[test]
fn stat_file() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st = fs.stat("hello.txt").unwrap();
    assert_eq!(st.mode, MODE_BLOB);
    assert_eq!(st.file_type, FileType::Blob);
    assert_eq!(st.size, 5);
    assert_eq!(st.nlink, 1);
    assert_eq!(st.hash.len(), 40);
    assert!(st.hash.chars().all(|c| c.is_ascii_hexdigit()));
}

#[cfg(unix)]
#[test]
fn stat_executable() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("run.sh", b"#!/bin/sh", fs::WriteOptions {
        mode: Some(MODE_BLOB_EXEC),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let st = fs.stat("run.sh").unwrap();
    assert_eq!(st.mode, MODE_BLOB_EXEC);
    assert_eq!(st.file_type, FileType::Executable);
    assert_eq!(st.nlink, 1);
}

#[cfg(unix)]
#[test]
fn stat_symlink() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write_symlink("link", "target.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let st = fs.stat("link").unwrap();
    assert_eq!(st.mode, MODE_LINK);
    assert_eq!(st.file_type, FileType::Link);
    assert_eq!(st.nlink, 1);
}

// ---------------------------------------------------------------------------
// stat — directories
// ---------------------------------------------------------------------------

#[test]
fn stat_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st = fs.stat("dir").unwrap();
    assert_eq!(st.mode, MODE_TREE);
    assert_eq!(st.file_type, FileType::Tree);
    assert_eq!(st.size, 0);
    // dir has no subdirs, so nlink = 2
    assert_eq!(st.nlink, 2);
}

#[test]
fn stat_root() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st = fs.stat("").unwrap();
    assert_eq!(st.mode, MODE_TREE);
    assert_eq!(st.file_type, FileType::Tree);
    assert_eq!(st.size, 0);
    // root has one subdir ("dir"), so nlink = 2 + 1 = 3
    assert_eq!(st.nlink, 3);
}

// ---------------------------------------------------------------------------
// stat — nlink with multiple subdirs
// ---------------------------------------------------------------------------

#[test]
fn stat_nlink_counts_subdirs() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("a/x.txt", b"x").unwrap();
    batch.write("b/y.txt", b"y").unwrap();
    batch.write("c/z.txt", b"z").unwrap();
    batch.write("file.txt", b"f").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();

    // root has 3 subdirs (a, b, c) → nlink = 2 + 3 = 5
    let st = fs.stat("").unwrap();
    assert_eq!(st.nlink, 5);
}

// ---------------------------------------------------------------------------
// stat — consistency with size() and object_hash()
// ---------------------------------------------------------------------------

#[test]
fn stat_size_matches_size_method() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st = fs.stat("hello.txt").unwrap();
    assert_eq!(st.size, fs.size("hello.txt").unwrap());
}

#[test]
fn stat_hash_matches_object_hash() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st = fs.stat("hello.txt").unwrap();
    assert_eq!(st.hash, fs.object_hash("hello.txt").unwrap());
}

// ---------------------------------------------------------------------------
// stat — mtime
// ---------------------------------------------------------------------------

#[test]
fn stat_mtime_consistent() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let st1 = fs.stat("hello.txt").unwrap();
    let st2 = fs.stat("dir/a.txt").unwrap();
    // Same commit → same mtime
    assert_eq!(st1.mtime, st2.mtime);
    assert!(st1.mtime > 0);
}

// ---------------------------------------------------------------------------
// stat — nonexistent
// ---------------------------------------------------------------------------

#[test]
fn stat_nonexistent_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.stat("nope.txt").is_err());
}

// ---------------------------------------------------------------------------
// listdir
// ---------------------------------------------------------------------------

#[test]
fn listdir_matches_ls() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let ls_names: Vec<String> = fs.ls("").unwrap();
    let ld_names: Vec<String> = fs.listdir("").unwrap().iter().map(|e| e.name.clone()).collect();
    assert_eq!(ls_names, ld_names);
}

#[test]
fn listdir_subdir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let entries = fs.listdir("dir").unwrap();
    let names: Vec<&str> = entries.iter().map(|e| e.name.as_str()).collect();
    assert!(names.contains(&"a.txt"));
    assert!(names.contains(&"b.txt"));
    assert_eq!(entries.len(), 2);
}

// ---------------------------------------------------------------------------
// tree_hash
// ---------------------------------------------------------------------------

#[test]
fn tree_hash_is_40_hex() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let hash = fs.tree_hash().unwrap();
    assert_eq!(hash.len(), 40);
    assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
}

#[test]
fn tree_hash_changes_on_write() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"hello", Default::default()).unwrap();
    let fs1 = store.branches().get("main").unwrap();
    let h1 = fs1.tree_hash().unwrap();

    fs1.write("b.txt", b"world", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.tree_hash().unwrap();

    assert_ne!(h1, h2);
}

// ---------------------------------------------------------------------------
// read_range
// ---------------------------------------------------------------------------

#[test]
fn read_range_offset_and_size() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("data.txt", b"hello world", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    // Read "world" (offset=6, size=5)
    let data = fs.read_range("data.txt", 6, Some(5)).unwrap();
    assert_eq!(data, b"world");
}

#[test]
fn read_range_offset_only() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("data.txt", b"hello world", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    // Read from offset=6 to end
    let data = fs.read_range("data.txt", 6, None).unwrap();
    assert_eq!(data, b"world");
}

#[test]
fn read_range_full() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let full = fs.read("hello.txt").unwrap();
    let ranged = fs.read_range("hello.txt", 0, None).unwrap();
    assert_eq!(full, ranged);
}

#[test]
fn read_range_size_beyond_end() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    // "hello" is 5 bytes; requesting 100 from offset 2 should clamp
    let data = fs.read_range("hello.txt", 2, Some(100)).unwrap();
    assert_eq!(data, b"llo");
}

#[test]
fn read_range_offset_at_end() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let data = fs.read_range("hello.txt", 5, Some(10)).unwrap();
    assert!(data.is_empty());
}

#[test]
fn read_range_offset_beyond_end() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let data = fs.read_range("hello.txt", 100, None).unwrap();
    assert!(data.is_empty());
}

// ---------------------------------------------------------------------------
// read_by_hash
// ---------------------------------------------------------------------------

#[test]
fn read_by_hash_full() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let hash = fs.object_hash("hello.txt").unwrap();
    let data = fs.read_by_hash(&hash, 0, None).unwrap();
    assert_eq!(data, b"hello");
}

#[test]
fn read_by_hash_ranged() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("data.txt", b"abcdefghij", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();

    let hash = fs.object_hash("data.txt").unwrap();
    let data = fs.read_by_hash(&hash, 3, Some(4)).unwrap();
    assert_eq!(data, b"defg");
}

#[test]
fn read_by_hash_roundtrip_with_object_hash() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    for path in &["hello.txt", "dir/a.txt", "dir/b.txt"] {
        let hash = fs.object_hash(path).unwrap();
        let by_hash = fs.read_by_hash(&hash, 0, None).unwrap();
        let by_path = fs.read(path).unwrap();
        assert_eq!(by_hash, by_path);
    }
}

#[test]
fn read_by_hash_invalid_hash_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.read_by_hash("not_a_valid_hash", 0, None).is_err());
}
