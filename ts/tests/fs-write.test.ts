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
  snap = await store.branches.get('main');
});

afterEach(() => rmTmpDir(tmpDir));

describe('writeText', () => {
  it('roundtrip', async () => {
    const f2 = await snap.writeText('hello.txt', 'Hello!');
    expect(await f2.readText('hello.txt')).toBe('Hello!');
    expect(fromBytes(await f2.read('hello.txt'))).toBe('Hello!');
  });

  it('with encoding', async () => {
    const bytes = new Uint8Array([0x63, 0x61, 0x66, 0xe9]);
    const f2 = await snap.write('latin.txt', bytes);
    const text = await f2.readText('latin.txt', 'latin1');
    expect(text).toBe('café');
  });

  it('custom message', async () => {
    const f2 = await snap.writeText('x.txt', 'x', { message: 'custom msg' });
    expect(await f2.getMessage()).toBe('custom msg');
  });
});

describe('write', () => {
  it('returns new FS with different commit', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    expect(f2.commitHash).not.toBe(snap.commitHash);
  });

  it('old FS unchanged', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    expect(await snap.exists('a.txt')).toBe(false);
    expect(await f2.exists('a.txt')).toBe(true);
  });

  it('binary data roundtrips', async () => {
    const data = new Uint8Array(256);
    for (let i = 0; i < 256; i++) data[i] = i;
    const f2 = await snap.write('bin.dat', data);
    const read = await f2.read('bin.dat');
    expect(read).toEqual(data);
  });

  it('nested path creates directories', async () => {
    const f2 = await snap.write('a/b/c.txt', toBytes('deep'));
    expect(await f2.exists('a/b/c.txt')).toBe(true);
  });

  it('branch advances', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    const latest = await store.branches.get('main');
    expect(latest.commitHash).toBe(f2.commitHash);
  });

  it('custom message', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'), { message: 'custom msg' });
    expect(await f2.getMessage()).toBe('custom msg');
  });

  it('write with executable mode', async () => {
    const f2 = await snap.write('run.sh', toBytes('#!/bin/sh'), { mode: FileType.EXECUTABLE });
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('write on tag raises PermissionError', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    await expect(tagged.write('b.txt', toBytes('bbb'))).rejects.toThrow(PermissionError);
  });
});

describe('remove', () => {
  it('removes a file', async () => {
    let f2 = await snap.write('a.txt', toBytes('aaa'));
    f2 = await f2.remove('a.txt');
    expect(await f2.exists('a.txt')).toBe(false);
  });

  it('missing file throws FileNotFoundError', async () => {
    await expect(snap.remove('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('remove on tag raises PermissionError', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    await expect(tagged.remove('a.txt')).rejects.toThrow(PermissionError);
  });

  it('remove directory raises IsADirectoryError', async () => {
    const f2 = await snap.write('d/f.txt', toBytes('x'));
    await expect(f2.remove('d')).rejects.toThrow(IsADirectoryError);
  });
});

describe('stale snapshot', () => {
  it('stale write raises StaleSnapshotError', async () => {
    const stale = snap;
    await snap.write('a.txt', toBytes('aaa')); // advances branch
    await expect(stale.write('b.txt', toBytes('bbb'))).rejects.toThrow(StaleSnapshotError);
  });

  it('stale remove raises StaleSnapshotError', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    const stale = f2;
    await f2.write('b.txt', toBytes('bbb')); // advances branch
    await expect(stale.remove('a.txt')).rejects.toThrow(StaleSnapshotError);
  });

  it('stale batch raises StaleSnapshotError', async () => {
    const stale = snap;
    await snap.write('a.txt', toBytes('aaa'));
    const b = stale.batch({ message: 'test' });
    await b.write('b.txt', toBytes('bbb'));
    await expect(b.commit()).rejects.toThrow(StaleSnapshotError);
  });
});

describe('writeFromFile', () => {
  it('basic write from disk file', async () => {
    const filePath = path.join(tmpDir, 'local.txt');
    fs.writeFileSync(filePath, 'from disk');
    const f2 = await snap.writeFromFile('repo.txt', filePath);
    expect(await f2.readText('repo.txt')).toBe('from disk');
  });

  it('preserves executable bit', async () => {
    const filePath = path.join(tmpDir, 'run.sh');
    fs.writeFileSync(filePath, '#!/bin/sh');
    fs.chmodSync(filePath, 0o755);
    const f2 = await snap.writeFromFile('run.sh', filePath);
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('mode override', async () => {
    const filePath = path.join(tmpDir, 'f.txt');
    fs.writeFileSync(filePath, 'data');
    const f2 = await snap.writeFromFile('f.txt', filePath, { mode: FileType.EXECUTABLE });
    expect(await f2.fileType('f.txt')).toBe(FileType.EXECUTABLE);
  });

  it('custom message', async () => {
    const filePath = path.join(tmpDir, 'f.txt');
    fs.writeFileSync(filePath, 'data');
    const f2 = await snap.writeFromFile('f.txt', filePath, { message: 'from file' });
    expect(await f2.getMessage()).toBe('from file');
  });

  it('write on tag raises PermissionError', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    const filePath = path.join(tmpDir, 'f.txt');
    fs.writeFileSync(filePath, 'data');
    await expect(tagged.writeFromFile('b.txt', filePath)).rejects.toThrow(PermissionError);
  });

  it('missing file throws', async () => {
    await expect(snap.writeFromFile('x.txt', '/nonexistent/file.txt')).rejects.toThrow();
  });
});

describe('symlinks', () => {
  it('write symlink basic', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    expect(await f2.readlink('link.txt')).toBe('hello.txt');
  });

  it('symlink filemode', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    expect(await f2.fileType('link.txt')).toBe(FileType.LINK);
  });

  it('nested target', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'a/b/c.txt');
    expect(await f2.readlink('link.txt')).toBe('a/b/c.txt');
  });

  it('custom message', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt', { message: 'add link' });
    expect(await f2.getMessage()).toBe('add link');
  });

  it('default message mentions link', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    const msg = await f2.getMessage();
    expect(msg).toContain('link.txt');
    expect(msg).toContain('link');
  });

  it('write on tag raises PermissionError', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f2);
    const tagged = await store.tags.get('v1');
    await expect(tagged.writeSymlink('link.txt', 'a.txt')).rejects.toThrow(PermissionError);
  });

  it('readlink missing throws FileNotFoundError', async () => {
    await expect(snap.readlink('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('readlink on regular file throws', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f2.readlink('a.txt')).rejects.toThrow(/Not a symlink/);
  });

  it('read symlink returns target as bytes', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    const data = await f2.read('link.txt');
    expect(fromBytes(data)).toBe('hello.txt');
  });

  it('remove symlink works', async () => {
    let f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    f2 = await f2.remove('link.txt');
    expect(await f2.exists('link.txt')).toBe(false);
  });
});

describe('no-op commit', () => {
  it('identical write returns same commit', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    const f3 = await f2.write('a.txt', toBytes('aaa'));
    expect(f3.commitHash).toBe(f2.commitHash);
  });

  it('identical batch returns same commit', async () => {
    const f2 = await snap.write('a.txt', toBytes('aaa'));
    const b = f2.batch({ message: 'noop' });
    await b.write('a.txt', toBytes('aaa'));
    const f3 = await b.commit();
    expect(f3.commitHash).toBe(f2.commitHash);
  });
});

describe('undo', () => {
  it('single step', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo();
    expect(undone.commitHash).toBe(f1.commitHash);
  });

  it('multiple steps', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo(2);
    expect(undone.commitHash).toBe(snap.commitHash);
  });

  it('updates branch', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    await f2.undo();
    const latest = await store.branches.get('main');
    expect(latest.commitHash).toBe(f1.commitHash);
  });

  it('zero raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f1.undo(0)).rejects.toThrow(/steps must be >= 1/);
  });

  it('negative raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f1.undo(-1)).rejects.toThrow(/steps must be >= 1/);
  });

  it('too many raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f1.undo(5)).rejects.toThrow(/Cannot undo/);
  });

  it('on tag raises PermissionError', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f1);
    const tagged = await store.tags.get('v1');
    await expect(tagged.undo()).rejects.toThrow(PermissionError);
  });
});

describe('redo', () => {
  it('after undo', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo();
    const redone = await undone.redo();
    expect(redone.commitHash).toBe(f2.commitHash);
  });

  it('multiple steps', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo();
    const redone = await undone.redo();
    expect(redone.commitHash).toBe(f2.commitHash);
  });

  it('updates branch', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo();
    await undone.redo();
    const latest = await store.branches.get('main');
    expect(latest.commitHash).toBe(f2.commitHash);
  });

  it('zero raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f1.redo(0)).rejects.toThrow(/steps must be >= 1/);
  });

  it('negative raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await expect(f1.redo(-1)).rejects.toThrow(/steps must be >= 1/);
  });

  it('too many raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const undone = await f1.undo();
    await expect(undone.redo(5)).rejects.toThrow(/Cannot redo/);
  });

  it('on tag raises PermissionError', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f1);
    const tagged = await store.tags.get('v1');
    await expect(tagged.redo()).rejects.toThrow(PermissionError);
  });
});

describe('reflog', () => {
  it('shows entries', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await f1.write('b.txt', toBytes('bbb'));
    const entries = await store.branches.reflog('main');
    expect(entries.length).toBeGreaterThanOrEqual(2);
    expect(entries[0]).toHaveProperty('message');
    expect(entries[0]).toHaveProperty('newSha');
    expect(entries[0]).toHaveProperty('oldSha');
  });

  it('includes undo entry', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    await f2.undo();
    const entries = await store.branches.reflog('main');
    const last = entries[entries.length - 1];
    expect(last.message).toContain('undo');
  });

  it('nonexistent branch raises', async () => {
    await expect(store.branches.reflog('nope')).rejects.toThrow(/Key not found/);
  });

  it('tags reflog raises', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f1);
    await expect(store.tags.reflog('v1')).rejects.toThrow(/Tags do not have reflog/);
  });
});

describe('undo/redo edge cases', () => {
  it('undo then new commit diverges history', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const undone = await f2.undo();
    const f3 = await undone.write('c.txt', toBytes('ccc'));
    expect(f3.commitHash).not.toBe(f2.commitHash);
    expect(await f3.exists('c.txt')).toBe(true);
    expect(await f3.exists('b.txt')).toBe(false);
  });

  it('undo redo undo sequence', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const u1 = await f2.undo();
    const r1 = await u1.redo();
    const u2 = await r1.undo();
    expect(u2.commitHash).toBe(f1.commitHash);
  });

  it('multiple undos then redo restores last undo', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    const f3 = await f2.write('c.txt', toBytes('ccc'));
    const u = await f3.undo();
    const r = await u.redo();
    expect(r.commitHash).toBe(f3.commitHash);
  });

  it('undo/redo works with batch', async () => {
    const b = snap.batch({ message: 'batch' });
    await b.write('x.txt', toBytes('xxx'));
    await b.write('y.txt', toBytes('yyy'));
    const f1 = await b.commit();
    const undone = await f1.undo();
    expect(await undone.exists('x.txt')).toBe(false);
    const redone = await undone.redo();
    expect(await redone.exists('x.txt')).toBe(true);
  });
});

describe('branches.set', () => {
  it('returns writable FS via setAndGet', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await store.branches.setAndGet('exp', f1);
    expect(f2.refName).toBe('exp');
  });

  it('creates new branch', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.branches.set('exp', f1);
    expect(await store.branches.has('exp')).toBe(true);
  });

  it('updates existing branch', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.branches.set('exp', f1);
    const f2 = await f1.write('b.txt', toBytes('bbb'));
    await store.branches.set('exp', f2);
    const exp = await store.branches.get('exp');
    expect(exp.commitHash).toBe(f2.commitHash);
  });

  it('accepts readonly tag snapshot', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    await store.tags.set('v1', f1);
    const tagged = await store.tags.get('v1');
    await store.branches.set('from-tag', tagged);
    expect(await store.branches.has('from-tag')).toBe(true);
  });

  it('returned FS is writable', async () => {
    const f1 = await snap.write('a.txt', toBytes('aaa'));
    const f2 = await store.branches.setAndGet('exp', f1);
    const f3 = await f2.write('b.txt', toBytes('bbb'));
    expect(await f3.exists('b.txt')).toBe(true);
  });
});

describe('retryWrite', () => {
  it('succeeds on first try', async () => {
    const { retryWrite } = await import('../src/index.js');
    const f1 = await retryWrite(store, 'main', 'retry.txt', toBytes('ok'));
    expect(await f1.readText('retry.txt')).toBe('ok');
  });
});

describe('filemode-only change detected in log', () => {
  it('mode change shows in log with path filter', async () => {
    const f1 = await snap.write('script.sh', toBytes('#!/bin/sh'));
    const f2 = await f1.write('script.sh', toBytes('#!/bin/sh'), { mode: FileType.EXECUTABLE });
    const entries = [];
    for await (const e of f2.log({ path: 'script.sh' })) entries.push(e);
    // Should have at least 2 entries (initial write + mode change)
    expect(entries.length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// Large binary and special filenames (ported from Python)
// ---------------------------------------------------------------------------

describe('large binary roundtrip', () => {
  it('1MB binary data', async () => {
    const data = new Uint8Array(1024 * 1024);
    for (let i = 0; i < data.length; i++) data[i] = i % 256;
    const f2 = await snap.write('large.bin', data);
    const read = await f2.read('large.bin');
    expect(read.length).toBe(1024 * 1024);
    expect(Buffer.from(read).equals(Buffer.from(data))).toBe(true);
  });
});

describe('special character filenames write/read', () => {
  it('filenames with spaces', async () => {
    const f2 = await snap.write('my file.txt', toBytes('spaces'));
    expect(fromBytes(await f2.read('my file.txt'))).toBe('spaces');
  });

  it('filenames with special chars', async () => {
    const f2 = await snap.write('file#1.txt', toBytes('hash'));
    const f3 = await f2.write('file@2.txt', toBytes('at'));
    const f4 = await f3.write('a=b.txt', toBytes('equals'));
    expect(fromBytes(await f4.read('file#1.txt'))).toBe('hash');
    expect(fromBytes(await f4.read('file@2.txt'))).toBe('at');
    expect(fromBytes(await f4.read('a=b.txt'))).toBe('equals');
  });

  it('unicode filenames', async () => {
    const f2 = await snap.write('café.txt', toBytes('coffee'));
    expect(fromBytes(await f2.read('café.txt'))).toBe('coffee');
  });

  it('writeFromFile with directory raises IsADirectoryError', async () => {
    const dir = path.join(tmpDir, 'adir');
    fs.mkdirSync(dir);
    await expect(snap.writeFromFile('x.txt', dir)).rejects.toThrow(IsADirectoryError);
  });
});
