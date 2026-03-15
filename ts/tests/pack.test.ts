import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, rmTmpDir } from './helpers.js';
import { GitStore } from '../src/index.js';

let store: GitStore;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
});

afterEach(() => rmTmpDir(tmpDir));

describe('GitStore.pack', () => {
  it('throws not implemented', async () => {
    await expect(store.pack()).rejects.toThrow('not implemented');
  });
});

describe('GitStore.gc', () => {
  it('throws not implemented', async () => {
    await expect(store.gc()).rejects.toThrow('not implemented');
  });
});
