use std::path::Path;

use gitstore::*;

pub fn create_store(dir: &Path, branch: &str) -> GitStore {
    GitStore::open(dir.join("test.git"), OpenOptions {
        create: true,
        branch: Some(branch.into()),
        ..Default::default()
    })
    .unwrap()
}

#[allow(dead_code)]
pub fn store_with_files(dir: &Path) -> (GitStore, Fs) {
    let store = create_store(dir, "main");
    let fs = store.branches().get("main").unwrap();
    let mut batch = fs.batch(Default::default());
    batch.write("hello.txt", b"hello").unwrap();
    batch.write("dir/a.txt", b"aaa").unwrap();
    batch.write("dir/b.txt", b"bbb").unwrap();
    batch.commit().unwrap();
    let fs = store.branches().get("main").unwrap();
    (store, fs)
}
