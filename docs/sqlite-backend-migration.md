# Use dulwich's reflog instead of direct file I/O

## Problem

vost bypasses dulwich's reflog machinery. It writes reflog entries by manually appending to filesystem files (`_write_reflog_entry` in `_compat.py`), and reads them by opening those files directly (`RefDict.reflog` in `repo.py`, `FS.redo` in `fs.py`).

dulwich already handles all of this. `dulwich.repo.Repo` has `_write_reflog()` and `read_reflog()` methods. Its `DiskRefsContainer` calls a `logger` callback on every ref mutation (`set_if_equals`, `add_if_new`, `remove_if_equals`) when a `message` is provided. The logger is wired to `Repo._write_reflog` at init time:

```python
# dulwich.repo.Repo.__init__:
self.refs = DiskRefsContainer(
    self.commondir(), self._controldir, logger=self._write_reflog
)
```

vost currently sidesteps this by setting refs via `self._refs[name] = sha` (which calls `set_if_equals` with `message=None`, so no reflog is written), then manually writing the reflog entry afterward. The fix is to pass the message through the ref mutation call so dulwich writes the reflog itself.

## Changes

### 1. `_compat.py` — Writing: pass message to `set_if_equals` instead of manual file I/O

Delete `_write_reflog_entry()` (lines 200-216) entirely.

**`_Reference.set_target()`** (line 235) — currently:
```python
def set_target(self, oid, message=None, committer=None):
    try:
        old_sha = self._refs[self._name]
    except KeyError:
        old_sha = _ZERO_SHA
    self._refs[self._name] = oid.raw
    if message is None:
        message = b"update ref"
    if committer is None:
        committer = b"vost <vost@localhost>"
    _write_reflog_entry(
        self._repo.path, self._name,
        old_sha, oid.raw,
        committer, message
    )
```

Replace with:
```python
def set_target(self, oid, message=None, committer=None):
    try:
        old_sha = self._refs[self._name]
    except KeyError:
        old_sha = None
    if message is None:
        message = b"update ref"
    if committer is None:
        committer = b"vost <vost@localhost>"
    self._refs.set_if_equals(
        self._name, old_sha, oid.raw,
        committer=committer, message=message,
    )
```

`DiskRefsContainer.set_if_equals` accepts `committer`, `timestamp`, `timezone`, and `message`. When `message` is not None, its internal `_log()` method calls the logger callback (`Repo._write_reflog`), which writes the reflog file.

**`_References.create()`** (line 278) — currently:
```python
def create(self, name, oid, message=None, committer=None):
    ref_bytes = name.encode() if isinstance(name, str) else name
    self._refs[ref_bytes] = oid.raw
    if message is None:
        message = b"create ref"
    if committer is None:
        committer = b"vost <vost@localhost>"
    _write_reflog_entry(
        self._dulwich_repo.path, ref_bytes,
        _ZERO_SHA, oid.raw,
        committer, message
    )
```

Replace with:
```python
def create(self, name, oid, message=None, committer=None):
    ref_bytes = name.encode() if isinstance(name, str) else name
    if message is None:
        message = b"create ref"
    if committer is None:
        committer = b"vost <vost@localhost>"
    self._refs.set_if_equals(
        ref_bytes, None, oid.raw,
        committer=committer, message=message,
    )
```

Passing `old_ref=None` makes it an unconditional set (same as `__setitem__`), but now with a message so the reflog is written.

After both changes, delete the `_write_reflog_entry` function and its `_format_reflog_line` import.

### 2. `repo.py` — Reading: use `Repo.read_reflog()` instead of file I/O

**`RefDict.reflog()`** (line 255) — currently:
```python
def reflog(self, name):
    from dulwich import reflog as dreflog
    if self._is_tags:
        raise ValueError("Tags do not have reflog")
    ref_name = self._ref_name(name)
    if ref_name not in self._store._repo.references:
        raise KeyError(name)
    reflog_path = os.path.join(
        self._store._repo.path,
        "logs", "refs", "heads", name
    )
    if not os.path.exists(reflog_path):
        raise FileNotFoundError(f"No reflog found for branch {name!r}")
    with open(reflog_path, 'rb') as f:
        entries = []
        for entry in dreflog.read_reflog(f):
            entries.append(ReflogEntry(
                old_sha=entry.old_sha.decode(),
                new_sha=entry.new_sha.decode(),
                committer=entry.committer.decode(),
                timestamp=entry.timestamp,
                message=entry.message.decode(),
            ))
        return entries
```

Replace with:
```python
def reflog(self, name):
    if self._is_tags:
        raise ValueError("Tags do not have reflog")
    ref_name = self._ref_name(name)
    if ref_name not in self._store._repo.references:
        raise KeyError(name)
    ref_bytes = ref_name.encode() if isinstance(ref_name, str) else ref_name
    entries = list(self._store._repo._repo.read_reflog(ref_bytes))
    if not entries:
        raise FileNotFoundError(f"No reflog found for branch {name!r}")
    return [
        ReflogEntry(
            old_sha=e.old_sha.decode(),
            new_sha=e.new_sha.decode(),
            committer=e.committer.decode(),
            timestamp=e.timestamp,
            message=e.message.decode(),
        )
        for e in entries
    ]
```

`self._store._repo` is the `_compat.Repository` wrapper. `self._store._repo._repo` is the underlying `dulwich.repo.Repo`. Its `read_reflog(ref_bytes)` yields `dulwich.reflog.Entry` objects and handles `FileNotFoundError` internally (returns empty generator when no reflog file exists).

### 3. `fs.py` — Reading: same change in `FS.redo()`

**`FS.redo()`** (line 865) — currently:
```python
from dulwich import reflog as dreflog
reflog_path = os.path.join(
    self._store._repo.path,
    "logs", "refs", "heads", self._branch
)
if not os.path.exists(reflog_path):
    raise ValueError(f"No reflog found for branch {self._branch!r}")
with open(reflog_path, 'rb') as f:
    entries = list(dreflog.read_reflog(f))
```

Replace with:
```python
ref_bytes = f"refs/heads/{self._branch}".encode()
entries = list(self._store._repo._repo.read_reflog(ref_bytes))
if not entries:
    raise ValueError(f"No reflog found for branch {self._branch!r}")
```

The rest of `redo()` uses `entries[i].old_sha` and `entries[i].new_sha` — these work identically since `Repo.read_reflog()` yields the same `dulwich.reflog.Entry` objects.

## What gets deleted

- `_write_reflog_entry()` function in `_compat.py` (lines 200-216)
- `from dulwich.reflog import format_reflog_line as _format_reflog_line` import in `_compat.py` (line 18)
- `from dulwich import reflog as dreflog` imports in `repo.py` and `fs.py`
- All `os.path.join(..., "logs", ...)` reflog path construction
- All `open(reflog_path, 'rb')` file reads for reflogs

## Why this matters

This change makes vost's reflog handling backend-agnostic. `Repo.read_reflog()` and `DiskRefsContainer._log()` are dulwich's internal contracts. Any dulwich `BaseRepo` subclass that implements `read_reflog()` and wires a logger to its refs container will work — including `dulwich-sqlite`'s `SqliteRepo`, which stores reflogs in a database table and already implements both.
