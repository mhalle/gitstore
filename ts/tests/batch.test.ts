import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  FileNotFoundError,
  IsADirectoryError,
  PermissionError,
  StaleSnapshotError,
  MODE_BLOB_EXEC,
  MODE_LINK,
} from '../src/index.js';
import * as path from 'node:path';

let store: GitStore;
let snap: FS;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
  let f = await store.branches.get('main');
  snap = await f.write('a.txt', toBytes('a'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('batch', () => {
  it('multiple writes single commit', async () => {
    const b = snap.batch({ message: 'bulk' });
    await b.write('x.txt', toBytes('x'));
    await b.write('y.txt', toBytes('y'));
    const f2 = await b.commit();
    expect(await f2.exists('x.txt')).toBe(true);
    expect(await f2.exists('y.txt')).toBe(true);
    // Only one commit ahead
    const parent = await f2.getParent();
    expect(parent!.commitHash).toBe(snap.commitHash);
  });

  it('custom message', async () => {
    const b = snap.batch({ message: 'bulk upload' });
    await b.write('x.txt', toBytes('x'));
    const f2 = await b.commit();
    expect(await f2.getMessage()).toBe('bulk upload');
  });

  it('write and remove', async () => {
    const b = snap.batch({ message: 'mixed' });
    await b.write('new.txt', toBytes('new'));
    await b.remove('a.txt');
    const f2 = await b.commit();
    expect(await f2.exists('new.txt')).toBe(true);
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('empty batch returns same FS', async () => {
    const b = snap.batch({ message: 'empty' });
    const f2 = await b.commit();
    expect(f2.commitHash).toBe(snap.commitHash);
  });

  it('batch on readonly raises', async () => {
    const f1 = await snap.write('x.txt', toBytes('x'));
    await store.tags.set('v1', f1);
    const tagged = await store.tags.get('v1');
    expect(() => tagged.batch()).toThrow(/read-only/);
  });

  it('last op wins: write then remove', async () => {
    const b = snap.batch();
    await b.write('new.txt', toBytes('data'));
    await b.remove('new.txt');
    // new.txt was only staged, not in base, so remove should un-stage it
    // and since it's not in base, removing should throw
    // Actually: write stages it, remove checks if it exists in base (no) and was staged (yes)
    // Looking at the code: remove deletes from _writes and only adds to _removes if existsInBase
    const f2 = await b.commit();
    expect(await f2.exists('new.txt')).toBe(false);
  });

  it('overwrite then remove existing', async () => {
    const b = snap.batch();
    await b.write('a.txt', toBytes('updated'));
    await b.remove('a.txt');
    const f2 = await b.commit();
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('remove then write', async () => {
    const b = snap.batch();
    await b.remove('a.txt');
    await b.write('a.txt', toBytes('new content'));
    const f2 = await b.commit();
    expect(fromBytes(await f2.read('a.txt'))).toBe('new content');
  });

  it('write after commit raises', async () => {
    const b = snap.batch();
    await b.write('x.txt', toBytes('x'));
    await b.commit();
    await expect(b.write('y.txt', toBytes('y'))).rejects.toThrow(/closed/);
  });

  it('remove after commit raises', async () => {
    const b = snap.batch();
    await b.commit();
    await expect(b.remove('a.txt')).rejects.toThrow(/closed/);
  });

  it('remove directory raises IsADirectoryError', async () => {
    const f2 = await snap.write('d/f.txt', toBytes('x'));
    const b = f2.batch();
    await expect(b.remove('d')).rejects.toThrow(IsADirectoryError);
  });

  it('remove missing raises FileNotFoundError', async () => {
    const b = snap.batch();
    await expect(b.remove('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('stale batch is retryable', async () => {
    const stale = snap;
    await snap.write('x.txt', toBytes('x')); // advance branch
    const b = stale.batch();
    await b.write('y.txt', toBytes('y'));
    await expect(b.commit()).rejects.toThrow(StaleSnapshotError);
  });

  it('writeFromFile basic', async () => {
    const filePath = path.join(tmpDir, 'local.txt');
    fs.writeFileSync(filePath, 'from disk');
    const b = snap.batch();
    await b.writeFromFile('repo.txt', filePath);
    const f2 = await b.commit();
    expect(await f2.readText('repo.txt')).toBe('from disk');
  });

  it('writeFromFile preserves executable', async () => {
    const filePath = path.join(tmpDir, 'run.sh');
    fs.writeFileSync(filePath, '#!/bin/sh');
    fs.chmodSync(filePath, 0o755);
    const b = snap.batch();
    await b.writeFromFile('run.sh', filePath);
    const f2 = await b.commit();
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('writeFromFile mode override', async () => {
    const filePath = path.join(tmpDir, 'f.txt');
    fs.writeFileSync(filePath, 'data');
    const b = snap.batch();
    await b.writeFromFile('f.txt', filePath, { mode: MODE_BLOB_EXEC });
    const f2 = await b.commit();
    expect(await f2.fileType('f.txt')).toBe(FileType.EXECUTABLE);
  });

  it('writeFromFile missing file throws', async () => {
    const b = snap.batch();
    await expect(b.writeFromFile('x.txt', '/nonexistent/file.txt')).rejects.toThrow();
  });

  it('batch mode parameter', async () => {
    const b = snap.batch();
    await b.write('run.sh', toBytes('#!/bin/sh'), { mode: MODE_BLOB_EXEC });
    const f2 = await b.commit();
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('writeSymlink basic', async () => {
    const b = snap.batch();
    await b.writeSymlink('link.txt', 'a.txt');
    const f2 = await b.commit();
    expect(await f2.readlink('link.txt')).toBe('a.txt');
  });

  it('writeSymlink filemode', async () => {
    const b = snap.batch();
    await b.writeSymlink('link.txt', 'a.txt');
    const f2 = await b.commit();
    expect(await f2.fileType('link.txt')).toBe(FileType.LINK);
  });

  it('writeSymlink with other ops', async () => {
    const b = snap.batch();
    await b.writeSymlink('link.txt', 'a.txt');
    await b.write('new.txt', toBytes('new'));
    const f2 = await b.commit();
    expect(await f2.readlink('link.txt')).toBe('a.txt');
    expect(await f2.exists('new.txt')).toBe(true);
  });

  it('writeSymlink after commit raises', async () => {
    const b = snap.batch();
    await b.commit();
    await expect(b.writeSymlink('link.txt', 'a.txt')).rejects.toThrow(/closed/);
  });

  it('identical writes no new commit', async () => {
    const b = snap.batch();
    await b.write('a.txt', toBytes('a')); // same as existing
    const f2 = await b.commit();
    expect(f2.commitHash).toBe(snap.commitHash);
  });
});
