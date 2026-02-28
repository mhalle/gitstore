mod common;

use std::process::Command;
use vost::*;

// ---------------------------------------------------------------------------
// Helpers using git CLI (no direct git library access below our API layer)
// ---------------------------------------------------------------------------

/// Run a git command in the store's repo directory and return stdout.
fn git(store: &GitStore, args: &[&str]) -> String {
    let output = Command::new("git")
        .args(args)
        .current_dir(store.path())
        .output()
        .expect("failed to run git");
    String::from_utf8(output.stdout).unwrap().trim().to_string()
}

/// Create a note in 2/38 fanout layout directly via git CLI.
fn create_fanout_note(store: &GitStore, namespace: &str, hash: &str, text: &str) {
    let repo_path = store.path();
    let ref_name = format!("refs/notes/{}", namespace);
    let prefix = &hash[..2];
    let suffix = &hash[2..];

    let run = |args: &[&str]| -> String {
        let output = Command::new("git")
            .args(args)
            .current_dir(repo_path)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .spawn()
            .expect("failed to run git");
        let out = output.wait_with_output().unwrap();
        String::from_utf8(out.stdout).unwrap().trim().to_string()
    };

    let run_stdin = |args: &[&str], input: &[u8]| -> String {
        use std::io::Write;
        let mut child = Command::new("git")
            .args(args)
            .current_dir(repo_path)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .spawn()
            .expect("failed to run git");
        child.stdin.take().unwrap().write_all(input).unwrap();
        let out = child.wait_with_output().unwrap();
        String::from_utf8(out.stdout).unwrap().trim().to_string()
    };

    // Create blob from text
    let blob_oid = run_stdin(&["hash-object", "-w", "--stdin"], text.as_bytes());

    // Build subtree: suffix -> blob
    let sub_tree_line = format!("100644 blob {}\t{}", blob_oid, suffix);
    let sub_tree_oid = run_stdin(&["mktree"], sub_tree_line.as_bytes());

    // Read existing root tree entries (if ref exists)
    let existing_entries = {
        let output = Command::new("git")
            .args(["rev-parse", "--verify", &ref_name])
            .current_dir(repo_path)
            .output()
            .unwrap();
        if output.status.success() {
            let tip = String::from_utf8(output.stdout).unwrap().trim().to_string();
            let tree_oid = run(&["rev-parse", &format!("{}^{{tree}}", tip)]);
            let ls_output = Command::new("git")
                .args(["ls-tree", &tree_oid])
                .current_dir(repo_path)
                .output()
                .unwrap();
            String::from_utf8(ls_output.stdout).unwrap()
        } else {
            String::new()
        }
    };

    // Build new root tree: existing entries + fanout subtree
    let mut mktree_input = String::new();
    for line in existing_entries.lines() {
        if !line.is_empty() {
            mktree_input.push_str(line);
            mktree_input.push('\n');
        }
    }
    mktree_input.push_str(&format!("040000 tree {}\t{}\n", sub_tree_oid, prefix));
    let root_tree_oid = run_stdin(&["mktree"], mktree_input.as_bytes());

    // Create commit (with parent if ref exists)
    let parent_check = Command::new("git")
        .args(["rev-parse", "--verify", &ref_name])
        .current_dir(repo_path)
        .output()
        .unwrap();
    let commit_oid = if parent_check.status.success() {
        let parent = String::from_utf8(parent_check.stdout).unwrap().trim().to_string();
        run(&["commit-tree", &root_tree_oid, "-p", &parent, "-m", "fanout note"])
    } else {
        run(&["commit-tree", &root_tree_oid, "-m", "fanout note"])
    };

    // Update ref
    run(&["update-ref", &ref_name, &commit_oid]);
}

/// Count commits on a notes ref by walking the chain via git CLI.
fn notes_chain_length(store: &GitStore, namespace: &str) -> usize {
    let ref_name = format!("refs/notes/{}", namespace);
    let output = Command::new("git")
        .args(["rev-parse", "--verify", &ref_name])
        .current_dir(store.path())
        .output()
        .unwrap();
    if !output.status.success() {
        return 0;
    }
    let log_output = Command::new("git")
        .args(["rev-list", &ref_name])
        .current_dir(store.path())
        .output()
        .unwrap();
    let text = String::from_utf8(log_output.stdout).unwrap();
    text.lines().filter(|l| !l.is_empty()).count()
}

/// Get parent count of the tip commit on a notes ref via git CLI.
fn notes_tip_parent_count(store: &GitStore, namespace: &str) -> usize {
    let ref_name = format!("refs/notes/{}", namespace);
    let output = Command::new("git")
        .args(["cat-file", "-p", &ref_name])
        .current_dir(store.path())
        .output()
        .unwrap();
    let text = String::from_utf8(output.stdout).unwrap();
    text.lines().filter(|l| l.starts_with("parent ")).count()
}

// ---------------------------------------------------------------------------
// Basic CRUD
// ---------------------------------------------------------------------------

#[test]
fn set_and_get() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "hello").unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "hello");
}

#[test]
fn get_missing_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let result = store.notes().commits().get(&hash);
    assert!(result.is_err());
}

#[test]
fn has_true() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "note").unwrap();
    assert!(store.notes().commits().has(&hash).unwrap());
}

#[test]
fn has_false() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    assert!(!store.notes().commits().has(&hash).unwrap());
}

#[test]
fn delete_note() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "note").unwrap();
    store.notes().commits().delete(&hash).unwrap();
    assert!(!store.notes().commits().has(&hash).unwrap());
}

#[test]
fn delete_missing_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    assert!(store.notes().commits().delete(&hash).is_err());
}

#[test]
fn overwrite() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "first").unwrap();
    store.notes().commits().set(&hash, "second").unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "second");
}

#[test]
fn empty_note_text() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "").unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "");
}

// ---------------------------------------------------------------------------
// get_for_current_branch
// ---------------------------------------------------------------------------

#[test]
fn for_current_branch_read() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "my note").unwrap();
    assert_eq!(
        store.notes().commits().get_for_current_branch(&store).unwrap(),
        "my note"
    );
}

#[test]
fn for_current_branch_write() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store
        .notes()
        .commits()
        .set_for_current_branch(&store, "written via method")
        .unwrap();
    assert_eq!(
        store.notes().commits().get(&hash).unwrap(),
        "written via method"
    );
}

#[test]
fn for_current_branch_no_note_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert!(store.notes().commits().get_for_current_branch(&store).is_err());
}

#[test]
fn for_current_branch_after_new_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "note on old").unwrap();
    // Create a new commit
    fs.write("file.txt", b"data", Default::default()).unwrap();
    // for_current_branch should now point to the new commit (which has no note)
    assert!(store.notes().commits().get_for_current_branch(&store).is_err());
}

// ---------------------------------------------------------------------------
// Iteration / len
// ---------------------------------------------------------------------------

#[test]
fn list_empty() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert_eq!(store.notes().commits().list().unwrap(), Vec::<String>::new());
}

#[test]
fn list_multiple() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs1 = store.branches().get("main").unwrap();
    let h1 = fs1.commit_hash().unwrap();
    fs1.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    store.notes().commits().set(&h1, "note1").unwrap();
    store.notes().commits().set(&h2, "note2").unwrap();

    let mut hashes = store.notes().commits().list().unwrap();
    hashes.sort();
    let mut expected = vec![h1, h2];
    expected.sort();
    assert_eq!(hashes, expected);
}

#[test]
fn len_empty() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert_eq!(store.notes().commits().len().unwrap(), 0);
}

#[test]
fn len_after_adds() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs1 = store.branches().get("main").unwrap();
    let h1 = fs1.commit_hash().unwrap();
    fs1.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    store.notes().commits().set(&h1, "n1").unwrap();
    store.notes().commits().set(&h2, "n2").unwrap();

    assert_eq!(store.notes().commits().len().unwrap(), 2);
}

#[test]
fn len_after_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "note").unwrap();
    assert_eq!(store.notes().commits().len().unwrap(), 1);
    store.notes().commits().delete(&hash).unwrap();
    assert_eq!(store.notes().commits().len().unwrap(), 0);
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

#[test]
fn unicode_text() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let text = "Unicode: \u{e9}\u{e8}\u{ea} \u{2603} \u{1f600}";
    store.notes().commits().set(&hash, text).unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), text);
}

#[test]
fn multiline_text() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let text = "line1\nline2\nline3\n";
    store.notes().commits().set(&hash, text).unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), text);
}

#[test]
fn invalid_hash_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert!(store.notes().commits().set("not-a-hash", "note").is_err());
}

#[test]
fn invalid_hash_too_short() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert!(store.notes().commits().set("abcd", "note").is_err());
}

#[test]
fn uppercase_hash_rejected() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let hash = "A".repeat(40);
    assert!(store.notes().commits().set(&hash, "note").is_err());
}

#[test]
fn note_on_nonexistent_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let fake_hash = "a".repeat(40);
    store.notes().commits().set(&fake_hash, "orphan note").unwrap();
    assert_eq!(
        store.notes().commits().get(&fake_hash).unwrap(),
        "orphan note"
    );
}

// ---------------------------------------------------------------------------
// Commit chain
// ---------------------------------------------------------------------------

#[test]
fn first_note_no_parent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "first").unwrap();
    assert_eq!(notes_tip_parent_count(&store, "commits"), 0);
}

#[test]
fn second_note_has_parent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let h1 = fs.commit_hash().unwrap();
    fs.write("f.txt", b"x", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    store.notes().commits().set(&h1, "first").unwrap();
    assert_eq!(notes_chain_length(&store, "commits"), 1);

    store.notes().commits().set(&h2, "second").unwrap();
    assert_eq!(notes_chain_length(&store, "commits"), 2);
    assert_eq!(notes_tip_parent_count(&store, "commits"), 1);
}

#[test]
fn multiple_notes_chain() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let mut snap = store.branches().get("main").unwrap();
    let mut hashes = vec![snap.commit_hash().unwrap()];
    for i in 0..3 {
        snap.write(&format!("f{}.txt", i), b"x", Default::default()).unwrap();
        snap = store.branches().get("main").unwrap();
        hashes.push(snap.commit_hash().unwrap());
    }

    for (i, h) in hashes.iter().enumerate() {
        store
            .notes()
            .commits()
            .set(h, &format!("note {}", i))
            .unwrap();
    }

    assert_eq!(notes_chain_length(&store, "commits"), 4);
}

// ---------------------------------------------------------------------------
// Fanout interop
// ---------------------------------------------------------------------------

#[test]
fn read_fanout_note() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    create_fanout_note(&store, "commits", &hash, "fanout note");
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "fanout note");
}

#[test]
fn list_fanout() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    create_fanout_note(&store, "commits", &hash, "fanout");
    let hashes = store.notes().commits().list().unwrap();
    assert!(hashes.contains(&hash));
}

#[test]
fn has_fanout() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    create_fanout_note(&store, "commits", &hash, "fanout");
    assert!(store.notes().commits().has(&hash).unwrap());
}

#[test]
fn delete_fanout() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    create_fanout_note(&store, "commits", &hash, "fanout");
    store.notes().commits().delete(&hash).unwrap();
    assert!(!store.notes().commits().has(&hash).unwrap());
}

#[test]
fn overwrite_fanout_with_flat() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    create_fanout_note(&store, "commits", &hash, "fanout original");
    store.notes().commits().set(&hash, "flat replacement").unwrap();
    assert_eq!(
        store.notes().commits().get(&hash).unwrap(),
        "flat replacement"
    );
}

// ---------------------------------------------------------------------------
// NoteDict container
// ---------------------------------------------------------------------------

#[test]
fn commits_accessor() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    // Just verify it compiles and returns a NoteNamespace
    let _ns = store.notes().commits();
}

#[test]
fn custom_namespace() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().namespace("reviews").set(&hash, "LGTM").unwrap();
    assert_eq!(
        store.notes().namespace("reviews").get(&hash).unwrap(),
        "LGTM"
    );
}

#[test]
fn separate_namespaces_independent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "default note").unwrap();
    store.notes().namespace("reviews").set(&hash, "review note").unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "default note");
    assert_eq!(
        store.notes().namespace("reviews").get(&hash).unwrap(),
        "review note"
    );
}

#[test]
fn display_note_dict() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let s = format!("{}", store.notes());
    assert!(s.contains("NoteDict"));
}

// ---------------------------------------------------------------------------
// Batch
// ---------------------------------------------------------------------------

#[test]
fn batch_multiple_writes_single_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs1 = store.branches().get("main").unwrap();
    let h1 = fs1.commit_hash().unwrap();
    fs1.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    let mut b = store.notes().commits().batch();
    b.set(&h1, "note 1").unwrap();
    b.set(&h2, "note 2").unwrap();
    b.commit().unwrap();

    assert_eq!(store.notes().commits().get(&h1).unwrap(), "note 1");
    assert_eq!(store.notes().commits().get(&h2).unwrap(), "note 2");

    // Only one commit on the notes ref (no parents)
    assert_eq!(notes_tip_parent_count(&store, "commits"), 0);
}

#[test]
fn batch_write_and_delete() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let h1 = fs.commit_hash().unwrap();
    store.notes().commits().set(&h1, "old").unwrap();

    fs.write("a.txt", b"a", Default::default()).unwrap();
    let fs2 = store.branches().get("main").unwrap();
    let h2 = fs2.commit_hash().unwrap();

    let mut b = store.notes().commits().batch();
    b.delete(&h1).unwrap();
    b.set(&h2, "new").unwrap();
    b.commit().unwrap();

    assert!(!store.notes().commits().has(&h1).unwrap());
    assert_eq!(store.notes().commits().get(&h2).unwrap(), "new");
}

#[test]
fn batch_delete_missing_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let mut b = store.notes().commits().batch();
    b.delete(&hash).unwrap();
    assert!(b.commit().is_err());
}

#[test]
fn batch_overwrite_in_batch() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let mut b = store.notes().commits().batch();
    b.set(&hash, "first").unwrap();
    b.set(&hash, "second").unwrap();
    b.commit().unwrap();

    assert_eq!(store.notes().commits().get(&hash).unwrap(), "second");
}

#[test]
fn batch_noop_no_commit() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let b = store.notes().commits().batch();
    b.commit().unwrap();

    // No notes ref should exist
    assert_eq!(notes_chain_length(&store, "commits"), 0);
}

#[test]
fn batch_set_then_delete_same_hash_no_prior() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let mut b = store.notes().commits().batch();
    b.set(&hash, "will be deleted").unwrap();
    b.delete(&hash).unwrap();
    assert!(b.commit().is_err());
}

#[test]
fn batch_set_then_delete_same_hash_with_prior() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "original").unwrap();

    let mut b = store.notes().commits().batch();
    b.set(&hash, "overwritten").unwrap();
    b.delete(&hash).unwrap();
    b.commit().unwrap();

    assert!(!store.notes().commits().has(&hash).unwrap());
}

#[test]
fn batch_delete_then_set_same_hash() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    store.notes().commits().set(&hash, "original").unwrap();

    let mut b = store.notes().commits().batch();
    b.delete(&hash).unwrap();
    b.set(&hash, "restored").unwrap();
    b.commit().unwrap();

    assert_eq!(store.notes().commits().get(&hash).unwrap(), "restored");
}

#[test]
fn batch_validation() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    let mut b = store.notes().commits().batch();
    assert!(b.set("bad", "note").is_err());
}

// ---------------------------------------------------------------------------
// Mapping extras
// ---------------------------------------------------------------------------

#[test]
fn get_with_default() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();

    let result = store
        .notes()
        .commits()
        .get(&hash)
        .unwrap_or_else(|_| "default".to_string());
    assert_eq!(result, "default");

    store.notes().commits().set(&hash, "note").unwrap();
    assert_eq!(store.notes().commits().get(&hash).unwrap(), "note");
}

#[test]
fn is_empty_check() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");

    assert!(store.notes().commits().is_empty().unwrap());

    let fs = store.branches().get("main").unwrap();
    let hash = fs.commit_hash().unwrap();
    store.notes().commits().set(&hash, "note").unwrap();
    assert!(!store.notes().commits().is_empty().unwrap());
}

// ---------------------------------------------------------------------------
// Ref-based target resolution
// ---------------------------------------------------------------------------

#[test]
fn set_and_get_by_branch_name() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let ns = store.notes().commits();
    ns.set("main", "note for main").unwrap();
    assert_eq!(ns.get("main").unwrap(), "note for main");
}

#[test]
fn set_and_get_by_tag_name() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let snap = store.branches().get("main").unwrap();
    store.tags().set("v1.0", &snap).unwrap();
    let ns = store.notes().commits();
    ns.set("v1.0", "note for tag").unwrap();
    assert_eq!(ns.get("v1.0").unwrap(), "note for tag");
}

#[test]
fn ref_and_hash_access_same_note() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let snap = store.branches().get("main").unwrap();
    let hash = snap.commit_hash().unwrap();
    let ns = store.notes().commits();
    ns.set("main", "via ref").unwrap();
    assert_eq!(ns.get(&hash).unwrap(), "via ref");
}

#[test]
fn has_by_ref() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let ns = store.notes().commits();
    assert!(!ns.has("main").unwrap());
    ns.set("main", "note").unwrap();
    assert!(ns.has("main").unwrap());
}

#[test]
fn delete_by_ref() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let ns = store.notes().commits();
    ns.set("main", "note").unwrap();
    assert!(ns.has("main").unwrap());
    ns.delete("main").unwrap();
    assert!(!ns.has("main").unwrap());
}

#[test]
fn batch_with_ref_targets() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let snap = store.branches().get("main").unwrap();
    store.branches().set_and_get("dev", &snap).unwrap();
    // Advance main so the two branches have different tips
    snap.write("a.txt", b"a", Default::default()).unwrap();

    let mut batch = store.notes().commits().batch();
    batch.set("main", "note for main").unwrap();
    batch.set("dev", "note for dev").unwrap();
    batch.commit().unwrap();

    let ns = store.notes().commits();
    assert_eq!(ns.get("main").unwrap(), "note for main");
    assert_eq!(ns.get("dev").unwrap(), "note for dev");
}

#[test]
fn nonexistent_ref_raises() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let ns = store.notes().commits();
    assert!(ns.set("nonexistent", "note").is_err());
}
