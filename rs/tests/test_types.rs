use vost::*;

// ---------------------------------------------------------------------------
// FileType
// ---------------------------------------------------------------------------

#[test]
fn file_type_from_mode_blob() {
    assert_eq!(FileType::from_mode(MODE_BLOB), Some(FileType::Blob));
}

#[test]
fn file_type_from_mode_exec() {
    assert_eq!(FileType::from_mode(MODE_BLOB_EXEC), Some(FileType::Executable));
}

#[test]
fn file_type_from_mode_link() {
    assert_eq!(FileType::from_mode(MODE_LINK), Some(FileType::Link));
}

#[test]
fn file_type_from_mode_tree() {
    assert_eq!(FileType::from_mode(MODE_TREE), Some(FileType::Tree));
}

#[test]
fn file_type_from_mode_unknown() {
    assert!(FileType::from_mode(0o777777).is_none());
}

// ---------------------------------------------------------------------------
// ChangeReport
// ---------------------------------------------------------------------------

#[test]
fn change_report_default_empty() {
    let r = ChangeReport::new();
    assert!(r.add.is_empty());
    assert!(r.update.is_empty());
    assert!(r.delete.is_empty());
    assert!(r.errors.is_empty());
    assert_eq!(r.total(), 0);
    assert!(r.in_sync());
}

#[test]
fn change_report_total() {
    let r = ChangeReport {
        add: vec![FileEntry::new("a.txt", FileType::Blob), FileEntry::new("b.txt", FileType::Blob)],
        update: vec![FileEntry::new("c.txt", FileType::Blob)],
        delete: vec![FileEntry::new("d.txt", FileType::Blob), FileEntry::new("e.txt", FileType::Blob), FileEntry::new("f.txt", FileType::Blob)],
        ..Default::default()
    };
    assert_eq!(r.total(), 6);
    assert!(!r.in_sync());
}

#[test]
fn change_report_in_sync_when_empty() {
    let r = ChangeReport {
        errors: vec![ChangeError::new("path", "msg")],
        ..Default::default()
    };
    assert!(r.in_sync());
    assert_eq!(r.total(), 0);
}

#[test]
fn change_report_actions_sorted() {
    let r = ChangeReport {
        add: vec![FileEntry::new("z.txt", FileType::Blob), FileEntry::new("a.txt", FileType::Blob)],
        delete: vec![FileEntry::new("m.txt", FileType::Blob)],
        ..Default::default()
    };
    let actions = r.actions();
    assert_eq!(actions.len(), 3);
    assert_eq!(actions[0].path, "a.txt");
    assert_eq!(actions[0].kind, ChangeActionKind::Add);
    assert_eq!(actions[1].path, "m.txt");
    assert_eq!(actions[1].kind, ChangeActionKind::Delete);
    assert_eq!(actions[2].path, "z.txt");
    assert_eq!(actions[2].kind, ChangeActionKind::Add);
}

#[test]
fn change_report_finalize_ok() {
    let r = ChangeReport {
        add: vec![FileEntry::new("a.txt", FileType::Blob)],
        ..Default::default()
    };
    assert!(r.finalize().is_ok());
}

#[test]
fn change_report_finalize_errors() {
    let r = ChangeReport {
        errors: vec![ChangeError::new("a.txt", "permission denied")],
        ..Default::default()
    };
    assert!(r.finalize().is_err());
}

// ---------------------------------------------------------------------------
// ChangeAction
// ---------------------------------------------------------------------------

#[test]
fn change_action_ordering() {
    let a = ChangeAction::new(ChangeActionKind::Add, "a.txt");
    let b = ChangeAction::new(ChangeActionKind::Delete, "b.txt");
    assert!(a < b);
}

#[test]
fn change_action_same_path_equal() {
    let a = ChangeAction::new(ChangeActionKind::Add, "same.txt");
    let b = ChangeAction::new(ChangeActionKind::Delete, "same.txt");
    // Ordering is by path only
    assert_eq!(a.cmp(&b), std::cmp::Ordering::Equal);
}

// ---------------------------------------------------------------------------
// ChangeError
// ---------------------------------------------------------------------------

#[test]
fn change_error_fields() {
    let e = ChangeError::new("path/to/file", "something went wrong");
    assert_eq!(e.path, "path/to/file");
    assert_eq!(e.error, "something went wrong");
}

// ---------------------------------------------------------------------------
// WriteEntry
// ---------------------------------------------------------------------------

#[test]
fn write_entry_from_bytes_mode() {
    let e = WriteEntry::from_bytes(vec![1, 2, 3]);
    assert_eq!(e.mode, MODE_BLOB);
    assert!(e.validate().is_ok());
}

#[test]
fn write_entry_from_text_utf8() {
    let e = WriteEntry::from_text("caf\u{e9}");
    assert_eq!(e.data.unwrap(), "caf\u{e9}".as_bytes());
}

#[test]
fn write_entry_symlink_mode() {
    let e = WriteEntry::symlink("target");
    assert_eq!(e.mode, MODE_LINK);
    assert!(e.validate().is_ok());
}

// ---------------------------------------------------------------------------
// MirrorDiff
// ---------------------------------------------------------------------------

#[test]
fn mirror_diff_default_in_sync() {
    let d = MirrorDiff::new();
    assert!(d.in_sync());
    assert_eq!(d.total(), 0);
}

#[test]
fn mirror_diff_total() {
    let d = MirrorDiff {
        add: vec![RefChange {
            ref_name: "refs/heads/main".into(),
            old_target: None,
            new_target: Some("abc".into()),
        }],
        update: vec![RefChange {
            ref_name: "refs/heads/dev".into(),
            old_target: Some("old".into()),
            new_target: Some("new".into()),
        }],
        delete: vec![],
    };
    assert_eq!(d.total(), 2);
    assert!(!d.in_sync());
}

#[test]
fn mirror_diff_all_categories() {
    let d = MirrorDiff {
        add: vec![RefChange {
            ref_name: "a".into(),
            old_target: None,
            new_target: Some("1".into()),
        }],
        update: vec![RefChange {
            ref_name: "b".into(),
            old_target: Some("2".into()),
            new_target: Some("3".into()),
        }],
        delete: vec![
            RefChange {
                ref_name: "c".into(),
                old_target: Some("4".into()),
                new_target: None,
            },
            RefChange {
                ref_name: "d".into(),
                old_target: Some("5".into()),
                new_target: None,
            },
        ],
    };
    assert_eq!(d.total(), 4);
    assert!(!d.in_sync());
}

// ---------------------------------------------------------------------------
// RefChange
// ---------------------------------------------------------------------------

#[test]
fn ref_change_fields() {
    let c = RefChange {
        ref_name: "refs/heads/main".into(),
        old_target: Some("abc1234".into()),
        new_target: None,
    };
    assert_eq!(c.ref_name, "refs/heads/main");
    assert_eq!(c.old_target.as_deref(), Some("abc1234"));
    assert!(c.new_target.is_none());
}

// ---------------------------------------------------------------------------
// Signature
// ---------------------------------------------------------------------------

#[test]
fn signature_default() {
    let s = Signature::default();
    assert_eq!(s.name, "vost");
    assert_eq!(s.email, "vost@localhost");
}

// ---------------------------------------------------------------------------
// OpenOptions
// ---------------------------------------------------------------------------

#[test]
fn open_options_default() {
    let o = OpenOptions::default();
    assert!(!o.create);
    assert!(o.branch.is_none());
    assert!(o.author.is_none());
    assert!(o.email.is_none());
}
