# vost (Rust)

A versioned filesystem backed by a bare git repository.

This is the Rust port of [vost](https://github.com/mhalle/vost), using [gitoxide (gix)](https://github.com/GitoxideLabs/gitoxide) as the git backend.

## Usage

```rust
use gitstore::{GitStore, OpenOptions};

let store = GitStore::open("my-repo.git", OpenOptions {
    create: true,
    branch: Some("main".to_string()),
    ..Default::default()
})?;

let fs = store.branches().get("main")?;
fs.write("hello.txt", b"world", Default::default())?;

let content = fs.read_text("hello.txt")?;
assert_eq!(content, "world");
```

## License

Apache-2.0 — see [LICENSE](../LICENSE) for details.
