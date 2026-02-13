import { describe, it, expect, afterEach } from 'vitest';
import { freshStore, toBytes, rmTmpDir } from './helpers.js';

describe('get/set head branch', () => {
  let tmpDir: string;
  afterEach(() => { if (tmpDir) rmTmpDir(tmpDir); });

  it('new repo HEAD matches branch', async () => {
    const { store, tmpDir: td } = await freshStore();
    tmpDir = td;
    const def = await store.branches.getDefault();
    expect(def).toBe('main');
  });

  it('default is main', async () => {
    const { store, tmpDir: td } = await freshStore();
    tmpDir = td;
    expect(await store.branches.getDefault()).toBe('main');
  });

  it('dangling HEAD returns master (isomorphic-git default)', async () => {
    const { store, tmpDir: td } = await freshStore({ branch: null });
    tmpDir = td;
    // isomorphic-git init sets HEAD to refs/heads/master by default
    const def = await store.branches.getDefault();
    expect(def).toBe('master');
  });

  it('setDefault works', async () => {
    const { store, tmpDir: td } = await freshStore();
    tmpDir = td;
    const snap = await store.branches.get('main');
    await store.branches.set('dev', snap);
    await store.branches.setDefault('dev');
    expect(await store.branches.getDefault()).toBe('dev');
  });

  it('bare repo HEAD defaults to master', async () => {
    const { store, tmpDir: td } = await freshStore({ branch: null });
    tmpDir = td;
    // isomorphic-git init creates HEAD → refs/heads/master even when no branch created
    expect(await store.branches.getDefault()).toBe('master');
  });
});
