# TypeScript API Reference

```typescript
import {
  GitStore, FS, Batch, FsWriter, BatchWriter, RefDict,
  NoteDict, NoteNamespace, NotesBatch, ExcludeFilter,
  FileType, WriteEntry, StatResult, WalkEntry, FileEntry,
  ChangeReport, ChangeAction, ChangeError,
  MirrorDiff, RefChange, ReflogEntry, Signature, CommitInfo,
  StaleSnapshotError, retryWrite, resolveCredentials, diskGlob,
} from '@mhalle/vost';
```

---

## GitStore

Opens or creates a bare Git repository.

### `GitStore.open(path, options)`

```typescript
const store = await GitStore.open('/path/to/repo.git', {
  fs,                         // required — Node.js fs module
  create: true,               // create if missing (default: true)
  branch: 'main',             // default branch (default: 'main', null for branchless)
  author: 'vost',             // commit author name
  email: 'vost@localhost',    // commit author email
});
```

Returns `Promise<GitStore>`.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `branches` | `RefDict` | Branch access (read/write) |
| `tags` | `RefDict` | Tag access (read-only snapshots) |
| `notes` | `NoteDict` | Git notes namespaces |

### `store.backup(url, options?)`

Push all refs to a remote as an exact mirror.

```typescript
const diff = await store.backup('https://github.com/user/repo.git', {
  http,                       // isomorphic-git http client (optional)
  dryRun: false,              // preview only (default: false)
  onAuth: () => ({ username, password }),  // auth callback (optional)
});
```

Returns `Promise<MirrorDiff>`.

### `store.restore(url, options?)`

Fetch all refs from a remote, overwriting local state.

Same options as `backup()`. Returns `Promise<MirrorDiff>`.

---

## FS (Snapshot)

An immutable snapshot of a committed tree. Reading methods never mutate state. Writing methods return a new `FS` pointing at the new commit.

### Sync properties

| Property | Type | Description |
|----------|------|-------------|
| `commitHash` | `string` | 40-char hex commit SHA |
| `refName` | `string \| null` | Branch or tag name, or `null` for detached |
| `writable` | `boolean` | `true` for branches, `false` for tags/detached |
| `treeHash` | `string` | 40-char hex root tree SHA |
| `changes` | `ChangeReport \| null` | Changes from the last operation |

### Commit metadata

These require reading the commit object and return promises:

```typescript
await fs.getMessage()       // string — commit message
await fs.getTime()          // Date — commit timestamp (timezone-aware)
await fs.getAuthorName()    // string
await fs.getAuthorEmail()   // string
await fs.getCommitInfo()    // CommitInfo — all four fields at once
```

---

### Reading files

#### `fs.read(path, options?)`

Read file contents as bytes.

```typescript
const data: Uint8Array = await fs.read('file.bin');
const chunk: Uint8Array = await fs.read('file.bin', { offset: 100, size: 50 });
```

Throws `FileNotFoundError` if the path does not exist, `IsADirectoryError` if it is a directory.

#### `fs.readText(path, encoding?)`

Read file contents as a UTF-8 string.

```typescript
const text: string = await fs.readText('config.json');
```

#### `fs.readByHash(hash, options?)`

Read a blob directly by its SHA hash, bypassing the tree walk.

```typescript
const data: Uint8Array = await fs.readByHash(sha, { offset: 0, size: 1024 });
```

#### `fs.readlink(path)`

Read the target of a symlink entry.

```typescript
const target: string = await fs.readlink('link');
```

---

### Querying files

#### `fs.exists(path)`

```typescript
const exists: boolean = await fs.exists('file.txt');
```

#### `fs.isDir(path)`

```typescript
const isDir: boolean = await fs.isDir('src');
```

#### `fs.fileType(path)`

```typescript
const ft: FileType = await fs.fileType('script.sh');  // FileType.EXECUTABLE
```

Returns one of `FileType.BLOB`, `FileType.EXECUTABLE`, `FileType.LINK`, or `FileType.TREE`.

#### `fs.size(path)`

```typescript
const bytes: number = await fs.size('data.bin');
```

#### `fs.objectHash(path)`

```typescript
const sha: string = await fs.objectHash('file.txt');  // 40-char hex
```

#### `fs.stat(path?)`

FUSE-friendly getattr returning all metadata in one call.

```typescript
const st: StatResult = await fs.stat('file.txt');
// st.mode      — raw mode as integer (e.g. 0o100644)
// st.fileType  — FileType enum
// st.size      — bytes (0 for directories)
// st.hash      — 40-char hex SHA
// st.nlink     — 1 for files, 2 + subdirectory count for directories
// st.mtime     — POSIX epoch seconds
```

---

### Listing and search

#### `fs.ls(path?)`

List entry names in a directory.

```typescript
const names: string[] = await fs.ls();          // root
const names: string[] = await fs.ls('src');     // subdirectory
```

Throws `NotADirectoryError` if the path is a file.

#### `fs.listdir(path?)`

List entries with metadata.

```typescript
const entries: WalkEntry[] = await fs.listdir('src');
for (const e of entries) {
  console.log(e.name, e.oid, e.mode);
}
```

#### `fs.walk(path?)`

Recursively walk the tree, yielding `[dirpath, dirnames, files]` tuples (like Python's `os.walk`).

```typescript
for await (const [dirpath, dirnames, files] of fs.walk()) {
  for (const entry of files) {
    console.log(`${dirpath}/${entry.name}`, entry.mode);
  }
}
```

- `dirpath` — `string`, relative directory path (empty string for root)
- `dirnames` — `string[]`, subdirectory names
- `files` — `WalkEntry[]`, file entries in this directory

#### `fs.glob(pattern)`

Return sorted list of paths matching a glob pattern.

```typescript
const matches: string[] = await fs.glob('**/*.ts');
const matches: string[] = await fs.glob('src/**/*.{ts,tsx}');
```

Supports `*`, `?`, `**` (recursive), `{a,b}` (alternation), `[abc]` (character class). Dotfiles (names starting with `.`) are only matched when the pattern explicitly starts with `.`.

#### `fs.iglob(pattern)`

Async iterator over matching paths (unordered, may be faster for large trees).

```typescript
for await (const path of fs.iglob('**/*.json')) {
  console.log(path);
}
```

---

### Writing files

All write methods auto-commit and return a new `FS`. The original snapshot is never mutated.

#### `fs.write(path, data, options?)`

Write binary data.

```typescript
const next = await fs.write('image.png', rawBytes);
const next = await fs.write('image.png', rawBytes, { message: 'Add image' });
```

Options: `message?: string`, `mode?: FileType`.

#### `fs.writeText(path, text, options?)`

Write a string as UTF-8.

```typescript
const next = await fs.writeText('config.json', '{"key": "value"}');
const next = await fs.writeText('run.sh', '#!/bin/sh\n', { mode: FileType.EXECUTABLE });
```

Options: `message?: string`, `mode?: FileType`, `encoding?: string`.

#### `fs.writeFromFile(path, localPath, options?)`

Write from a local file on disk.

```typescript
const next = await fs.writeFromFile('data.bin', '/path/to/local/data.bin');
```

Options: `message?: string`, `mode?: FileType`.

#### `fs.writeSymlink(path, target, options?)`

Create a symbolic link entry.

```typescript
const next = await fs.writeSymlink('link', 'target-file.txt');
```

Options: `message?: string`.

#### `fs.remove(sources, options?)`

Delete files or directories.

```typescript
const next = await fs.remove('old.txt');
const next = await fs.remove(['dir1', 'dir2'], { recursive: true });
```

Options: `recursive?: boolean`, `dryRun?: boolean`, `message?: string`.

#### `fs.move(sources, dest, options?)`

Move or rename files within the repository.

```typescript
const next = await fs.move(['old.txt'], 'new.txt');
const next = await fs.move(['a.txt', 'b.txt'], 'archive/');
```

Options: `dryRun?: boolean`, `message?: string`.

---

### Buffered writes

#### `fs.writer(path, mode?)`

Returns an `FsWriter` for streaming data into a single file. The write is committed when `close()` is called.

```typescript
const w = fs.writer('large-file.bin');
await w.write(chunk1);
await w.write(chunk2);
await w.close();
const next: FS = w.fs;  // new snapshot after commit
```

Pass `'w'` as mode for text (string) writes.

---

### Batch writes

#### `fs.batch(options?)`

Returns a `Batch` for accumulating multiple writes into a single commit.

```typescript
const batch = fs.batch({ message: 'Bulk import' });
await batch.write('a.txt', new TextEncoder().encode('aaa'));
await batch.writeText('b.txt', 'bbb');
await batch.writeFromFile('c.bin', '/path/to/c.bin');
await batch.writeSymlink('link', 'a.txt');
await batch.remove('old.txt');
const next: FS = await batch.commit();
```

If an error occurs before `commit()`, nothing is committed.

Options: `message?: string`, `operation?: string`.

---

### Atomic apply

#### `fs.apply(writes?, removes?, options?)`

Apply multiple writes and removes in a single commit without creating a batch.

```typescript
const next = await fs.apply(
  {
    'config.json': new TextEncoder().encode('{"v": 2}'),
    'script.sh': { data: new TextEncoder().encode('#!/bin/sh\n'), mode: FileType.EXECUTABLE },
    'link': { target: 'config.json' },
  },
  ['old.txt'],
  { message: 'Update config' },
);
```

- `writes` — `Record<string, Uint8Array | string | WriteEntry>` or `undefined`
- `removes` — `string | string[] | Set<string>` or `undefined`
- Options: `message?: string`, `operation?: string`.

---

### Copy and sync

#### `fs.copyIn(sources, dest, options?)`

Copy files from disk into the repository (like `rsync` disk-to-repo).

```typescript
const next = await fs.copyIn(['./data/'], 'backup');
const next = await fs.copyIn(['./src/*.py'], 'backup', { dryRun: true });
```

Options: `dryRun`, `followSymlinks`, `message`, `mode`, `ignoreExisting`, `delete`, `ignoreErrors`, `checksum`, `exclude`.

Trailing `/` on a source copies **contents** (not the directory itself).

#### `fs.copyOut(sources, dest, options?)`

Copy files from the repository to disk.

```typescript
await fs.copyOut(['docs'], './local-docs');
await fs.copyOut(['/'], './full-export');
```

Options: `dryRun`, `ignoreExisting`, `delete`, `ignoreErrors`, `checksum`.

#### `fs.syncIn(localPath, repoPath, options?)`

Make a repo directory match a local directory exactly (including deletes).

```typescript
const next = await fs.syncIn('./local', 'data');
```

Options: `dryRun`, `message`, `ignoreErrors`, `checksum`, `exclude`.

#### `fs.syncOut(repoPath, localPath, options?)`

Make a local directory match a repo directory exactly.

```typescript
await fs.syncOut('data', './local');
```

Options: `dryRun`, `ignoreErrors`, `checksum`.

#### `fs.copyFromRef(sourceFs, sources, dest?, options?)`

Copy files from another branch/tag into this snapshot (atomic, no disk I/O).

```typescript
const main = await store.branches.get('main');
let dev = await store.branches.get('dev');
dev = await dev.copyFromRef(main, ['config'], 'imported');
dev = await dev.copyFromRef(main, ['config/'], 'imported');  // contents mode
```

Options: `dryRun`, `message`.

---

### History and navigation

#### `fs.parent()`

```typescript
const prev: FS | null = await fs.parent();
```

#### `fs.back(n)`

```typescript
const ancestor: FS = await fs.back(3);  // 3 commits back
```

Throws if there aren't enough ancestors.

#### `fs.log(options?)`

Async iterator over commit history.

```typescript
for await (const entry of fs.log()) {
  console.log(entry.commitHash, await entry.getMessage());
}

// File history
for await (const entry of fs.log({ path: 'config.json' })) { ... }

// Message filter
for await (const entry of fs.log({ match: 'deploy*' })) { ... }

// Date filter
for await (const entry of fs.log({ before: cutoffDate })) { ... }
```

#### `fs.undo()`

Move the branch back one commit. Returns the new `FS`.

```typescript
const prev = await fs.undo();
```

#### `fs.redo()`

Move the branch forward one reflog step (undoes an undo). Returns the new `FS`.

```typescript
const restored = await fs.redo();
```

---

### Lifecycle

#### `fs.close()`

Release cached internal state. Idempotent. After closing, the `FS` can still be used but will re-create internal caches as needed.

---

## Batch

Accumulates multiple writes into a single commit.

### Methods

| Method | Description |
|--------|-------------|
| `write(path, data, opts?)` | Stage a binary write |
| `writeText(path, text, opts?)` | Stage a text write |
| `writeFromFile(path, localPath, opts?)` | Stage a write from disk |
| `writeSymlink(path, target)` | Stage a symlink |
| `remove(path)` | Stage a deletion |
| `writer(path)` | Return a `BatchWriter` for streaming |
| `commit()` | Commit all staged changes, returns `Promise<FS>` |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `fs` | `FS \| null` | Resulting snapshot after `commit()` (null until committed) |

---

## FsWriter / BatchWriter

Buffered writers for streaming data into files.

```typescript
// Standalone (commits on close)
const w = fs.writer('file.bin');
await w.write(chunk);
await w.close();
const next = w.fs;

// Inside a batch (staged on close)
const batch = fs.batch();
const bw = batch.writer('file.bin');
await bw.write(chunk);
await bw.close();
const result = await batch.commit();
```

| Property/Method | Type | Description |
|-----------------|------|-------------|
| `write(data)` | `Promise<void>` | Buffer bytes (`Uint8Array`) or string |
| `close()` | `Promise<void>` | Flush and commit/stage |
| `closed` | `boolean` | Whether the writer has been closed |
| `fs` | `FS \| null` | (FsWriter only) Resulting snapshot after close |

---

## RefDict

Dict-like access to branches or tags. Supports async iteration.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get(name)` | `Promise<FS>` | Get snapshot for ref |
| `set(name, fs)` | `Promise<void>` | Point ref at an FS commit |
| `setAndGet(name, fs)` | `Promise<FS>` | Set ref and return new writable FS |
| `delete(name)` | `Promise<void>` | Delete ref |
| `has(name)` | `Promise<boolean>` | Check existence |
| `list()` | `Promise<string[]>` | List all ref names |

### Branch-only methods

These throw on tag RefDicts:

| Method | Returns | Description |
|--------|---------|-------------|
| `getCurrentName()` | `Promise<string \| null>` | Current branch name |
| `getCurrent()` | `Promise<FS \| null>` | Current branch FS |
| `setCurrent(name)` | `Promise<void>` | Set HEAD to branch |
| `reflog(name)` | `Promise<ReflogEntry[]>` | Branch reflog |

### Async iteration

```typescript
for await (const name of store.branches) {
  console.log(name);
}
```

---

## NoteDict

Access to git notes namespaces.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `commits` | `NoteNamespace` | Default namespace (`refs/notes/commits`) |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `namespace(name)` | `NoteNamespace` | Get or create a named namespace |

---

## NoteNamespace

Read and write notes in a single namespace. Targets can be 40-char hex commit hashes, branch names, or tag names.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get(target)` | `Promise<string>` | Get note text |
| `set(target, text)` | `Promise<void>` | Set note |
| `delete(target)` | `Promise<void>` | Delete note |
| `has(target)` | `Promise<boolean>` | Check if note exists |
| `list()` | `Promise<string[]>` | List commit hashes with notes |
| `batch()` | `NotesBatch` | Create a batch for atomic updates |
| `getForCurrentBranch()` | `Promise<string>` | Get note for HEAD commit |
| `setForCurrentBranch(text)` | `Promise<void>` | Set note for HEAD commit |

---

## NotesBatch

Atomic batch of note writes.

| Method | Returns | Description |
|--------|---------|-------------|
| `set(target, text)` | `Promise<void>` | Stage a note write |
| `delete(target)` | `Promise<void>` | Stage a note deletion |
| `commit()` | `Promise<void>` | Commit all staged changes |

---

## ExcludeFilter

Gitignore-style pattern matching for `copyIn` and `syncIn` operations.

```typescript
const filter = new ExcludeFilter({ patterns: ['*.log', 'node_modules/'] });
filter.addPatterns(['*.tmp']);
await filter.loadFromFile('.gitignore');

filter.isExcluded('debug.log');           // true
filter.isExcluded('src/app.ts');          // false
filter.active;                            // true (has patterns)
```

### Constructor options

| Option | Type | Description |
|--------|------|-------------|
| `patterns` | `string[]` | Initial gitignore-style patterns |
| `excludeFrom` | `string` | Path to a file containing patterns (one per line) |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `addPatterns(patterns)` | `void` | Add more patterns |
| `loadFromFile(path)` | `Promise<void>` | Load patterns from a file |
| `isExcluded(path, isDir?)` | `boolean` | Test if path should be excluded |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `active` | `boolean` | Whether any patterns are configured |

---

## Error classes

All errors extend `GitStoreError`, which extends `Error`.

| Class | Code | When |
|-------|------|------|
| `FileNotFoundError` | `ENOENT` | Path not found in tree; missing local file |
| `IsADirectoryError` | `EISDIR` | `read()` on a directory |
| `NotADirectoryError` | `ENOTDIR` | `ls()`/`walk()` on a file |
| `PermissionError` | `EPERM` | Writing to a read-only (tag) snapshot |
| `KeyNotFoundError` | — | Accessing a missing branch or tag |
| `KeyExistsError` | — | Creating a tag that already exists |
| `InvalidRefNameError` | — | Invalid characters in ref name |
| `InvalidPathError` | — | Empty segments, `..`, or invalid path |
| `BatchClosedError` | — | Using a batch after `commit()` |
| `StaleSnapshotError` | — | Branch advanced since snapshot was obtained |

---

## Utility functions

### `retryWrite(store, branchName, path, data, options?)`

Retry a single-file write with exponential backoff on `StaleSnapshotError`.

```typescript
const next = await retryWrite(store, 'main', 'counter.txt', data);
```

### `resolveCredentials(url)`

Inject git credentials into an HTTPS URL. Tries `git credential fill`, then `gh auth token`.

```typescript
const authedUrl: string = await resolveCredentials('https://github.com/user/repo.git');
```

### `diskGlob(pattern, options?)`

Glob-match files on the local filesystem (dotfile-aware).

```typescript
const files: string[] = await diskGlob('./data/**/*.csv');
```

### `normalizePath(path)`

Normalize a repository path (forward slashes, reject `..` and `.`).

### `validateRefName(name)`

Validate a branch/tag name (reject colons, spaces, control characters).

---

## Data types

### FileType

```typescript
enum FileType {
  BLOB = 'blob',              // regular file (mode 100644)
  EXECUTABLE = 'executable',  // executable file (mode 100755)
  LINK = 'link',              // symbolic link (mode 120000)
  TREE = 'tree',              // directory (mode 040000)
}
```

### Mode constants

```typescript
MODE_BLOB      = '100644'
MODE_BLOB_EXEC = '100755'
MODE_LINK      = '120000'
MODE_TREE      = '040000'
```

### Mode conversion functions

```typescript
fileTypeFromMode(mode: string): FileType
fileModeFromType(ft: FileType): string
```

### WalkEntry

```typescript
interface WalkEntry {
  name: string;     // entry basename
  oid: string;      // 40-char hex SHA
  mode: string;     // git filemode string ('100644', etc.)
}
```

### StatResult

```typescript
interface StatResult {
  mode: number;        // raw mode as integer (e.g. 0o100644)
  fileType: FileType;  // BLOB, EXECUTABLE, LINK, or TREE
  size: number;        // bytes (0 for directories)
  hash: string;        // 40-char hex SHA
  nlink: number;       // 1 for files, 2 + subdirectory count for dirs
  mtime: number;       // POSIX epoch seconds
}
```

### WriteEntry

```typescript
interface WriteEntry {
  data?: Uint8Array | string;   // file content (mutually exclusive with target)
  mode?: FileType | string;     // file mode override
  target?: string;              // symlink target (mutually exclusive with data)
}
```

### FileEntry

```typescript
interface FileEntry {
  path: string;       // repo-relative path
  type: FileType;     // file type
  src?: string;       // source path (for copy operations)
}
```

### ChangeReport

```typescript
interface ChangeReport {
  add: FileEntry[];
  update: FileEntry[];
  delete: FileEntry[];
  errors: ChangeError[];
  warnings: ChangeError[];
}
```

Helper functions:
- `emptyChangeReport()` — create an empty report
- `changeReportInSync(cr)` — true if no changes
- `changeReportTotal(cr)` — count of add + update + delete
- `changeReportActions(cr)` — flat array of `ChangeAction` objects

### ChangeAction

```typescript
interface ChangeAction {
  path: string;
  action: 'add' | 'update' | 'delete';
}
```

### ChangeError

```typescript
interface ChangeError {
  path: string;
  error: string;
}
```

### MirrorDiff

```typescript
interface MirrorDiff {
  add: RefChange[];
  update: RefChange[];
  delete: RefChange[];
}
```

Helper functions:
- `mirrorDiffInSync(md)` — true if no ref changes
- `mirrorDiffTotal(md)` — count of add + update + delete

### RefChange

```typescript
interface RefChange {
  ref: string;              // full ref name (e.g. 'refs/heads/main')
  oldTarget?: string;       // previous SHA or undefined
  newTarget?: string;       // new SHA or undefined
}
```

### CommitInfo

```typescript
interface CommitInfo {
  message: string;
  time: Date;
  authorName: string;
  authorEmail: string;
}
```

### ReflogEntry

```typescript
interface ReflogEntry {
  oldSha: string;
  newSha: string;
  committer: string;
  timestamp: number;        // POSIX epoch seconds
  message: string;
}
```

### Signature

```typescript
interface Signature {
  name: string;
  email: string;
}
```
