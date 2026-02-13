import { describe, it, expect, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';

describe('integration smoke test', () => {
  let tmpDir: string;
  afterEach(() => { if (tmpDir) rmTmpDir(tmpDir); });

  it('creates a store, writes, and reads back', async () => {
    const res = await freshStore();
    tmpDir = res.tmpDir;
    const store = res.store;

    let snap = await store.branches.get('main');
    snap = await snap.write('hello.txt', toBytes('Hello!'));

    const data = await snap.read('hello.txt');
    expect(fromBytes(data)).toBe('Hello!');
  });
});
