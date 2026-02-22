mod common;

use gitstore::*;

// ---------------------------------------------------------------------------
// read
// ---------------------------------------------------------------------------

#[test]
fn read_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_eq!(fs.read("hello.txt").unwrap(), b"hello");
}

#[test]
fn read_nested() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_eq!(fs.read("dir/a.txt").unwrap(), b"aaa");
}

#[test]
fn read_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.read("nope.txt").is_err());
}

// ---------------------------------------------------------------------------
// read_text
// ---------------------------------------------------------------------------

#[test]
fn read_text_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write_text("msg.txt", "hello world", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("msg.txt").unwrap(), "hello world");
}

// ---------------------------------------------------------------------------
// ls
// ---------------------------------------------------------------------------

#[test]
fn ls_root() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let entries = fs.ls("").unwrap();
    let names: Vec<&str> = entries.iter().map(|e| e.name.as_str()).collect();
    assert!(names.contains(&"hello.txt"));
    assert!(names.contains(&"dir"));
    assert_eq!(entries.len(), 2);
}

#[test]
fn ls_subdir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let entries = fs.ls("dir").unwrap();
    let names: Vec<&str> = entries.iter().map(|e| e.name.as_str()).collect();
    assert!(names.contains(&"a.txt"));
    assert!(names.contains(&"b.txt"));
    assert_eq!(entries.len(), 2);
}

#[test]
fn ls_on_file_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.ls("hello.txt").is_err());
}

// ---------------------------------------------------------------------------
// walk
// ---------------------------------------------------------------------------

#[test]
fn walk_root() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let entries = fs.walk("").unwrap();
    let paths: Vec<&str> = entries.iter().map(|(p, _)| p.as_str()).collect();
    assert_eq!(paths.len(), 3);
    assert!(paths.contains(&"hello.txt"));
    assert!(paths.contains(&"dir/a.txt"));
    assert!(paths.contains(&"dir/b.txt"));
}

#[test]
fn walk_subdir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let entries = fs.walk("dir").unwrap();
    let paths: Vec<&str> = entries.iter().map(|(p, _)| p.as_str()).collect();
    assert_eq!(paths.len(), 2);
    assert!(paths.contains(&"dir/a.txt"));
    assert!(paths.contains(&"dir/b.txt"));
}

// ---------------------------------------------------------------------------
// exists
// ---------------------------------------------------------------------------

#[test]
fn exists_file() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.exists("hello.txt").unwrap());
}

#[test]
fn exists_dir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.exists("dir").unwrap());
}

#[test]
fn exists_missing() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(!fs.exists("nope.txt").unwrap());
}

// ---------------------------------------------------------------------------
// is_dir
// ---------------------------------------------------------------------------

#[test]
fn is_dir_true() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.is_dir("dir").unwrap());
}

#[test]
fn is_dir_false_for_file() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(!fs.is_dir("hello.txt").unwrap());
}

#[test]
fn is_dir_false_for_missing() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(!fs.is_dir("nope").unwrap());
}

// ---------------------------------------------------------------------------
// file_type
// ---------------------------------------------------------------------------

#[test]
fn file_type_blob() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_eq!(fs.file_type("hello.txt").unwrap(), FileType::Blob);
}

#[test]
fn file_type_tree() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_eq!(fs.file_type("dir").unwrap(), FileType::Tree);
}

#[cfg(unix)]
#[test]
fn file_type_executable() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("run.sh", b"#!/bin/sh", fs::WriteOptions {
        mode: Some(MODE_BLOB_EXEC),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.file_type("run.sh").unwrap(), FileType::Executable);
}

#[cfg(unix)]
#[test]
fn file_type_link() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write_symlink("link", "hello.txt", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.file_type("link").unwrap(), FileType::Link);
}

#[test]
fn file_type_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.file_type("nope.txt").is_err());
}

// ---------------------------------------------------------------------------
// size
// ---------------------------------------------------------------------------

#[test]
fn size_correct() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_eq!(fs.size("hello.txt").unwrap(), 5);
}

#[test]
fn size_matches_read_len() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let data = fs.read("dir/a.txt").unwrap();
    assert_eq!(fs.size("dir/a.txt").unwrap(), data.len() as u64);
}

#[test]
fn size_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.size("nope.txt").is_err());
}

// ---------------------------------------------------------------------------
// object_hash
// ---------------------------------------------------------------------------

#[test]
fn object_hash_hex() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let hash = fs.object_hash("hello.txt").unwrap();
    assert_eq!(hash.len(), 40);
    assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
}

#[test]
fn object_hash_same_content() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("a.txt", b"same").unwrap();
    batch.write("b.txt", b"same").unwrap();
    batch.commit().unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(
        fs.object_hash("a.txt").unwrap(),
        fs.object_hash("b.txt").unwrap()
    );
}

#[test]
fn object_hash_different_content() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert_ne!(
        fs.object_hash("hello.txt").unwrap(),
        fs.object_hash("dir/a.txt").unwrap()
    );
}

#[test]
fn object_hash_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.object_hash("nope.txt").is_err());
}

// ---------------------------------------------------------------------------
// readlink
// ---------------------------------------------------------------------------

#[cfg(unix)]
#[test]
fn readlink_valid() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write_symlink("link", "hello.txt", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.readlink("link").unwrap(), "hello.txt");
}

#[cfg(unix)]
#[test]
fn readlink_not_symlink_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.readlink("hello.txt").is_err());
}

#[cfg(unix)]
#[test]
fn readlink_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.readlink("nope").is_err());
}

// ---------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------

#[test]
fn export_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();
    let report = fs.export(&dest).unwrap();
    assert!(report.total() > 0);
    assert_eq!(std::fs::read_to_string(dest.join("hello.txt")).unwrap(), "hello");
    assert_eq!(std::fs::read_to_string(dest.join("dir/a.txt")).unwrap(), "aaa");
}

#[cfg(unix)]
#[test]
fn export_preserves_executable() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.write("run.sh", b"#!/bin/sh", fs::WriteOptions {
        mode: Some(MODE_BLOB_EXEC),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();
    fs.export(&dest).unwrap();

    let meta = std::fs::metadata(dest.join("run.sh")).unwrap();
    assert!(meta.permissions().mode() & 0o111 != 0);
}

#[cfg(unix)]
#[test]
fn export_preserves_symlinks() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("target.txt", b"data").unwrap();
    batch.write_symlink("link", "target.txt").unwrap();
    batch.commit().unwrap();
    let fs = store.fs(Some("main")).unwrap();

    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();
    fs.export(&dest).unwrap();

    let link_target = std::fs::read_link(dest.join("link")).unwrap();
    assert_eq!(link_target.to_string_lossy(), "target.txt");
}
