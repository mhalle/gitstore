# vost Documentation

vost is a versioned key-value filesystem backed by bare Git repositories. Every write produces a new commit, and old snapshots remain accessible forever.

## Quick install

```
pip install vost
```

Requires Python 3.10+ and [dulwich](https://www.dulwich.io/).

## Hello world

```python
from vost import GitStore

repo = GitStore.open("data.git")
fs = repo.branches["main"]
fs = fs.write("hello.txt", b"Hello, world!")
print(fs.read("hello.txt"))  # b'Hello, world!'
```

## Reference docs

- [Python API Reference](api.md) -- classes, methods, and data types
- [CLI Reference](cli.md) -- the `vost` command-line tool
- [Path Syntax](paths.md) -- how `ref:path` works across commands

## More

The top-level [README](../README.md) covers core concepts, concurrency safety, error handling, and development setup.
