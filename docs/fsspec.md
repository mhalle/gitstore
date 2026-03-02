# fsspec Integration

vost provides an [fsspec](https://filesystem-spec.readthedocs.io/) filesystem adapter, letting pandas, xarray, dask, and any fsspec-aware tool read from (and write to) vost repos transparently.

## Install

```
pip install vost[fsspec]
```

## Usage with pandas

```python
import pandas as pd

# Read from a branch
df = pd.read_csv("vost:///data.csv", storage_options={
    "repo": "lab.git",
    "ref": "main",
})

# Read an older version (1 commit back)
df_old = pd.read_csv("vost:///data.csv", storage_options={
    "repo": "lab.git",
    "ref": "main",
    "back": 1,
})

# Read from a tag
df_release = pd.read_csv("vost:///data.csv", storage_options={
    "repo": "lab.git",
    "ref": "v1.0",
})

# Write back
df.to_csv("vost:///output.csv", storage_options={
    "repo": "lab.git",
    "ref": "main",
}, index=False)
```

## Direct usage

```python
import fsspec

fs = fsspec.filesystem("vost", repo="lab.git", ref="main")

# Read
data = fs.cat("/data.csv")
with fs.open("/config.json", "rb") as f:
    config = json.load(f)

# Partial read (byte range)
header = fs.cat_file("/big.bin", start=0, end=1024)

# List
fs.ls("/")                   # ['/data.csv', '/src']
fs.ls("/src", detail=True)   # [{'name': '/src/app.py', 'type': 'file', ...}]

# Search
fs.glob("/src/**/*.py")      # ['/src/app.py', '/src/lib/util.py']

# Write (each call creates a new commit)
fs.pipe_file("/new.txt", b"content")
with fs.open("/output.bin", "wb") as f:
    f.write(b"data")

# Remove
fs.rm("/old.txt")
fs.rm("/old_dir", recursive=True)
```

## Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `repo` | `str` | *(required)* | Path to the bare git repository |
| `ref` | `str` | `None` | Branch name, tag name, or commit SHA. Defaults to the repo's current (HEAD) branch |
| `back` | `int` | `0` | Number of ancestor commits to walk back (time-travel) |
| `readonly` | `bool` | `False` | Block all write operations, even on branches |

## Read-only mode

Pass `readonly=True` to prevent accidental writes:

```python
fs = fsspec.filesystem("vost", repo="lab.git", ref="main", readonly=True)
fs.cat("/data.csv")           # works
fs.pipe_file("/x", b"nope")   # raises PermissionError
```

Tags and detached commits (bare SHA refs) are always read-only regardless of this flag.

## Write semantics

Each write operation (`pipe_file`, `open("wb")`, `rm`) creates a new git commit and advances the filesystem's internal snapshot. This matches vost's core design where every mutation is a commit.

`mkdir` and `mkdirs` are no-ops — git does not track empty directories.

## Limitations

- **No append mode** — only `"rb"` and `"wb"` are supported.
- **No concurrent writers** — the adapter holds a single FS snapshot. Concurrent write calls from different threads or processes may raise `StaleSnapshotError`.
- **Python only** — fsspec is a Python abstraction. Other languages have analogous ecosystems (Rust: `object_store`, JVM: Hadoop `FileSystem`, C++: Arrow `FileSystem`) but these are not currently implemented.
