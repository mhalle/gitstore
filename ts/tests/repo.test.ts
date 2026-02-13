import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, rmTmpDir } from './helpers.js';
import { GitStore, FS } from '../src/index.js';

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
  it('get returns FS with correct branch', async () => {
    const snap = await store.branches.get('main');
    expect(snap.branch).toBe('main');
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
    expect(exp.branch).toBe('exp');
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

describe('RefDict tags', () => {
  it('tag and get', async () => {
    const snap = await store.branches.get('main');
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    expect(tagged.branch).toBeNull();
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

describe('RefDict default (HEAD)', () => {
  it('default is main', async () => {
    const def = await store.branches.getDefault();
    expect(def).toBe('main');
  });

  it('custom default', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: 'data' });
    expect(await s2.branches.getDefault()).toBe('data');
    rmTmpDir(td);
  });

  it('set default', async () => {
    const snap = await store.branches.get('main');
    await store.branches.set('dev', snap);
    await store.branches.setDefault('dev');
    expect(await store.branches.getDefault()).toBe('dev');
  });

  it('set nonexistent raises', async () => {
    await expect(store.branches.setDefault('nope')).rejects.toThrow(/not found/);
  });

  it('dangling HEAD returns master (isomorphic-git default)', async () => {
    const { store: s2, tmpDir: td } = await freshStore({ branch: null });
    // isomorphic-git init sets HEAD to refs/heads/master by default
    const def = await s2.branches.getDefault();
    expect(def).toBe('master');
    rmTmpDir(td);
  });

  it('tags default raises', async () => {
    await expect(store.tags.getDefault()).rejects.toThrow(/Tags do not have a default/);
  });
});
