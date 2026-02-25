/**
 * Deno compatibility tests for gitstore.
 *
 * Run: deno test tests/deno_compat_test.ts --allow-read --allow-write
 *
 * These tests import the compiled dist/ to verify the package works
 * under Deno's runtime — same as an npm consumer would use it.
 * Requires `npm run build` first.
 */

import {
  assert,
  assertEquals,
  assertNotEquals,
  assertRejects,
} from 'jsr:@std/assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  GitStore,
  FileNotFoundError,
  normalizePath,
  validateRefName,
  FileType,
  type FS,
} from '../dist/index.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const enc = new TextEncoder();
const dec = new TextDecoder();

function toBytes(s: string): Uint8Array {
  return enc.encode(s);
}

function fromBytes(b: Uint8Array): string {
  return dec.decode(b);
}

function makeTmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'gitstore-deno-'));
}

async function freshStore(opts?: {
  branch?: string | null;
  author?: string;
  email?: string;
}): Promise<{ store: GitStore; tmpDir: string }> {
  const tmpDir = makeTmpDir();
  const repoPath = path.join(tmpDir, 'test.git');
  const store = await GitStore.open(repoPath, {
    fs,
    branch: opts?.branch !== undefined ? opts.branch : 'main',
    author: opts?.author,
    email: opts?.email,
  });
  return { store, tmpDir };
}

async function storeWithFiles(): Promise<{
  store: GitStore;
  snap: FS;
  tmpDir: string;
}> {
  const { store, tmpDir } = await freshStore();
  let snap = await store.branches.get('main');
  const b = snap.batch({ message: 'seed files' });
  await b.write('a.txt', toBytes('aaa'));
  await b.write('b.txt', toBytes('bbb'));
  await b.write('dir/c.txt', toBytes('ccc'));
  await b.write('dir/d.txt', toBytes('ddd'));
  snap = await b.commit();
  return { store, snap, tmpDir };
}

function cleanup(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Store creation & opening
// ---------------------------------------------------------------------------

Deno.test('create and open a bare repo', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    assert(await store.branches.has('main'));
    assertEquals([...(await store.branches.list())], ['main']);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('create with custom author/email', async () => {
  const { store, tmpDir } = await freshStore({
    author: 'deno-test',
    email: 'deno@test.local',
  });
  try {
    const snap = await store.branches.get('main');
    const info = await snap.getCommitInfo();
    assertEquals(info.authorName, 'deno-test');
    assertEquals(info.authorEmail, 'deno@test.local');
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('create with no initial branch', async () => {
  const { store, tmpDir } = await freshStore({ branch: null });
  try {
    assertEquals([...(await store.branches.list())], []);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('open existing repo (create=false)', async () => {
  const tmpDir = makeTmpDir();
  const repoPath = path.join(tmpDir, 'test.git');
  try {
    await GitStore.open(repoPath, { fs, branch: 'main' });
    const store2 = await GitStore.open(repoPath, { fs, create: false });
    assert(await store2.branches.has('main'));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Read operations
// ---------------------------------------------------------------------------

Deno.test('write and read back bytes', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    let snap = await store.branches.get('main');
    snap = await snap.write('hello.txt', toBytes('Hello from Deno!'));
    const data = await snap.read('hello.txt');
    assertEquals(fromBytes(data), 'Hello from Deno!');
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('writeText and readText', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    let snap = await store.branches.get('main');
    snap = await snap.writeText('greeting.txt', 'Kia ora!');
    assertEquals(await snap.readText('greeting.txt'), 'Kia ora!');
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('read missing file throws FileNotFoundError', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    const snap = await store.branches.get('main');
    await assertRejects(
      () => snap.read('nope.txt'),
      FileNotFoundError,
    );
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('ls lists files and dirs', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const root = await snap.ls();
    assert(root.includes('a.txt'));
    assert(root.includes('b.txt'));
    assert(root.includes('dir'));

    const dir = await snap.ls('dir');
    assert(dir.includes('c.txt'));
    assert(dir.includes('d.txt'));
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('exists and isDir', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    assert(await snap.exists('a.txt'));
    assert(await snap.exists('dir'));
    assert(await snap.exists('dir/c.txt'));
    assert(!(await snap.exists('nope.txt')));

    assert(await snap.isDir('dir'));
    assert(!(await snap.isDir('a.txt')));
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('fileType returns correct types', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    assertEquals(await snap.fileType('a.txt'), FileType.BLOB);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('size returns byte count', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    assertEquals(await snap.size('a.txt'), 3); // 'aaa'
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Stat
// ---------------------------------------------------------------------------

Deno.test('stat returns correct fields', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const st = await snap.stat('a.txt');
    assertEquals(st.size, 3);
    assertEquals(st.hash.length, 40);
    assertEquals(st.fileType, FileType.BLOB);
    assert(st.mtime! > 0);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('listdir returns WalkEntry objects', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const entries = await snap.listdir('dir');
    const names = entries.map((e: { name: string }) => e.name).sort();
    assertEquals(names, ['c.txt', 'd.txt']);
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Walk
// ---------------------------------------------------------------------------

Deno.test('walk yields directory entries', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const dirs: string[] = [];
    for await (const [dir, _subdirs, _files] of snap.walk()) {
      dirs.push(dir);
    }
    assert(dirs.includes(''));     // root
    assert(dirs.includes('dir'));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Batch writes
// ---------------------------------------------------------------------------

Deno.test('batch write and commit', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    let snap = await store.branches.get('main');
    const b = snap.batch({ message: 'batch test' });
    await b.write('x.txt', toBytes('xxx'));
    await b.write('y.txt', toBytes('yyy'));
    snap = await b.commit();

    assertEquals(fromBytes(await snap.read('x.txt')), 'xxx');
    assertEquals(fromBytes(await snap.read('y.txt')), 'yyy');
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('batch write and remove', async () => {
  const { snap: initial, tmpDir } = await storeWithFiles();
  try {
    const b = initial.batch();
    await b.write('new.txt', toBytes('new'));
    await b.remove('a.txt');
    const snap = await b.commit();

    assert(await snap.exists('new.txt'));
    assert(!(await snap.exists('a.txt')));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Branches & tags
// ---------------------------------------------------------------------------

Deno.test('create and delete branch', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    await store.branches.setAndGet('dev', snap);
    assert(await store.branches.has('dev'));

    const devSnap = await store.branches.get('dev');
    assertEquals(devSnap.commitHash, snap.commitHash);

    await store.branches.delete('dev');
    assert(!(await store.branches.has('dev')));
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('create and retrieve tag', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    await store.tags.set('v1.0', snap);
    const tagged = await store.tags.get('v1.0');
    assertEquals(tagged.commitHash, snap.commitHash);
    assertEquals(tagged.writable, false);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('branch iteration', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    await store.branches.setAndGet('alpha', snap);
    await store.branches.setAndGet('beta', snap);
    const names = (await store.branches.list()).sort();
    assert(names.includes('alpha'));
    assert(names.includes('beta'));
    assert(names.includes('main'));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

Deno.test('commit history via log()', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const hashes: string[] = [];
    for await (const entry of snap.log()) {
      hashes.push(entry.commitHash);
    }
    // init commit + seed files commit
    assertEquals(hashes.length, 2);
    assertNotEquals(hashes[0], hashes[1]);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('commit message available', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const msg = await snap.getMessage();
    assert(msg.length > 0);
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('commit time is valid Date', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const t = await snap.getTime();
    assert(t instanceof Date);
    assert(t.getTime() > 0);
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Copy ref (branch-to-branch)
// ---------------------------------------------------------------------------

Deno.test('copyFromRef copies subtree between branches', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    // Create a dev branch, write extra files on main
    await store.branches.setAndGet('dev', snap);
    let main = await store.branches.get('main');
    main = await main.write('extra/e.txt', toBytes('eee'));

    // Copy extra/ from main to dev
    let dev = await store.branches.get('dev');
    dev = await dev.copyFromRef(main, 'extra');
    assert(await dev.exists('extra/e.txt'));
    assertEquals(fromBytes(await dev.read('extra/e.txt')), 'eee');
  } finally {
    cleanup(tmpDir);
  }
});

Deno.test('copyFromRef dry run reports changes', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    await store.branches.setAndGet('dev', snap);
    let main = await store.branches.get('main');
    main = await main.write('new/f.txt', toBytes('fff'));

    const dev = await store.branches.get('dev');
    const result = await dev.copyFromRef(main, 'new', '', { dryRun: true });
    const changes = result.changes;
    assert(changes !== null);
    assert((changes as any).add.length > 0);
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Copy in/out (disk <-> repo)
// ---------------------------------------------------------------------------

Deno.test('copyIn from disk and copyOut to disk', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    // Write a file to disk
    const srcDir = path.join(tmpDir, 'input');
    fs.mkdirSync(srcDir, { recursive: true });
    fs.writeFileSync(path.join(srcDir, 'local.txt'), 'from disk');

    // Copy into repo
    const updated = await snap.copyIn(srcDir + '/', 'imported');
    assertEquals(await updated.readText('imported/local.txt'), 'from disk');

    // Copy back out
    const outDir = path.join(tmpDir, 'output');
    await updated.copyOut('imported/', outDir);
    assertEquals(
      fs.readFileSync(path.join(outDir, 'local.txt'), 'utf8'),
      'from disk',
    );
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// copyOut
// ---------------------------------------------------------------------------

Deno.test('copyOut tree to disk', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const outDir = path.join(tmpDir, 'export');
    await snap.copyOut('/', outDir);
    assertEquals(fs.readFileSync(path.join(outDir, 'a.txt'), 'utf8'), 'aaa');
    assertEquals(fs.readFileSync(path.join(outDir, 'dir', 'c.txt'), 'utf8'), 'ccc');
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

Deno.test('git notes set/get/delete', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    const ns = store.notes.namespace('test');
    const target = snap.commitHash;

    await ns.set(target, 'hello note');
    assertEquals(await ns.get(target), 'hello note');

    await ns.delete(target);
    // TS API throws on missing note (unlike Python which returns None)
    await assertRejects(() => ns.get(target));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Path utilities
// ---------------------------------------------------------------------------

Deno.test('normalizePath strips slashes and validates', () => {
  assertEquals(normalizePath('foo/bar'), 'foo/bar');
  assertEquals(normalizePath('/foo/bar/'), 'foo/bar');
  assertEquals(normalizePath('a'), 'a');
});

Deno.test('validateRefName rejects bad names', () => {
  // Valid
  validateRefName('main');
  validateRefName('feature/foo');

  // Invalid
  let threw = false;
  try {
    validateRefName('bad:name');
  } catch {
    threw = true;
  }
  assert(threw, 'colon should be rejected');
});

// ---------------------------------------------------------------------------
// Immutability: writes return new snapshots
// ---------------------------------------------------------------------------

Deno.test('write returns new snapshot, original unchanged', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    const snap1 = await store.branches.get('main');
    const snap2 = await snap1.write('x.txt', toBytes('x'));
    assertNotEquals(snap1.commitHash, snap2.commitHash);
    assert(!(await snap1.exists('x.txt')));
    assert(await snap2.exists('x.txt'));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Read-only enforcement
// ---------------------------------------------------------------------------

Deno.test('tag snapshots are read-only', async () => {
  const { store, snap, tmpDir } = await storeWithFiles();
  try {
    await store.tags.set('v1', snap);
    const tagged = await store.tags.get('v1');

    await assertRejects(
      () => tagged.write('x.txt', toBytes('x')),
      Error,
      'read-only',
    );
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// treeHash property
// ---------------------------------------------------------------------------

Deno.test('treeHash is 40-char hex', async () => {
  const { snap, tmpDir } = await storeWithFiles();
  try {
    const hash = snap.treeHash;
    assertEquals(hash.length, 40);
    assert(/^[0-9a-f]{40}$/.test(hash));
  } finally {
    cleanup(tmpDir);
  }
});

// ---------------------------------------------------------------------------
// Partial reads
// ---------------------------------------------------------------------------

Deno.test('read with offset and size', async () => {
  const { store, tmpDir } = await freshStore();
  try {
    let snap = await store.branches.get('main');
    snap = await snap.write('data.txt', toBytes('Hello, World!'));

    const partial = await snap.read('data.txt', { offset: 7, size: 5 });
    assertEquals(fromBytes(partial), 'World');
  } finally {
    cleanup(tmpDir);
  }
});
