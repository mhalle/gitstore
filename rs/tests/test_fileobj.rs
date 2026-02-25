mod common;

use std::io::Write;

use vost::*;

#[test]
fn fs_writer_write_all_and_close() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    let mut w = fs.writer("out.bin").unwrap();
    w.write_all(b"chunk1").unwrap();
    w.write_all(b"chunk2").unwrap();
    let fs2 = w.close().unwrap();
    assert_eq!(fs2.read("out.bin").unwrap(), b"chunk1chunk2");
}

#[test]
fn fs_writer_on_tag_returns_error() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    store.tags().set("v1", &fs).unwrap();
    let tag_fs = store.tags().get("v1").unwrap();
    assert!(tag_fs.writer("x.txt").is_err());
}

#[test]
fn fs_writer_write_after_close_returns_error() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    let mut w = fs.writer("out.bin").unwrap();
    w.write_all(b"data").unwrap();
    w.close().unwrap();
    assert!(w.write_all(b"more").is_err());
}

#[test]
fn fs_writer_double_close_is_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    let mut w = fs.writer("out.bin").unwrap();
    w.write_all(b"data").unwrap();
    let fs1 = w.close().unwrap();
    let fs2 = w.close().unwrap();
    assert_eq!(fs1.commit_hash().unwrap(), fs2.commit_hash().unwrap());
}

#[test]
fn fs_writer_drop_auto_commits() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    {
        let mut w = fs.writer("dropped.txt").unwrap();
        w.write_all(b"auto").unwrap();
        // drop without explicit close
    }

    let fs2 = store.branches().get("main").unwrap();
    assert_eq!(fs2.read_text("dropped.txt").unwrap(), "auto");
}

#[test]
fn batch_writer_write_and_close() {
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    let mut batch = fs.batch(Default::default());
    {
        let mut w = batch.writer("streamed.bin").unwrap();
        w.write_all(b"part1").unwrap();
        w.write_all(b"part2").unwrap();
        w.close().unwrap();
    }
    let fs2 = batch.commit().unwrap();
    assert_eq!(fs2.read("streamed.bin").unwrap(), b"part1part2");
}

#[test]
fn batch_writer_on_committed_batch_is_consumed() {
    // Rust's Batch::commit() takes ownership, so you simply can't call
    // writer() after commit — this is enforced at compile time.
    // We verify that writer() works fine on an open batch, though.
    let dir = tempfile::tempdir().unwrap();
    let store = common::create_store(dir.path(), "main");
    let fs = store.branches().get("main").unwrap();
    let fs = fs
        .write("seed.txt", b"seed", fs::WriteOptions::default())
        .unwrap();

    let mut batch = fs.batch(Default::default());
    {
        let mut w = batch.writer("ok.txt").unwrap();
        w.write_all(b"fine").unwrap();
        w.close().unwrap();
    }
    let fs2 = batch.commit().unwrap();
    assert_eq!(fs2.read_text("ok.txt").unwrap(), "fine");
}
