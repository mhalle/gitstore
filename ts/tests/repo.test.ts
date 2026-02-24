import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import { GitStore, FS } from '../src/index.js';
import * as path from 'node:path';

let store: GitStore;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
});

afterEach(() => rmTmpDir(tmpDir));

describe('GitStore.open', () => {
  it('creates with branch', async () => {
    expect(await store.branches.has('main')).toBe(true);
  });

  it('creates with custom branch', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: 'dev' });
    expect(await s2.branches.has('dev')).toBe(true);
    rmTmpDir(td);
  });

  it('creates bare repo with no branch', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: null });
    expect((await s2.branches.list()).length).toBe(0);
    rmTmpDir(td);
  });

  it('opens existing repo', async () => {
    const { store: s2 } = await freshStore();
    // re-open at same path
    const reopened = await GitStore.open(store._gitdir, { fs: store._fsModule });
    expect(await reopened.branches.has('main')).toBe(true);
  });

  it('open missing with create=false raises', async () => {
    await expect(
      GitStore.open('/tmp/nonexistent-repo-' + Date.now() + '.git', {
        fs: store._fsModule,
        create: false,
      }),
    ).rejects.toThrow(/not found/);
  });

  it('idempotent open', async () => {
    const s2 = await GitStore.open(store._gitdir, { fs: store._fsModule });
    expect(await s2.branches.has('main')).toBe(true);
  });

  it('custom author/email', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ author: 'Test', email: 'test@test.com' });
    const snap = await s2.branches.get('main');
    expect(await snap.getAuthorName()).toBe('Test');
    expect(await snap.getAuthorEmail()).toBe('test@test.com');
    rmTmpDir(td);
  });
});

describe('RefDict branches', () => {
  it('get returns FS with correct refName', async () => {
    const snap = await store.branches.get('main');
    expect(snap.refName).toBe('main');
    expect(snap.writable).toBe(true);
  });

  it('get missing throws', async () => {
    await expect(store.branches.get('nope')).rejects.toThrow(/Key not found/);
  });

  it('has', async () => {
    expect(await store.branches.has('main')).toBe(true);
    expect(await store.branches.has('nope')).toBe(false);
  });

  it('list/iteration', async () => {
    const names = await store.branches.list();
    expect(names).toContain('main');

    const iterNames: string[] = [];
    for await (const n of store.branches) iterNames.push(n);
    expect(iterNames).toContain('main');
  });

  it('length via list', async () => {
    expect((await store.branches.list()).length).toBe(1);
  });

  it('fork (set + get)', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.branches.set('exp', f2);
    const exp = await store.branches.get('exp');
    expect(exp.refName).toBe('exp');
    expect(await exp.exists('a.txt')).toBe(true);
  });

  it('delete', async () => {
    const snap = await store.branches.get('main');
    await store.branches.set('exp', snap);
    await store.branches.delete('exp');
    expect(await store.branches.has('exp')).toBe(false);
  });

  it('delete missing throws', async () => {
    await expect(store.branches.delete('nope')).rejects.toThrow(/Key not found/);
  });
});

describe('RefDict.set reflog oldSha', () => {
  it('records correct oldSha when overwriting existing branch', async () => {
    // Create a separate branch 'exp' from main
    const snap = await store.branches.get('main');
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.branches.set('exp', f1);
    const firstCommit = f1.commitHash;

    // Make a new commit (on main) to get a different SHA
    const f2 = await f1.write('b.txt', toBytes('bbb'));

    // Overwrite 'exp' with the new commit
    await store.branches.set('exp', f2);

    const entries = await store.branches.reflog('exp');
    // Most recent entry should have oldSha == firstCommit (before overwrite)
    const last = entries[entries.length - 1];
    expect(last.newSha).toBe(f2.commitHash);
    expect(last.oldSha).toBe(firstCommit);
    expect(last.oldSha).not.toBe(last.newSha);
  });
});

describe('RefDict tags', () => {
  it('tag and get', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    expect(tagged.refName).toBe('v1');
    expect(tagged.writable).toBe(false);
    expect(await tagged.exists('a.txt')).toBe(true);
  });

  it('tag missing throws', async () => {
    await expect(store.tags.get('nope')).rejects.toThrow(/Key not found/);
  });

  it('delete tag', async () => {
    const snap = await store.branches.get('main');
    await store.tags.set('v1', snap);
    await store.tags.delete('v1');
    expect(await store.tags.has('v1')).toBe(false);
  });

  it('iter tags', async () => {
    const snap = await store.branches.get('main');
    await store.tags.set('v1', snap);
    await store.tags.set('v2', snap);
    const names = (await store.tags.list()).sort();
    expect(names).toEqual(['v1', 'v2']);
  });

  it('tag overwrite raises', async () => {
    const snap = await store.branches.get('main');
    await store.tags.set('v1', snap);
    await expect(store.tags.set('v1', snap)).rejects.toThrow(/already exists/);
  });

  it('invalid type in set raises', async () => {
    await expect(store.tags.set('v1', 'not an FS' as any)).rejects.toThrow(TypeError);
  });
});

describe('RefDict current (HEAD)', () => {
  it('currentName is main', async () => {
    const def = await store.branches.getCurrentName();
    expect(def).toBe('main');
  });

  it('custom currentName', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: 'data' });
    expect(await s2.branches.getCurrentName()).toBe('data');
    rmTmpDir(td);
  });

  it('setCurrent works', async () => {
    const snap = await store.branches.get('main');
    await store.branches.set('dev', snap);
    await store.branches.setCurrent('dev');
    expect(await store.branches.getCurrentName()).toBe('dev');
  });

  it('setCurrent nonexistent raises', async () => {
    await expect(store.branches.setCurrent('nope')).rejects.toThrow(/not found/);
  });

  it('dangling HEAD returns master (isomorphic-git default)', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: null });
    // isomorphic-git init sets HEAD to refs/heads/master by default
    const def = await s2.branches.getCurrentName();
    expect(def).toBe('master');
    rmTmpDir(td);
  });

  it('tags getCurrentName raises', async () => {
    await expect(store.tags.getCurrentName()).rejects.toThrow(/Tags do not have a current branch/);
  });

  it('getCurrent returns FS with correct refName', async () => {
    const current = await store.branches.getCurrent();
    expect(current).not.toBeNull();
    expect(current!.refName).toBe('main');
    expect(current!.writable).toBe(true);
  });

  it('getCurrent returns null on dangling HEAD', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: null });
    const current = await s2.branches.getCurrent();
    expect(current).toBeNull();
    rmTmpDir(td);
  });
});

// ---------------------------------------------------------------------------
// Cross-repo validation
// ---------------------------------------------------------------------------

describe('cross-repo validation', () => {
  it('cross-repo branch assign raises', async () => {
    const { store: s2, tmpDir: td } = await freshStore();
    const otherSnap = await s2.branches.get('main');
    const f2 = await otherSnap.write('x.txt', toBytes('x'));
    // Setting a branch to an FS from a different repo should raise
    await expect(store.branches.set('cross', f2)).rejects.toThrow();
    rmTmpDir(td);
  });

  it('cross-repo tag assign raises', async () => {
    const { store: s2, tmpDir: td } = await freshStore();
    const otherSnap = await s2.branches.get('main');
    const f2 = await otherSnap.write('x.txt', toBytes('x'));
    await expect(store.tags.set('v1', f2)).rejects.toThrow();
    rmTmpDir(td);
  });

  it('same-path assign allowed', async () => {
    const s2 = await GitStore.open(store._gitdir, { fs: store._fsModule });
    const snap = await s2.branches.get('main');
    const f2 = await snap.write('x.txt', toBytes('x'));
    // Same underlying repo — should succeed
    await store.branches.set('cross', f2);
    expect(await store.branches.has('cross')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Author metadata in commits
// ---------------------------------------------------------------------------

describe('author metadata', () => {
  it('author info preserved across writes', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ author: 'Alice', email: 'alice@example.com' });
    const snap = await s2.branches.get('main');
    const f2 = await snap.write('x.txt', toBytes('x'));
    expect(await f2.getAuthorName()).toBe('Alice');
    expect(await f2.getAuthorEmail()).toBe('alice@example.com');
    rmTmpDir(td);
  });
});

// ---------------------------------------------------------------------------
// getCommitInfo
// ---------------------------------------------------------------------------

describe('getCommitInfo', () => {
  it('returns all commit fields in one call', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ author: 'Bob', email: 'bob@test.com' });
    const snap = await s2.branches.get('main');
    const f2 = await snap.write('x.txt', toBytes('x'));
    const info = await f2.getCommitInfo();
    expect(info.authorName).toBe('Bob');
    expect(info.authorEmail).toBe('bob@test.com');
    expect(info.message).toContain('x.txt');
    expect(info.time).toBeInstanceOf(Date);
    rmTmpDir(td);
  });

  it('matches individual getters', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('y.txt', toBytes('y'));
    const info = await f2.getCommitInfo();
    expect(info.message).toBe(await f2.getMessage());
    expect(info.time.getTime()).toBe((await f2.getTime()).getTime());
    expect(info.authorName).toBe(await f2.getAuthorName());
    expect(info.authorEmail).toBe(await f2.getAuthorEmail());
  });
});
