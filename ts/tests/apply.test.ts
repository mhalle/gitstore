import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  PermissionError,
  StaleSnapshotError,
  MODE_BLOB_EXEC,
} from '../src/index.js';
import { validateWriteEntry, type WriteEntry } from '../src/types.js';
import * as path from 'node:path';

let store: GitStore;
let snap: FS;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
  let f = await store.branches.get('main');
  snap = await f.write('a.txt', toBytes('aaa'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('WriteEntry validation', () => {
  it('data only is valid', () => {
    expect(() => validateWriteEntry({ data: toBytes('x') })).not.toThrow();
  });

  it('target only is valid', () => {
    expect(() => validateWriteEntry({ target: 'link' })).not.toThrow();
  });

  it('both data and target throws', () => {
    expect(() => validateWriteEntry({ data: toBytes('x'), target: 'link' })).toThrow(
      /Cannot specify both/,
    );
  });

  it('neither data nor target throws', () => {
    expect(() => validateWriteEntry({} as WriteEntry)).toThrow(/Must specify either/);
  });

  it('target with mode throws', () => {
    expect(() =>
      validateWriteEntry({ target: 'link', mode: FileType.EXECUTABLE }),
    ).toThrow(/Cannot specify mode for symlinks/);
  });
});

describe('apply writes', () => {
  it('bytes data', async () => {
    const f2 = await snap.apply({ 'new.txt': { data: toBytes('hello') } });
    expect(fromBytes(await f2.read('new.txt'))).toBe('hello');
  });

  it('string data (UTF-8)', async () => {
    const f2 = await snap.apply({ 'new.txt': { data: 'hello' } });
    expect(fromBytes(await f2.read('new.txt'))).toBe('hello');
  });

  it('symlink via target', async () => {
    const f2 = await snap.apply({ 'link.txt': { target: 'a.txt' } });
    expect(await f2.readlink('link.txt')).toBe('a.txt');
    expect(await f2.fileType('link.txt')).toBe(FileType.LINK);
  });

  it('executable mode', async () => {
    const f2 = await snap.apply({
      'run.sh': { data: toBytes('#!/bin/sh'), mode: FileType.EXECUTABLE },
    });
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('multiple writes single commit', async () => {
    const f2 = await snap.apply({
      'x.txt': { data: toBytes('x') },
      'y.txt': { data: 'y' },
    });
    expect(await f2.exists('x.txt')).toBe(true);
    expect(await f2.exists('y.txt')).toBe(true);
    const parent = await f2.getParent();
    expect(parent!.commitHash).toBe(snap.commitHash);
  });
});

describe('apply bare shorthand', () => {
  it('bare bytes', async () => {
    const f2 = await snap.apply({ 'b.txt': toBytes('bbb') });
    expect(fromBytes(await f2.read('b.txt'))).toBe('bbb');
  });

  it('bare string', async () => {
    const f2 = await snap.apply({ 'b.txt': 'bbb' });
    expect(fromBytes(await f2.read('b.txt'))).toBe('bbb');
  });

  it('mixed shorthand and WriteEntry', async () => {
    const f2 = await snap.apply({
      'x.txt': toBytes('x'),
      'y.txt': 'y',
      'z.txt': { data: toBytes('z') },
    });
    expect(await f2.exists('x.txt')).toBe(true);
    expect(await f2.exists('y.txt')).toBe(true);
    expect(await f2.exists('z.txt')).toBe(true);
  });
});

describe('apply removes', () => {
  it('single string', async () => {
    const f2 = await snap.apply(null, 'a.txt');
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('list', async () => {
    const f1 = await snap.write('b.txt', toBytes('bbb'));
    const f2 = await f1.apply(null, ['a.txt', 'b.txt']);
    expect(await f2.exists('a.txt')).toBe(false);
    expect(await f2.exists('b.txt')).toBe(false);
  });

  it('set', async () => {
    const f2 = await snap.apply(null, new Set(['a.txt']));
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('null removes is no-op', async () => {
    const f2 = await snap.apply(null, null);
    expect(f2.commitHash).toBe(snap.commitHash);
  });
});

describe('apply combined', () => {
  it('write and remove', async () => {
    const f2 = await snap.apply({ 'new.txt': toBytes('new') }, 'a.txt');
    expect(await f2.exists('new.txt')).toBe(true);
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('empty apply is no-op', async () => {
    const f2 = await snap.apply();
    expect(f2.commitHash).toBe(snap.commitHash);
  });
});

describe('apply commit options', () => {
  it('custom message', async () => {
    const f2 = await snap.apply({ 'x.txt': toBytes('x') }, null, { message: 'custom' });
    expect(await f2.getMessage()).toBe('custom');
  });

  it('operation keyword', async () => {
    const f2 = await snap.apply(
      { 'x.txt': toBytes('x'), 'y.txt': toBytes('y') },
      null,
      { operation: 'import' },
    );
    const msg = await f2.getMessage();
    expect(msg).toContain('import');
  });

  it('auto-generated message', async () => {
    const f2 = await snap.apply({ 'new.txt': toBytes('new') });
    const msg = await f2.getMessage();
    expect(msg).toContain('new.txt');
  });
});

describe('apply errors', () => {
  it('readonly raises PermissionError', async () => {
    await store.tags.set('v1', snap);
    const tagged = await store.tags.get('v1');
    await expect(tagged.apply({ 'x.txt': toBytes('x') })).rejects.toThrow(PermissionError);
  });

  it('stale raises StaleSnapshotError', async () => {
    const stale = snap;
    await snap.write('x.txt', toBytes('x'));
    await expect(stale.apply({ 'y.txt': toBytes('y') })).rejects.toThrow(StaleSnapshotError);
  });
});

describe('apply changes report', () => {
  it('add report', async () => {
    const f2 = await snap.apply({ 'new.txt': toBytes('new') });
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.add.length).toBe(1);
    expect(f2.changes!.add[0].path).toBe('new.txt');
  });

  it('update report', async () => {
    const f2 = await snap.apply({ 'a.txt': toBytes('updated') });
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.update.length).toBe(1);
    expect(f2.changes!.update[0].path).toBe('a.txt');
  });

  it('delete report', async () => {
    const f2 = await snap.apply(null, 'a.txt');
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.delete.length).toBe(1);
    expect(f2.changes!.delete[0].path).toBe('a.txt');
  });

  it('identical write produces no new commit', async () => {
    const f2 = await snap.apply({ 'a.txt': toBytes('aaa') });
    expect(f2.commitHash).toBe(snap.commitHash);
  });

  it('invalid type in writes raises TypeError', async () => {
    await expect(snap.apply({ 'x.txt': 42 as any })).rejects.toThrow(TypeError);
  });

  it('combined add/update/delete report', async () => {
    let f2 = await snap.write('b.txt', toBytes('bbb'));
    const f3 = await f2.apply(
      { 'new.txt': toBytes('new'), 'b.txt': toBytes('updated') },
      'a.txt',
    );
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.add.length).toBe(1);
    expect(f3.changes!.update.length).toBe(1);
    expect(f3.changes!.delete.length).toBe(1);
  });
});
