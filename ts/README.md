# @mhalle/vost

A versioned filesystem backed by bare Git repositories. Store, retrieve, and version directory trees of files with text and binary data using an immutable-snapshot API. Every write produces a new commit. Old snapshots remain accessible forever.

This is the TypeScript port of [vost](https://github.com/mhalle/vost), using [isomorphic-git](https://isomorphic-git.org/) as the git backend. The repositories are standard Git repos that can be manipulated with Git tools as well.

## Installation

```bash
npm install @mhalle/vost
```

Requires Node.js 18+ or Deno.

## Quick start

```typescript
import { GitStore } from '@mhalle/vost';

// Create (or open) a repository with a "main" branch
const store = await GitStore.open('data.git');

// Get a snapshot of the current branch ("main" by default)
let snap = await store.branches.getCurrent();

// Write a file -- returns a new immutable snapshot
snap = await snap.writeText('hello.txt', 'Hello, world!');

// Read it back
console.log(await snap.readText('hello.txt'));  // 'Hello, world!'

// Every write is a commit
console.log(snap.commitHash);                   // full 40-char SHA
console.log(await snap.getMessage());           // '+ hello.txt'
```

## Core concepts

**Bare repository.** vost uses a bare Git repository with no working directory. All data lives inside Git's content-addressable object store and is accessed through the vost API.

**`GitStore`** opens or creates a bare repository. It exposes `branches`, `tags`, and `notes`.

**`FS`** is an immutable snapshot of a committed tree. Reading methods (`read`, `ls`, `walk`, `exists`) never mutate state. Writing methods (`write`, `writeText`, `remove`, `batch`) return a *new* `FS` pointing at the new commit -- the original `FS` is unchanged.

Snapshots from **branches** are writable (`fs.writable === true`). Snapshots from **tags** are read-only (`fs.writable === false`).

**All operations are async** -- every read, write, and query returns a `Promise`.

## API

### Opening a repository

```typescript
const store = await GitStore.open('data.git');                          // create or open
const store = await GitStore.open('data.git', { create: false });       // open only
const store = await GitStore.open('data.git', { branch: 'dev' });       // custom default branch
const store = await GitStore.open('data.git', { branch: null });        // branchless
const store = await GitStore.open('data.git', {
  author: 'alice', email: 'alice@example.com' });                       // custom author
```

The `fs` option defaults to Node's `node:fs` module. Override it to provide a custom filesystem implementation (e.g. `lightning-fs` for browsers).

### Branches and tags

```typescript
let snap = await store.branches.get('main');
await store.branches.set('experiment', snap);    // fork a branch
await store.branches.delete('experiment');        // delete a branch

await store.tags.set('v1.0', snap);              // create a tag
const tagged = await store.tags.get('v1.0');     // read-only FS

const name = await store.branches.getCurrentName();  // 'main'
snap = await store.branches.getCurrent();            // FS for current branch
await store.branches.setCurrent('dev');              // set current branch

for await (const name of store.branches) {
  console.log(name);
}
console.log(await store.branches.has('main'));       // true
```

### Reading

```typescript
const data = await snap.read('path/to/file.bin');             // Uint8Array
const text = await snap.readText('config.json');              // string (UTF-8)
const chunk = await snap.read('big.bin', { offset: 100, size: 50 });  // partial read
const chunk = await snap.readByHash(sha, { offset: 0, size: 1024 }); // read blob by SHA

const entries = await snap.ls();                              // root listing -- string[]
const entries = await snap.ls('src');                         // subdirectory listing
const details = await snap.listdir('src');                    // WalkEntry[] (name, oid, mode)
const exists = await snap.exists('path/to/file.bin');         // boolean
const info = await snap.stat('path/to/file.bin');             // StatResult
const ftype = await snap.fileType('run.sh');                  // FileType.EXECUTABLE
const nbytes = await snap.size('path/to/file.bin');           // number (bytes)
const sha = await snap.objectHash('path/to/file.bin');        // 40-char hex SHA
const treeHash = snap.treeHash;                               // root tree SHA

// Walk the tree (like os.walk)
for await (const [dirpath, dirnames, files] of snap.walk()) {
  for (const entry of files) {
    console.log(entry.name, entry.mode);          // WalkEntry
  }
}

// Glob
const matches = await snap.glob('**/*.ts');                   // sorted string[]
```

### Writing

Every write auto-commits and returns a new snapshot:

```typescript
import { FileType } from '@mhalle/vost';

snap = await snap.writeText('config.json', '{"key": "value"}');
snap = await snap.writeText('script.sh', '#!/bin/sh\n', { mode: FileType.EXECUTABLE });
snap = await snap.writeText('config.json', '{}', { message: 'Reset' });
snap = await snap.write('image.png', rawBytes);                        // Uint8Array
snap = await snap.writeFromFile('big.bin', '/data/big.bin');           // from disk
snap = await snap.writeSymlink('link', 'target');                      // symlink
snap = await snap.remove('old-file.txt');

// Buffered write (commits on close)
const w = snap.writer('big.bin');
await w.write(chunk1);
await w.write(chunk2);
await w.close();
snap = w.fs;

// Text mode
const tw = snap.writer('log.txt', 'w');
await tw.write('line 1\n');
await tw.write('line 2\n');
await tw.close();
snap = tw.fs;
```

The original `FS` is never mutated:

```typescript
const snap1 = await store.branches.get('main');
const snap2 = await snap1.write('new.txt', new TextEncoder().encode('data'));
console.log(await snap1.exists('new.txt'));  // false -- snap1 is unchanged
console.log(await snap2.exists('new.txt'));  // true
```

### Batch writes

Multiple writes/removes in a single commit:

```typescript
const batch = snap.batch({ message: 'Import dataset v2' });
await batch.write('a.txt', new TextEncoder().encode('alpha'));
await batch.writeFromFile('big.bin', '/data/big.bin');
await batch.writeSymlink('link.txt', 'a.txt');
await batch.remove('old.txt');
snap = await batch.commit();  // single atomic commit
```

### Atomic apply

Apply multiple writes and removes in a single commit without a batch:

```typescript
import { WriteEntry } from '@mhalle/vost';

snap = await snap.apply(
  {
    'config.json': new TextEncoder().encode('{"v": 2}'),
    'script.sh': { data: new TextEncoder().encode('#!/bin/sh\n'), mode: FileType.EXECUTABLE },
    'link': { target: 'config.json' },                         // symlink
  },
  ['old.txt', 'deprecated/'],                                  // removes
  { message: 'Update config and clean up' },
);
```

### History

```typescript
const parent = await snap.parent();                         // FS or null
const ancestor = await snap.back(3);                        // 3 commits back

for await (const entry of snap.log()) {                     // full commit log
  console.log(entry.commitHash, await entry.getMessage());
}

for await (const entry of snap.log({ path: 'config.json' })) {  // file history
  console.log(entry.commitHash, await entry.getMessage());
}

snap = await snap.undo();                                   // move branch back 1 commit
snap = await snap.redo();                                   // move branch forward 1 reflog step

// Reflog
const entries = await store.branches.reflog('main');
for (const entry of entries) {
  console.log(entry.oldSha, entry.newSha, entry.message);
}
```

### Copy and sync

```typescript
// Disk to repo
snap = await snap.copyIn(['./data/'], 'backup');
console.log(snap.changes.add);                              // FileEntry[]

// Repo to disk
await snap.copyOut(['docs'], './local-docs');

// Copy between branches (atomic, no disk I/O)
let main = await store.branches.get('main');
let dev = await store.branches.get('dev');
dev = await dev.copyFromRef(main, ['config'], 'imported');

// Sync (make identical, including deletes)
snap = await snap.syncIn('./local', 'data');
await snap.syncOut('data', './local');

// Remove and move within repo
snap = await snap.remove(['old-dir'], { recursive: true });
snap = await snap.move(['old.txt'], 'new.txt');
```

### Snapshot properties

```typescript
snap.commitHash           // string -- full 40-char commit SHA
snap.refName              // string | null -- branch or tag name
snap.writable             // boolean -- true for branches, false for tags
snap.treeHash             // string -- root tree SHA
snap.changes              // ChangeReport | null

// Async properties (require commit object read)
await snap.getMessage()      // string -- commit message
await snap.getTime()         // Date -- commit timestamp
await snap.getAuthorName()   // string
await snap.getAuthorEmail()  // string
await snap.getCommitInfo()   // { message, time, authorName, authorEmail }
```

### Git notes

Attach metadata to commits without modifying history. Notes can be addressed by commit hash or ref name (branch/tag):

```typescript
// Default namespace (refs/notes/commits)
const ns = store.notes.commits;

// By commit hash
await ns.set(snap.commitHash, 'reviewed by Alice');
console.log(await ns.get(snap.commitHash));         // 'reviewed by Alice'

// By branch or tag name (resolves to tip commit)
await ns.set('main', 'deployed to staging');
console.log(await ns.get('main'));                   // 'deployed to staging'

await ns.delete(snap.commitHash);

// Custom namespaces
const reviews = store.notes.namespace('reviews');
await reviews.set('main', 'LGTM');

// Batch writes (single commit)
const batch = ns.batch();
await batch.set('main', 'note for main');
await batch.set('dev', 'note for dev');
await batch.commit();

// Iteration
for (const hash of await ns.list()) {
  console.log(hash, await ns.get(hash));
}
```

### Backup and restore

```typescript
const diff = await store.backup('https://github.com/user/repo.git');   // MirrorDiff
const diff = await store.restore('https://github.com/user/repo.git');  // MirrorDiff
const diff = await store.backup(url, { dryRun: true });                // preview only
```

## Concurrency safety

vost uses an advisory file lock (`vost.lock`) to make the stale-snapshot check and ref update atomic. If a branch advances after you obtain a snapshot, writing from the stale snapshot throws `StaleSnapshotError`:

```typescript
import { StaleSnapshotError, retryWrite } from '@mhalle/vost';

let snap = await store.branches.get('main');
await snap.write('a.txt', new TextEncoder().encode('a'));  // advances the branch

try {
  await snap.write('b.txt', new TextEncoder().encode('b'));  // snap is now stale
} catch (e) {
  if (e instanceof StaleSnapshotError) {
    snap = await store.branches.get('main');                 // re-fetch and retry
  }
}

// Or use retryWrite for automatic retry with backoff
snap = await retryWrite(store, 'main', 'file.txt', data);
```

## Error handling

| Exception | When |
|-----------|------|
| `FileNotFoundError` | `read`/`remove` on a missing path; `writeFromFile` with a missing local file |
| `IsADirectoryError` | `read` on a directory path |
| `NotADirectoryError` | `ls`/`walk` on a file path |
| `PermissionError` | Writing to a tag snapshot |
| `KeyNotFoundError` | Accessing a missing branch/tag |
| `KeyExistsError` | Overwriting an existing tag |
| `InvalidRefNameError` | Invalid characters in branch/tag name |
| `InvalidPathError` | Invalid path (`..`, empty segments) |
| `BatchClosedError` | Writing to a batch after `commit()` |
| `StaleSnapshotError` | Writing from a snapshot whose branch has moved forward |

All errors extend `GitStoreError`.

## Documentation

- [API Reference](https://github.com/mhalle/vost/blob/master/ts/docs/api.md) -- classes, methods, and types
- [Python version](https://github.com/mhalle/vost) -- the reference implementation with CLI

## Deno support

vost works under Deno using its Node.js compatibility layer:

```typescript
import { GitStore } from 'npm:@mhalle/vost';

const store = await GitStore.open('/tmp/repo.git');
```

## License

Apache-2.0 -- see [LICENSE](../LICENSE) for details.
