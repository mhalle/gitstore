# gitstore Documentation

gitstore is a versioned key-value filesystem backed by bare Git repositories. Every write produces a new commit, and old snapshots remain accessible forever.

## Quick install

```
pip install gitstore
```

Requires Python 3.10+ and [dulwich](https://www.dulwich.io/).

## Hello world

```python
from gitstore import GitStore

repo = GitStore.open("data.git")
fs = repo.branches["main"]
fs = fs.write("hello.txt", b"Hello, world!")
print(fs.read("hello.txt"))  # b'Hello, world!'
```

## Reference docs

- [Python API Reference](api.md) -- classes, methods, and data types
- [CLI Reference](cli.md) -- the `gitstore` command-line tool
- [Path Syntax](paths.md) -- how `ref:path` works across commands

## More

The top-level [README](../README.md) covers core concepts, concurrency safety, error handling, and development setup.
