import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  FileNotFoundError,
  NotADirectoryError,
  type StatResult,
} from '../src/index.js';

let store: GitStore;
let snap: FS;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;

  let f = await store.branches.get('main');
  f = await f.write('hello.txt', toBytes('Hello!'));
  f = await f.write('run.sh', toBytes('#!/bin/sh\n'), { mode: FileType.EXECUTABLE });
  f = await f.writeSymlink('link.txt', 'hello.txt');
  f = await f.write('src/main.py', toBytes("print('hi')"));
  snap = await f.write('src/lib/util.py', toBytes('# util'));
});

afterEach(() => rmTmpDir(tmpDir));

// -- stat() ----------------------------------------------------------------

describe('stat', () => {
  it('stat file', async () => {
    const st = await snap.stat('hello.txt');
    expect(st.mode).toBe(0o100644);
    expect(st.fileType).toBe(FileType.BLOB);
    expect(st.size).toBe(toBytes('Hello!').length);
    expect(st.nlink).toBe(1);
    expect(st.hash).toMatch(/^[0-9a-f]{40}$/);
    expect(st.mtime).toBeGreaterThan(0);
  });

  it('stat executable', async () => {
    const st = await snap.stat('run.sh');
    expect(st.mode).toBe(0o100755);
    expect(st.fileType).toBe(FileType.EXECUTABLE);
    expect(st.size).toBe(toBytes('#!/bin/sh\n').length);
    expect(st.nlink).toBe(1);
  });

  it('stat symlink', async () => {
    const st = await snap.stat('link.txt');
    expect(st.mode).toBe(0o120000);
    expect(st.fileType).toBe(FileType.LINK);
    expect(st.size).toBe('hello.txt'.length);
    expect(st.nlink).toBe(1);
  });

  it('stat directory', async () => {
    const st = await snap.stat('src');
    expect(st.mode).toBe(0o040000);
    expect(st.fileType).toBe(FileType.TREE);
    expect(st.size).toBe(0);
    // src/ has 1 subdir (lib), so nlink = 2 + 1 = 3
    expect(st.nlink).toBe(3);
  });

  it('stat root', async () => {
    const st = await snap.stat();
    expect(st.mode).toBe(0o040000);
    expect(st.fileType).toBe(FileType.TREE);
    expect(st.size).toBe(0);
    // Root has 1 subdir (src), so nlink = 2 + 1 = 3
    expect(st.nlink).toBe(3);
    expect(st.hash).toMatch(/^[0-9a-f]{40}$/);
  });

  it('stat root explicit null matches stat()', async () => {
    const stNull = await snap.stat(null);
    const stNone = await snap.stat();
    expect(stNull).toEqual(stNone);
  });

  it('stat nonexistent throws FileNotFoundError', async () => {
    await expect(snap.stat('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('stat size matches size()', async () => {
    for (const path of ['hello.txt', 'run.sh', 'src/main.py', 'src/lib/util.py']) {
      const st = await snap.stat(path);
      expect(st.size).toBe(await snap.size(path));
    }
  });

  it('stat hash matches objectHash()', async () => {
    for (const path of ['hello.txt', 'src', 'src/main.py']) {
      const st = await snap.stat(path);
      expect(st.hash).toBe(await snap.objectHash(path));
    }
  });

  it('stat nlink leaf dir', async () => {
    // src/lib has no subdirs, so nlink = 2
    const st = await snap.stat('src/lib');
    expect(st.nlink).toBe(2);
  });

  it('stat mtime consistent across paths', async () => {
    const stFile = await snap.stat('hello.txt');
    const stDir = await snap.stat('src');
    const stRoot = await snap.stat();
    expect(stFile.mtime).toBe(stDir.mtime);
    expect(stFile.mtime).toBe(stRoot.mtime);
  });
});

// -- listdir() -------------------------------------------------------------

describe('listdir', () => {
  it('listdir root names match ls()', async () => {
    const entries = await snap.listdir();
    const names = entries.map(e => e.name).sort();
    const lsNames = (await snap.ls()).sort();
    expect(names).toEqual(lsNames);
  });

  it('listdir subdir names match ls()', async () => {
    const entries = await snap.listdir('src');
    const names = entries.map(e => e.name).sort();
    const lsNames = (await snap.ls('src')).sort();
    expect(names).toEqual(lsNames);
  });

  it('listdir returns WalkEntry objects', async () => {
    const entries = await snap.listdir();
    for (const e of entries) {
      expect(e).toHaveProperty('name');
      expect(e).toHaveProperty('oid');
      expect(e).toHaveProperty('mode');
    }
  });

  it('listdir on file throws NotADirectoryError', async () => {
    await expect(snap.listdir('hello.txt')).rejects.toThrow(NotADirectoryError);
  });
});

// -- treeHash --------------------------------------------------------------

describe('treeHash', () => {
  it('is 40-char hex string', () => {
    expect(snap.treeHash).toMatch(/^[0-9a-f]{40}$/);
  });

  it('is stable', () => {
    expect(snap.treeHash).toBe(snap.treeHash);
  });

  it('changes on write', async () => {
    const old = snap.treeHash;
    const snap2 = await snap.write('new.txt', toBytes('data'));
    expect(snap2.treeHash).not.toBe(old);
  });
});

// -- read() with offset/size -----------------------------------------------

describe('read with range', () => {
  it('no opts unchanged', async () => {
    expect(fromBytes(await snap.read('hello.txt'))).toBe('Hello!');
  });

  it('offset and size', async () => {
    const data = await snap.read('hello.txt', { offset: 0, size: 3 });
    expect(fromBytes(data)).toBe('Hel');
  });

  it('offset middle', async () => {
    const data = await snap.read('hello.txt', { offset: 2, size: 2 });
    expect(fromBytes(data)).toBe('ll');
  });

  it('offset end', async () => {
    const data = await snap.read('hello.txt', { offset: 4, size: 2 });
    expect(fromBytes(data)).toBe('o!');
  });

  it('size beyond end clamps', async () => {
    const data = await snap.read('hello.txt', { offset: 4, size: 100 });
    expect(fromBytes(data)).toBe('o!');
  });

  it('size zero', async () => {
    const data = await snap.read('hello.txt', { offset: 0, size: 0 });
    expect(data.length).toBe(0);
  });

  it('offset at end', async () => {
    const data = await snap.read('hello.txt', { offset: 6, size: 10 });
    expect(data.length).toBe(0);
  });

  it('offset only', async () => {
    const data = await snap.read('hello.txt', { offset: 3 });
    expect(fromBytes(data)).toBe('lo!');
  });

  it('size only', async () => {
    const data = await snap.read('hello.txt', { size: 3 });
    expect(fromBytes(data)).toBe('Hel');
  });

  it('range on nonexistent throws FileNotFoundError', async () => {
    await expect(snap.read('nope.txt', { offset: 0, size: 10 })).rejects.toThrow(FileNotFoundError);
  });
});

// -- readByHash() ----------------------------------------------------------

describe('readByHash', () => {
  it('round-trips with objectHash', async () => {
    const h = await snap.objectHash('hello.txt');
    expect(fromBytes(await snap.readByHash(h))).toBe('Hello!');
  });

  it('matches read()', async () => {
    for (const path of ['hello.txt', 'run.sh', 'src/main.py']) {
      const h = await snap.objectHash(path);
      const byHash = await snap.readByHash(h);
      const byPath = await snap.read(path);
      expect(fromBytes(byHash)).toBe(fromBytes(byPath));
    }
  });

  it('range offset and size', async () => {
    const h = await snap.objectHash('hello.txt');
    const data = await snap.readByHash(h, { offset: 2, size: 2 });
    expect(fromBytes(data)).toBe('ll');
  });

  it('range offset only', async () => {
    const h = await snap.objectHash('hello.txt');
    const data = await snap.readByHash(h, { offset: 3 });
    expect(fromBytes(data)).toBe('lo!');
  });

  it('range size only', async () => {
    const h = await snap.objectHash('hello.txt');
    const data = await snap.readByHash(h, { size: 3 });
    expect(fromBytes(data)).toBe('Hel');
  });
});
