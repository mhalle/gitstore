# Drop `_compat.py`: use dulwich `BaseRepo` directly

## Background

`_compat.py` exists to mimic pygit2's API so vost could switch backends by changing one import. vost now only uses dulwich. The compat layer wraps every dulwich type in a pygit2-shaped wrapper — `Oid`, `_WrappedCommit`, `_Reference`, `Repository`, etc. These wrappers add indirection without value.

Removing the compat layer lets vost accept any `BaseRepo` subclass directly — `Repo` (disk), `SqliteRepo` (SQLite), `MemoryRepo` (in-memory) — with no adapter code.

## What to delete

The entire `_compat.py` module. Specifically:

| Class/function | Replacement |
|---|---|
| `Oid` | `bytes` — dulwich's native 40-char hex SHA |
| `Signature` | `bytes` — e.g. `b"Alice <alice@example.com>"` |
| `Repository` | `BaseRepo` directly |
| `_WrappedObject/Blob/Tree/Commit` | `dulwich.objects.Blob/Tree/Commit` directly |
| `_TreeEntry` | `dulwich.objects.TreeEntry` (from `tree.iteritems()`) |
| `_Reference` | `repo.refs.set_if_equals()` directly |
| `_References` | `repo.refs` directly |
| `_wrap()` | Nothing — no wrapping needed |
| `init_repository()` | `Repo.init_bare()` or `SqliteRepo.init_bare()` |
| `GitError` | `dulwich.errors.*` or plain exceptions |
| `Commit` sentinel | `dulwich.objects.Commit` for isinstance checks |

## Translation guide

### Oid

Every `Oid(sha)` becomes just `sha`. Every `oid.raw` becomes just `sha`.

```python
# Before:
oid = pygit2.Oid(sha)
repo[oid]
oid.raw

# After:
sha  # bytes, e.g. b"abc123..."
repo.object_store[sha]
sha
```

Anywhere vost stores, compares, or passes an `Oid`, it becomes plain `bytes`.

### Object access

```python
# Before:
obj = repo[oid]                    # _WrappedCommit
obj.tree_id                        # Oid
obj.message                        # str (decoded)
obj.commit_time                    # int
obj.commit_time_offset             # int (minutes)
obj.author.name                    # str
obj.author.email                   # str
obj.parents                        # list[_WrappedCommit]
obj.type                           # int (type_num)
obj.peel(pygit2.Commit)            # follows tags

# After:
obj = repo.object_store[sha]       # dulwich Commit
obj.tree                            # bytes
obj.message                         # bytes (call .decode() where needed)
obj.commit_time                     # int
obj.commit_timezone                 # int (seconds, not minutes)
obj.author                          # bytes, e.g. b"Alice <alice@example.com>"
obj.parents                         # list[bytes] (SHAs)
obj.type_num                        # int
# For tag peeling, walk manually:
while isinstance(obj, Tag):
    obj = repo.object_store[obj.object[1]]
```

### Tree access

```python
# Before:
tree = repo[tree_oid]              # _WrappedTree
entry = tree["filename"]           # _TreeEntry with .name, .id, .filemode
for entry in tree:                 # iterates _TreeEntry

# After:
tree = repo.object_store[tree_sha] # dulwich Tree
mode, sha = tree[b"filename"]      # (int, bytes)
for entry in tree.iteritems():     # TreeEntry with .path, .sha, .mode
    entry.path                     # bytes
    entry.sha                      # bytes
    entry.mode                     # int
```

### Blob access

```python
# Before:
blob = repo[oid]                   # _WrappedBlob
blob.data                          # bytes

# After:
blob = repo.object_store[sha]      # dulwich Blob
blob.data                           # bytes
```

### Refs

```python
# Before:
ref = repo.references[ref_name]
ref.resolve().target                # Oid
ref.set_target(oid, message=msg, committer=committer)
repo.references.create(name, oid, message=msg, committer=committer)
repo.references.delete(name)
ref_name in repo.references
for name in repo.references: ...

# After:
sha = repo.refs[ref_bytes]          # bytes
repo.refs.set_if_equals(ref_bytes, old_sha, new_sha,
    committer=committer, message=msg)
repo.refs.set_if_equals(ref_bytes, None, new_sha,  # None = unconditional
    committer=committer, message=msg)
del repo.refs[ref_bytes]
ref_bytes in repo.refs
for ref_bytes in repo.refs.allkeys(): ...
```

Note: ref names and values are `bytes` in dulwich (`b"refs/heads/main"`), not `str`.

### Symbolic refs (HEAD)

```python
# Before:
repo.get_head_branch()              # str | None
repo.set_head_branch(name)

# After:
symrefs = repo.refs.get_symrefs()
target = symrefs.get(b"HEAD")       # b"refs/heads/main" | None
repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
```

### Creating objects

```python
# Before:
oid = repo.create_blob(data)
oid = repo.create_blob_fromdisk(path)
oid = repo.create_commit(ref, author, committer, message, tree_oid, parent_oids)
oid = repo.create_tag(name, target_oid, target_type, tagger, message)

# After:
blob = Blob.from_string(data)
repo.object_store.add_object(blob)
sha = blob.id

c = Commit()
c.tree = tree_sha
c.parents = [parent_sha]
c.author = c.committer = b"Alice <alice@example.com>"
c.author_time = c.commit_time = int(time.time())
c.author_timezone = c.commit_timezone = 0
c.message = message if isinstance(message, bytes) else message.encode()
c.encoding = b"UTF-8"
repo.object_store.add_object(c)
sha = c.id
if ref_bytes is not None:
    repo.refs[ref_bytes] = c.id
```

### TreeBuilder

Keep `TreeBuilder` as a helper — it's useful and backend-agnostic. Just change it to accept `BaseRepo`:

```python
class TreeBuilder:
    def __init__(self, repo: BaseRepo, base_tree=None):
        self._repo = repo
        self._entries = {}
        if base_tree is not None:
            for entry in base_tree.iteritems():
                self._entries[entry.path] = (entry.mode, entry.sha)

    def insert(self, name: str, sha: bytes, mode: int):
        self._entries[name.encode()] = (mode, sha)

    def remove(self, name: str):
        del self._entries[name.encode()]

    def write(self) -> bytes:
        tree = Tree()
        for name_bytes, (mode, sha) in sorted(self._entries.items()):
            tree.add(name_bytes, mode, sha)
        self._repo.object_store.add_object(tree)
        return tree.id
```

### Signature

Replace the `Signature` class with a helper function or just inline the format:

```python
# Before:
sig = pygit2.Signature(name, email)
sig._identity  # b"Name <email>"
sig.name        # str
sig.email       # str

# After — for dulwich commit fields:
identity = f"{name} <{email}>".encode()

# For display, parse when needed:
name, _, email_part = identity.decode().partition(" <")
email = email_part.rstrip(">")
```

### Transport / mirror

```python
# Before:
repo.diff_refs(url, direction)
repo.mirror_push(url)
repo.mirror_fetch(url)

# After — move these to standalone functions or GitStore methods:
# They only use repo.get_refs(), repo.refs, repo.object_store.generate_pack_data(),
# and client.fetch(path, repo). All on BaseRepo's interface.
```

### Reflog

Already migrated. Uses `repo.refs.set_if_equals(..., message=msg)` for writing and `repo.read_reflog(ref_bytes)` for reading. Both work on any `BaseRepo` that wires a logger to its refs container.

## GitStore changes

```python
# Before:
class GitStore:
    def __init__(self, pygit2_repo: pygit2.Repository, ...):
        self._repo = pygit2_repo  # compat wrapper

    @classmethod
    def open(cls, path, ...):
        repo = pygit2.Repository(str(path))
        # or
        repo = pygit2.init_repository(str(path))

# After:
class GitStore:
    def __init__(self, repo: BaseRepo, ...):
        self._repo = repo  # any dulwich BaseRepo

    @classmethod
    def open(cls, path, ...):
        repo = Repo(str(path))      # disk
        # or
        repo = SqliteRepo(str(path)) # sqlite
```

## `_lock.py` fix

`repo_lock(repo.path)` assumes path is a directory. For SqliteRepo, `path` is a `.db` file:

```python
if os.path.isdir(repo_path):
    lock_path = os.path.join(repo_path, "vost.lock")
else:
    lock_path = repo_path + ".lock"
```

## `_objsize.py` fix

`ObjectSizer` reads pack/loose files from disk. Falls back to `get_object_size()` for non-disk stores:

```python
if hasattr(self._store, 'path') and os.path.isdir(self._store.path):
    return self._read_loose_header(sha_hex)
return self._store.get_object_size(sha_hex)
```

## Encoding convention

dulwich uses `bytes` throughout. gitstore's public API uses `str`. The boundary is at the `FS` / `GitStore` / `RefDict` level — decode at the public API surface, keep `bytes` internally. This is already mostly the case; the compat layer just re-encodes things unnecessarily.

## Migration order

1. Replace `Oid` with plain `bytes` throughout (mechanical find-replace)
2. Replace wrapped objects with direct dulwich object access
3. Replace `_References`/`_Reference` with direct `repo.refs` calls
4. Replace `Repository` with `BaseRepo`
5. Move transport helpers (`diff_refs`, `mirror_push`, `mirror_fetch`) to standalone functions
6. Delete `_compat.py`
7. Fix `_lock.py` and `_objsize.py`

Each step is independently testable — run the full test suite after each.
