import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';
import { GitStore, KeyNotFoundError } from '../src/index.js';

let store: GitStore;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
});

afterEach(() => rmTmpDir(tmpDir));

describe('GitStore.fs()', () => {
  it('resolves branch (writable)', async () => {
    const snap = await store.branches.get('main');
    await snap.write('a.txt', toBytes('aaa'));

    const fs = await store.fs('main');
    expect(fs.refName).toBe('main');
    expect(fs.writable).toBe(true);
  });

  it('resolves tag (read-only)', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);

    const fs = await store.fs('v1');
    expect(fs.refName).toBe('v1');
    expect(fs.writable).toBe(false);
  });

  it('resolves full commit hash (read-only)', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    const hash = f2.commitHash;

    const fs = await store.fs(hash);
    expect(fs.commitHash).toBe(hash);
    expect(fs.writable).toBe(false);
  });

  it('supports back parameter', async () => {
    const snap = await store.branches.get('main');
    const f1 = await snap.write('a.txt', toBytes('v1'));
    const f2 = await f1.write('a.txt', toBytes('v2'));

    const fs = await store.fs('main', { back: 1 });
    const content = fromBytes(await fs.read('a.txt'));
    expect(content).toBe('v1');
  });

  it('throws on missing ref', async () => {
    await expect(store.fs('nonexistent')).rejects.toThrow(KeyNotFoundError);
  });

  it('branch takes priority over tag with same name', async () => {
    // Create a tag named 'dev'
    const snap = await store.branches.get('main');
    const f1 = await snap.write('a.txt', toBytes('tag-content'));
    await store.tags.set('dev', f1);

    // Create a branch named 'dev' with different content
    const f2 = await f1.write('b.txt', toBytes('branch-content'));
    await store.branches.set('dev', f2);

    const fs = await store.fs('dev');
    // Should resolve to the branch (writable)
    expect(fs.writable).toBe(true);
    expect(await fs.exists('b.txt')).toBe(true);
  });

  it('commit hash read has correct content', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('hello.txt', toBytes('world'));
    const hash = f2.commitHash;

    const fs = await store.fs(hash);
    const content = fromBytes(await fs.read('hello.txt'));
    expect(content).toBe('world');
  });
});
