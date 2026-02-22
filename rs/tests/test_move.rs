mod common;

use gitstore::*;

fn store_with_move_files(dir: &std::path::Path) -> (GitStore, Fs) {
    let store = common::create_store(dir, "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("hello.txt", b"hello world").unwrap();
    batch.write("dir/a.txt", b"aaa").unwrap();
    batch.write("dir/b.txt", b"bbb").unwrap();
    batch.write("other/c.txt", b"ccc").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();
    (store, fs)
}

// ---------------------------------------------------------------------------
// Rename file
// ---------------------------------------------------------------------------

#[test]
fn rename_file_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("hello.txt", "renamed.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("renamed.txt").unwrap(), "hello world");
    assert!(!fs.exists("hello.txt").unwrap());
}

#[test]
fn rename_preserves_other_files() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("hello.txt", "renamed.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
    assert_eq!(fs.read_text("other/c.txt").unwrap(), "ccc");
}

// ---------------------------------------------------------------------------
// Rename directory
// ---------------------------------------------------------------------------

#[test]
fn rename_directory_basic() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("dir", "newdir", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.read_text("newdir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("newdir/b.txt").unwrap(), "bbb");
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert!(!fs.exists("dir/b.txt").unwrap());
}

#[test]
fn rename_directory_preserves_others() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("dir", "moved", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    // hello.txt and other/ should still be there
    assert_eq!(fs.read_text("hello.txt").unwrap(), "hello world");
    assert_eq!(fs.read_text("other/c.txt").unwrap(), "ccc");
}

// ---------------------------------------------------------------------------
// Rename to different directory
// ---------------------------------------------------------------------------

#[test]
fn rename_file_to_new_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("hello.txt", "newdir/hello.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("newdir/hello.txt").unwrap(), "hello world");
}

#[test]
fn rename_nested_file() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("dir/a.txt", "dir/renamed_a.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert_eq!(fs.read_text("dir/renamed_a.txt").unwrap(), "aaa");
    // b.txt still there
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn rename_file_across_directories() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("dir/a.txt", "other/moved_a.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert_eq!(fs.read_text("other/moved_a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("other/c.txt").unwrap(), "ccc");
}

// ---------------------------------------------------------------------------
// Atomicity
// ---------------------------------------------------------------------------

#[test]
fn rename_is_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    let log_before = fs.log(Default::default()).unwrap();
    fs.rename("hello.txt", "moved.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let log_after = fs.log(Default::default()).unwrap();
    assert_eq!(log_after.len(), log_before.len() + 1);
}

#[test]
fn rename_previous_commit_has_original() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("hello.txt", "moved.txt", Default::default()).unwrap();
    let fs = store.branches().get("main").unwrap();
    let prev = fs.back(1).unwrap();
    assert!(prev.exists("hello.txt").unwrap());
    assert!(!prev.exists("moved.txt").unwrap());
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[test]
fn rename_nonexistent_source_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_move_files(dir.path());
    assert!(fs.rename("missing.txt", "dest.txt", Default::default()).is_err());
}

// ---------------------------------------------------------------------------
// Custom message
// ---------------------------------------------------------------------------

#[test]
fn rename_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    fs.rename("hello.txt", "moved.txt", fs::WriteOptions {
        message: Some("renamed hello".into()),
        ..Default::default()
    })
    .unwrap();
    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "renamed hello");
}

// ---------------------------------------------------------------------------
// Stale
// ---------------------------------------------------------------------------

#[test]
fn rename_on_stale_errors() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs_old = store.branches().get("main").unwrap();

    // Advance
    let fs_new = store.branches().get("main").unwrap();
    fs_new.write("b.txt", b"b", Default::default()).unwrap();

    assert!(fs_old.rename("a.txt", "moved.txt", Default::default()).is_err());
}

// ---------------------------------------------------------------------------
// Directory rename preserves content
// ---------------------------------------------------------------------------

#[test]
fn rename_directory_deep() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("src/a/b/c.txt", b"deep").unwrap();
    batch.write("src/x.txt", b"x").unwrap();
    batch.commit().unwrap();

    let fs = store.branches().get("main").unwrap();
    fs.rename("src", "dest", Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("src").unwrap());
    assert_eq!(fs.read_text("dest/a/b/c.txt").unwrap(), "deep");
    assert_eq!(fs.read_text("dest/x.txt").unwrap(), "x");
}

// ---------------------------------------------------------------------------
// move_paths — multiple sources
// ---------------------------------------------------------------------------

#[test]
fn move_multiple_files_into_directory() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());

    fs.move_paths(
        &["hello.txt", "other/c.txt"],
        "dir",
        Default::default(),
    )
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    // Moved files should be inside dir/
    assert_eq!(fs.read_text("dir/hello.txt").unwrap(), "hello world");
    assert_eq!(fs.read_text("dir/c.txt").unwrap(), "ccc");
    // Originals gone
    assert!(!fs.exists("hello.txt").unwrap());
    assert!(!fs.exists("other/c.txt").unwrap());
    // Pre-existing dir files still there
    assert_eq!(fs.read_text("dir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("dir/b.txt").unwrap(), "bbb");
}

#[test]
fn move_multiple_requires_dest_dir() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_move_files(dir.path());

    // Multiple sources to non-existent dest should error
    let result = fs.move_paths(
        &["hello.txt", "dir/a.txt"],
        "nonexistent",
        Default::default(),
    );
    assert!(result.is_err());
}

#[test]
fn move_single_to_new_name() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());

    fs.move_paths(&["hello.txt"], "renamed.txt", Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("hello.txt").unwrap());
    assert_eq!(fs.read_text("renamed.txt").unwrap(), "hello world");
}

// ---------------------------------------------------------------------------
// move_paths — dry run
// ---------------------------------------------------------------------------

#[test]
fn move_dry_run_no_changes() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    let hash_before = fs.commit_hash().unwrap();

    fs.move_paths(&["hello.txt"], "moved.txt", fs::MoveOptions {
        dry_run: true,
        ..Default::default()
    })
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert_eq!(fs.commit_hash().unwrap(), hash_before);
    assert!(fs.exists("hello.txt").unwrap());
    assert!(!fs.exists("moved.txt").unwrap());
}

// ---------------------------------------------------------------------------
// move_paths — directory without recursive
// ---------------------------------------------------------------------------

#[test]
fn move_directory_without_recursive_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_move_files(dir.path());

    let result = fs.move_paths(&["dir"], "newdir", Default::default());
    assert!(result.is_err());
}

#[test]
fn move_directory_recursive() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());

    fs.move_paths(&["dir"], "newdir", fs::MoveOptions {
        recursive: true,
        ..Default::default()
    })
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    assert!(!fs.exists("dir/a.txt").unwrap());
    assert_eq!(fs.read_text("newdir/a.txt").unwrap(), "aaa");
    assert_eq!(fs.read_text("newdir/b.txt").unwrap(), "bbb");
}

// ---------------------------------------------------------------------------
// move_paths — custom message
// ---------------------------------------------------------------------------

#[test]
fn move_paths_custom_message() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());

    fs.move_paths(&["hello.txt"], "moved.txt", fs::MoveOptions {
        message: Some("custom move msg".into()),
        ..Default::default()
    })
    .unwrap();

    let fs = store.branches().get("main").unwrap();
    let log = fs.log(fs::LogOptions { limit: Some(1), ..Default::default() }).unwrap();
    assert_eq!(log[0].message, "custom move msg");
}

// ---------------------------------------------------------------------------
// move_paths — single commit
// ---------------------------------------------------------------------------

#[test]
fn move_multiple_is_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (store, fs) = store_with_move_files(dir.path());
    let log_before = fs.log(Default::default()).unwrap();

    fs.move_paths(&["hello.txt", "other/c.txt"], "dir", Default::default()).unwrap();

    let fs = store.branches().get("main").unwrap();
    let log_after = fs.log(Default::default()).unwrap();
    assert_eq!(log_after.len(), log_before.len() + 1);
}

// ---------------------------------------------------------------------------
// move_paths — nonexistent source
// ---------------------------------------------------------------------------

#[test]
fn move_nonexistent_source_errors() {
    let dir = tempfile::tempdir().unwrap();
    let (_, fs) = store_with_move_files(dir.path());
    assert!(fs.move_paths(&["missing.txt"], "dest.txt", Default::default()).is_err());
}
