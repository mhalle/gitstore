import { describe, it, expect, afterEach } from 'vitest';
import { freshStore, toBytes, rmTmpDir } from './helpers.js';
import {
  validateRefName,
  PermissionError,
} from '../src/index.js';

let _tmpDir: string;
afterEach(() => {
  if (_tmpDir) rmTmpDir(_tmpDir);
});

describe('validateRefName', () => {
  it('accepts valid name', () => {
    expect(() => validateRefName('main')).not.toThrow();
  });

  it('rejects colon', () => {
    expect(() => validateRefName('my:branch')).toThrow(/colon/);
  });

  it('rejects space', () => {
    expect(() => validateRefName('my branch')).toThrow(/space/);
  });

  it('rejects tab', () => {
    expect(() => validateRefName('my\tbranch')).toThrow(/tab/);
  });

  it('rejects newline', () => {
    expect(() => validateRefName('my\nbranch')).toThrow(/newline/);
  });

  it('accepts dots and slashes', () => {
    expect(() => validateRefName('feature/my-thing.v2')).not.toThrow();
  });
});

describe('write to read-only snapshot', () => {
  it('rejects write to tag', async () => {
    const { store, tmpDir } = await freshStore();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.writeText('hello.txt', 'hello');
    await store.tags.set('v1', fs);
    const tagFs = await store.tags.get('v1');
    await expect(tagFs.writeText('new.txt', 'x')).rejects.toThrow(PermissionError);
  });

  it('rejects batch on tag', async () => {
    const { store, tmpDir } = await freshStore();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.writeText('hello.txt', 'hello');
    await store.tags.set('v1', fs);
    const tagFs = await store.tags.get('v1');
    expect(() => tagFs.batch()).toThrow(PermissionError);
  });

  it('rejects undo on tag', async () => {
    const { store, tmpDir } = await freshStore();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.writeText('hello.txt', 'hello');
    await store.tags.set('v1', fs);
    const tagFs = await store.tags.get('v1');
    await expect(tagFs.undo()).rejects.toThrow(PermissionError);
  });
});
