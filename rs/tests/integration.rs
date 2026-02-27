use vost::types::*;
use vost::paths;

// ---------------------------------------------------------------------------
// Pure-data type construction
// ---------------------------------------------------------------------------

#[test]
fn types_are_constructible() {
    // FileType round-trip
    assert_eq!(FileType::from_mode(MODE_BLOB), Some(FileType::Blob));
    assert_eq!(FileType::from_mode(MODE_BLOB_EXEC), Some(FileType::Executable));
    assert_eq!(FileType::from_mode(MODE_LINK), Some(FileType::Link));
    assert_eq!(FileType::from_mode(MODE_TREE), Some(FileType::Tree));
    assert_eq!(FileType::Blob.filemode(), MODE_BLOB);
    assert!(FileType::Blob.is_file());
    assert!(FileType::Tree.is_dir());
    assert!(FileType::Link.is_link());
    assert_eq!(FileType::from_mode(0), None);

    // Signature default
    let sig = Signature::default();
    assert_eq!(sig.name, "vost");
    assert_eq!(sig.email, "vost@localhost");

    // OpenOptions default
    let opts = OpenOptions::default();
    assert!(!opts.create);
    assert!(opts.branch.is_none());

    // ChangeReport default
    let report = ChangeReport::new();
    assert!(report.in_sync());
    assert_eq!(report.total(), 0);

    // MirrorDiff default
    let diff = MirrorDiff::new();
    assert!(diff.in_sync());
    assert_eq!(diff.total(), 0);
}

// ---------------------------------------------------------------------------
// Path normalization
// ---------------------------------------------------------------------------

#[test]
fn path_normalization() {
    assert_eq!(paths::normalize_path("").unwrap(), "");
    assert_eq!(paths::normalize_path("a/b/c").unwrap(), "a/b/c");
    assert_eq!(paths::normalize_path("/a/b/c/").unwrap(), "a/b/c");
    assert_eq!(paths::normalize_path("a//b///c").unwrap(), "a/b/c");
    assert_eq!(paths::normalize_path("///").unwrap(), "");

    // dot segments are collapsed
    assert_eq!(paths::normalize_path("a/./b").unwrap(), "a/b");
    assert_eq!(paths::normalize_path("./a/b").unwrap(), "a/b");

    // only-dot paths resolve to empty → error
    assert!(paths::normalize_path(".").is_err());
    assert!(paths::normalize_path("./.").is_err());

    // dotdot is still rejected
    assert!(paths::normalize_path("a/../b").is_err());
    assert!(paths::normalize_path("..").is_err());
    assert!(paths::normalize_path("a/b/..").is_err());
}

// ---------------------------------------------------------------------------
// Ref name validation
// ---------------------------------------------------------------------------

#[test]
fn ref_name_validation() {
    assert!(paths::validate_ref_name("refs/heads/main").is_ok());
    assert!(paths::validate_ref_name("my-branch").is_ok());
    assert!(paths::validate_ref_name("feature/foo").is_ok());

    assert!(paths::validate_ref_name("").is_err());
    assert!(paths::validate_ref_name("a b").is_err());
    assert!(paths::validate_ref_name("a:b").is_err());
    assert!(paths::validate_ref_name("a\tb").is_err());
    assert!(paths::validate_ref_name("a\nb").is_err());
    assert!(paths::validate_ref_name("a..b").is_err());
    assert!(paths::validate_ref_name("a@{0}").is_err());
    assert!(paths::validate_ref_name("a.").is_err());
    assert!(paths::validate_ref_name("a.lock").is_err());
    assert!(paths::validate_ref_name("a\\b").is_err());
    assert!(paths::validate_ref_name("a^b").is_err());
    assert!(paths::validate_ref_name("a~b").is_err());
    assert!(paths::validate_ref_name("a?b").is_err());
    assert!(paths::validate_ref_name("a*b").is_err());
    assert!(paths::validate_ref_name("a[b").is_err());
}

// ---------------------------------------------------------------------------
// WriteEntry validation
// ---------------------------------------------------------------------------

#[test]
fn write_entry_validation() {
    // Valid blob
    let entry = WriteEntry::from_bytes(b"hello".to_vec());
    assert!(entry.validate().is_ok());

    // Valid text
    let entry = WriteEntry::from_text("hello");
    assert!(entry.validate().is_ok());

    // Valid symlink
    let entry = WriteEntry::symlink("target");
    assert!(entry.validate().is_ok());

    // Invalid: blob without data
    let entry = WriteEntry {
        data: None,
        target: None,
        mode: MODE_BLOB,
    };
    assert!(entry.validate().is_err());

    // Invalid: blob with target
    let entry = WriteEntry {
        data: Some(b"hi".to_vec()),
        target: Some("oops".into()),
        mode: MODE_BLOB,
    };
    assert!(entry.validate().is_err());

    // Invalid: symlink without target
    let entry = WriteEntry {
        data: None,
        target: None,
        mode: MODE_LINK,
    };
    assert!(entry.validate().is_err());

    // Invalid: symlink with data
    let entry = WriteEntry {
        data: Some(b"oops".to_vec()),
        target: Some("target".into()),
        mode: MODE_LINK,
    };
    assert!(entry.validate().is_err());

    // Invalid: unsupported mode
    let entry = WriteEntry {
        data: Some(b"hi".to_vec()),
        target: None,
        mode: 0o777,
    };
    assert!(entry.validate().is_err());
}

// ---------------------------------------------------------------------------
// ChangeReport actions
// ---------------------------------------------------------------------------

#[test]
fn change_report_actions() {
    let mut report = ChangeReport::new();
    report.add.push(FileEntry::new("c.txt", FileType::Blob));
    report.update.push(FileEntry::new("a.txt", FileType::Blob));
    report.delete.push(FileEntry::new("b.txt", FileType::Blob));

    assert!(!report.in_sync());
    assert_eq!(report.total(), 3);

    let actions = report.actions();
    // Should be sorted by path
    assert_eq!(actions.len(), 3);
    assert_eq!(actions[0].path, "a.txt");
    assert_eq!(actions[0].kind, ChangeActionKind::Update);
    assert_eq!(actions[1].path, "b.txt");
    assert_eq!(actions[1].kind, ChangeActionKind::Delete);
    assert_eq!(actions[2].path, "c.txt");
    assert_eq!(actions[2].kind, ChangeActionKind::Add);

    // Finalize with no errors → Ok
    let report2 = ChangeReport::new();
    assert!(report2.finalize().is_ok());

    // Finalize with errors → Err
    let mut report3 = ChangeReport::new();
    report3.errors.push(ChangeError::new("x.txt", "boom"));
    assert!(report3.finalize().is_err());
}

// ---------------------------------------------------------------------------
// Store open compiles (API shape check)
// ---------------------------------------------------------------------------

#[test]
fn store_open_and_fs() {
    let dir = tempfile::tempdir().unwrap();
    let repo_path = dir.path().join("test.git");

    // Create with branch
    let store = vost::GitStore::open(&repo_path, vost::OpenOptions {
        create: true,
        branch: Some("main".into()),
        ..Default::default()
    })
    .unwrap();

    // fs() should work
    let fs = store.branches().get("main").unwrap();
    assert!(fs.commit_hash().is_some());

    // Write and read back
    fs.write("hello.txt", b"world", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    assert_eq!(fs2.read_text("hello.txt").unwrap(), "world");
    assert!(fs2.exists("hello.txt").unwrap());
    assert!(!fs2.exists("nope.txt").unwrap());

    // Walk
    let entries = fs2.walk("").unwrap();
    // 1 directory (root) with 1 file
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].dirpath, "");
    assert_eq!(entries[0].files.len(), 1);
    assert_eq!(entries[0].files[0].name, "hello.txt");

    // Open existing (no create)
    let store2 = vost::GitStore::open(&repo_path, vost::OpenOptions {
        create: false,
        ..Default::default()
    })
    .unwrap();
    let fs3 = store2.branches().get("main").unwrap();
    assert_eq!(fs3.read_text("hello.txt").unwrap(), "world");

    // Open missing without create → error
    let result = vost::GitStore::open(dir.path().join("missing.git"), vost::OpenOptions {
        create: false,
        ..Default::default()
    });
    assert!(result.is_err());
}
