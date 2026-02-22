mod common;

use gitstore::*;
use std::path::Path;

fn create_disk_files(dir: &Path) {
    std::fs::create_dir_all(dir.join("sub")).unwrap();
    std::fs::write(dir.join("file1.txt"), b"one").unwrap();
    std::fs::write(dir.join("file2.txt"), b"two").unwrap();
    std::fs::write(dir.join("sub/deep.txt"), b"deep").unwrap();
}

// ---------------------------------------------------------------------------
// copy_in
// ---------------------------------------------------------------------------

#[test]
fn copy_in_basic() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let report = fs.copy_in(&src, "", Default::default()).unwrap();
    assert!(report.total() > 0);

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("file1.txt").unwrap(), "one");
    assert_eq!(fs.read_text("sub/deep.txt").unwrap(), "deep");
}

#[test]
fn copy_in_nested() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", Default::default()).unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert!(fs.exists("sub/deep.txt").unwrap());
}

#[test]
fn copy_in_with_dest_prefix() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "imported", Default::default()).unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("imported/file1.txt").unwrap(), "one");
}

#[test]
fn copy_in_include_filter() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", fs::CopyInOptions {
        include: Some(vec!["*.txt".into()]),
        ..Default::default()
    })
    .unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert!(fs.exists("file1.txt").unwrap());
}

#[test]
fn copy_in_exclude_filter() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", fs::CopyInOptions {
        exclude: Some(vec!["sub/*".into()]),
        ..Default::default()
    })
    .unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert!(fs.exists("file1.txt").unwrap());
    assert!(!fs.exists("sub/deep.txt").unwrap());
}

// ---------------------------------------------------------------------------
// copy_out
// ---------------------------------------------------------------------------

#[test]
fn copy_out_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    let report = fs.copy_out("", &dest, Default::default()).unwrap();
    assert!(report.total() > 0);
    assert_eq!(std::fs::read_to_string(dest.join("hello.txt")).unwrap(), "hello");
}

#[test]
fn copy_out_creates_dirs() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    fs.copy_out("", &dest, Default::default()).unwrap();
    assert!(dest.join("dir").is_dir());
    assert_eq!(
        std::fs::read_to_string(dest.join("dir/a.txt")).unwrap(),
        "aaa"
    );
}

#[cfg(unix)]
#[test]
fn copy_out_preserves_executable() {
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
    fs.copy_out("", &dest, Default::default()).unwrap();

    let meta = std::fs::metadata(dest.join("run.sh")).unwrap();
    assert!(meta.permissions().mode() & 0o111 != 0);
}

#[cfg(unix)]
#[test]
fn copy_out_preserves_symlinks() {
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
    fs.copy_out("", &dest, Default::default()).unwrap();

    let link_target = std::fs::read_link(dest.join("link")).unwrap();
    assert_eq!(link_target.to_string_lossy(), "target.txt");
}

#[test]
fn copy_out_include_filter() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    fs.copy_out("", &dest, fs::CopyOutOptions {
        include: Some(vec!["*.txt".into()]),
        ..Default::default()
    })
    .unwrap();

    assert!(dest.join("hello.txt").exists());
}

#[test]
fn copy_out_exclude_filter() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    fs.copy_out("", &dest, fs::CopyOutOptions {
        exclude: Some(vec!["dir/*".into()]),
        ..Default::default()
    })
    .unwrap();

    assert!(dest.join("hello.txt").exists());
    assert!(!dest.join("dir/a.txt").exists());
}

// ---------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------

#[test]
fn export_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("exported");
    std::fs::create_dir(&dest).unwrap();

    fs.export(&dest).unwrap();
    assert_eq!(std::fs::read_to_string(dest.join("hello.txt")).unwrap(), "hello");
    assert_eq!(std::fs::read_to_string(dest.join("dir/a.txt")).unwrap(), "aaa");
    assert_eq!(std::fs::read_to_string(dest.join("dir/b.txt")).unwrap(), "bbb");
}

// ---------------------------------------------------------------------------
// sync_in / sync_out
// ---------------------------------------------------------------------------

#[test]
fn sync_in_basic() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let report = fs.sync_in(&src, "", Default::default()).unwrap();
    assert!(report.total() > 0);

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("file1.txt").unwrap(), "one");
}

#[test]
fn sync_out_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("synced");
    std::fs::create_dir(&dest).unwrap();

    let report = fs.sync_out("", &dest, Default::default()).unwrap();
    assert!(report.total() > 0);
    assert_eq!(std::fs::read_to_string(dest.join("hello.txt")).unwrap(), "hello");
}

// ---------------------------------------------------------------------------
// remove (disk)
// ---------------------------------------------------------------------------

#[test]
fn remove_disk_files() {
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("to_remove");
    std::fs::create_dir(&target).unwrap();
    std::fs::write(target.join("a.txt"), b"a").unwrap();
    std::fs::write(target.join("b.txt"), b"b").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let report = fs.remove(&target, Default::default()).unwrap();
    assert!(report.total() > 0);
    assert!(!target.join("a.txt").exists());
    assert!(!target.join("b.txt").exists());
}

#[test]
fn remove_with_include_filter() {
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("to_remove");
    std::fs::create_dir(&target).unwrap();
    std::fs::write(target.join("a.txt"), b"a").unwrap();
    std::fs::write(target.join("keep.md"), b"keep").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.remove(&target, fs::RemoveOptions {
        include: Some(vec!["*.txt".into()]),
        ..Default::default()
    })
    .unwrap();

    assert!(!target.join("a.txt").exists());
    assert!(target.join("keep.md").exists());
}

// ---------------------------------------------------------------------------
// rename
// ---------------------------------------------------------------------------

#[test]
fn rename_single_file() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "goodbye.txt", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("goodbye.txt").unwrap(), "hello");
}

#[test]
fn rename_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("dir", "moved", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert!(!fs.exists("dir").unwrap());
    assert_eq!(fs.read_text("moved/a.txt").unwrap(), "aaa");
}

#[test]
fn rename_missing_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    assert!(fs.rename("nope.txt", "dest.txt", Default::default()).is_err());
}

// ---------------------------------------------------------------------------
// copy_in — edge cases
// ---------------------------------------------------------------------------

#[test]
fn copy_in_empty_file() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    std::fs::create_dir_all(&src).unwrap();
    std::fs::write(src.join("empty.txt"), b"").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", Default::default()).unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read("empty.txt").unwrap(), b"");
}

#[test]
fn copy_in_binary_data() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    std::fs::create_dir_all(&src).unwrap();
    let data: Vec<u8> = (0u8..=255).collect();
    std::fs::write(src.join("binary.bin"), &data).unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", Default::default()).unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read("binary.bin").unwrap(), data);
}

#[test]
fn copy_in_deep_nesting() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    std::fs::create_dir_all(src.join("a/b/c/d")).unwrap();
    std::fs::write(src.join("a/b/c/d/deep.txt"), b"deep").unwrap();

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", Default::default()).unwrap();

    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("a/b/c/d/deep.txt").unwrap(), "deep");
}

#[test]
fn copy_in_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    fs.copy_in(&src, "", fs::CopyInOptions {
        message: Some("import files".into()),
        ..Default::default()
    })
    .unwrap();

    let fs = store.fs(Some("main")).unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), skip: None }).unwrap();
    assert_eq!(log[0].message, "import files");
}

// ---------------------------------------------------------------------------
// copy_out — edge cases
// ---------------------------------------------------------------------------

#[test]
fn copy_out_subdirectory() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    fs.copy_out("dir", &dest, Default::default()).unwrap();
    // copy_out("dir") walks the "dir" tree, so paths are relative to it
    assert_eq!(std::fs::read_to_string(dest.join("a.txt")).unwrap(), "aaa");
    assert_eq!(std::fs::read_to_string(dest.join("b.txt")).unwrap(), "bbb");
    // hello.txt should not be exported (it's outside "dir")
    assert!(!dest.join("hello.txt").exists());
}

#[test]
fn copy_out_single_file() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = common::store_with_files(dir.path());
    let dest = dir.path().join("out");
    std::fs::create_dir(&dest).unwrap();

    // Export just the root which includes hello.txt
    fs.copy_out("", &dest, fs::CopyOutOptions {
        include: Some(vec!["hello.txt".into()]),
        ..Default::default()
    })
    .unwrap();

    assert!(dest.join("hello.txt").exists());
}

// ---------------------------------------------------------------------------
// sync — idempotent
// ---------------------------------------------------------------------------

#[test]
fn sync_in_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    let src = dir.path().join("src_files");
    create_disk_files(&src);

    let store = common::create_store(dir.path(), "main");

    // First sync
    let fs = store.fs(Some("main")).unwrap();
    fs.sync_in(&src, "", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let hash1 = fs.commit_hash().unwrap();

    // Second sync with same files — should be no-op
    fs.sync_in(&src, "", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let hash2 = fs.commit_hash().unwrap();

    assert_eq!(hash1, hash2);
}

// ---------------------------------------------------------------------------
// export — edge cases
// ---------------------------------------------------------------------------

#[test]
fn export_empty_repo() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.fs(Some("main")).unwrap();
    let dest = dir.path().join("exported");
    std::fs::create_dir(&dest).unwrap();

    let report = fs.export(&dest).unwrap();
    assert_eq!(report.total(), 0);
}

// ---------------------------------------------------------------------------
// rename — content preservation
// ---------------------------------------------------------------------------

#[test]
fn rename_preserves_content() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("dir/a.txt", "dir/renamed_a.txt", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert_eq!(fs.read_text("dir/renamed_a.txt").unwrap(), "aaa");
    assert!(!fs.exists("dir/a.txt").unwrap());
    // b.txt still present
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn rename_to_different_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "newdir/hello.txt", Default::default()).unwrap();
    let fs = store.fs(Some("main")).unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("newdir/hello.txt").unwrap(), "hello");
}

#[test]
fn rename_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = common::store_with_files(dir.path());
    fs.rename("hello.txt", "moved.txt", fs::WriteOptions {
        message: Some("move hello".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.fs(Some("main")).unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), skip: None }).unwrap();
    assert_eq!(log[0].message, "move hello");
}
