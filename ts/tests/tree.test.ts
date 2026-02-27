import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';
import { GitStore, FS, FileNotFoundError, IsADirectoryError, NotADirectoryError } from '../src/index.js';
import { normalizePath } from '../src/paths.js';
import {
  rebuildTree,
  readBlobAtPath,
  listTreeAtPath,
  existsAtPath,
  walkTree,
  type TreeWrite,
} from '../src/tree.js';
import { fs as nodeFs } from './helpers.js';
import git from 'isomorphic-git';

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

describe('normalizePath', () => {
  it('simple path unchanged', () => {
    expect(normalizePath('hello.txt')).toBe('hello.txt');
  });

  it('strips slashes', () => {
    expect(normalizePath('/a/b/')).toBe('a/b');
  });

  it('rejects empty', () => {
    expect(() => normalizePath('')).toThrow(/must not be empty/);
  });

  it('collapses dot segments', () => {
    expect(normalizePath('foo/./bar')).toBe('foo/bar');
    expect(normalizePath('./foo/bar')).toBe('foo/bar');
    expect(normalizePath('foo/bar/.')).toBe('foo/bar');
    expect(normalizePath('./foo/./bar/.')).toBe('foo/bar');
  });

  it('rejects only dots', () => {
    expect(() => normalizePath('.')).toThrow(/must not be empty/);
    expect(() => normalizePath('./.')).toThrow(/must not be empty/);
  });

  it('rejects dotdot', () => {
    expect(() => normalizePath('..')).toThrow(/Invalid path segment/);
    expect(() => normalizePath('foo/../bar')).toThrow(/Invalid path segment/);
  });

  it('rejects double slash', () => {
    expect(() => normalizePath('a//b')).toThrow(/Empty segment/);
  });
});

describe('rebuildTree', () => {
  it('single file', async () => {
    const writes = new Map<string, TreeWrite>([
      ['hello.txt', { data: toBytes('hello'), mode: '100644' }],
    ]);
    const treeOid = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes, new Set());
    expect(treeOid).toMatch(/^[0-9a-f]{40}$/);

    const data = await readBlobAtPath(nodeFs, store._gitdir, treeOid, 'hello.txt');
    expect(fromBytes(data)).toBe('hello');
  });

  it('nested path', async () => {
    const writes = new Map<string, TreeWrite>([
      ['a/b/c.txt', { data: toBytes('deep'), mode: '100644' }],
    ]);
    const treeOid = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes, new Set());
    const data = await readBlobAtPath(nodeFs, store._gitdir, treeOid, 'a/b/c.txt');
    expect(fromBytes(data)).toBe('deep');
  });

  it('structural sharing', async () => {
    // Write two files in different dirs
    const writes1 = new Map<string, TreeWrite>([
      ['a/x.txt', { data: toBytes('x'), mode: '100644' }],
      ['b/y.txt', { data: toBytes('y'), mode: '100644' }],
    ]);
    const tree1 = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes1, new Set());

    // Now update only file in 'a'
    const writes2 = new Map<string, TreeWrite>([
      ['a/x.txt', { data: toBytes('x2'), mode: '100644' }],
    ]);
    const tree2 = await rebuildTree(nodeFs, store._gitdir, tree1, writes2, new Set());
    expect(tree2).not.toBe(tree1);

    // Read 'b/y.txt' — should still be there
    const data = await readBlobAtPath(nodeFs, store._gitdir, tree2, 'b/y.txt');
    expect(fromBytes(data)).toBe('y');
  });

  it('remove file', async () => {
    const writes = new Map<string, TreeWrite>([
      ['hello.txt', { data: toBytes('hello'), mode: '100644' }],
    ]);
    const tree1 = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes, new Set());
    const tree2 = await rebuildTree(
      nodeFs, store._gitdir, tree1, new Map(), new Set(['hello.txt']),
    );
    expect(await existsAtPath(nodeFs, store._gitdir, tree2, 'hello.txt')).toBe(false);
  });

  it('remove last file prunes directory', async () => {
    const writes = new Map<string, TreeWrite>([
      ['d/only.txt', { data: toBytes('x'), mode: '100644' }],
    ]);
    const tree1 = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes, new Set());
    const tree2 = await rebuildTree(
      nodeFs, store._gitdir, tree1, new Map(), new Set(['d/only.txt']),
    );
    expect(await existsAtPath(nodeFs, store._gitdir, tree2, 'd')).toBe(false);
  });

  it('remove missing is no-op', async () => {
    const writes = new Map<string, TreeWrite>([
      ['hello.txt', { data: toBytes('hello'), mode: '100644' }],
    ]);
    const tree1 = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes, new Set());
    const tree2 = await rebuildTree(
      nodeFs, store._gitdir, tree1, new Map(), new Set(['nope.txt']),
    );
    expect(tree2).toBe(tree1);
  });

  it('overwrite file with directory', async () => {
    const writes1 = new Map<string, TreeWrite>([
      ['x', { data: toBytes('file'), mode: '100644' }],
    ]);
    const tree1 = await rebuildTree(nodeFs, store._gitdir, snap._treeOid, writes1, new Set());

    const writes2 = new Map<string, TreeWrite>([
      ['x/y.txt', { data: toBytes('nested'), mode: '100644' }],
    ]);
    const tree2 = await rebuildTree(nodeFs, store._gitdir, tree1, writes2, new Set());
    const data = await readBlobAtPath(nodeFs, store._gitdir, tree2, 'x/y.txt');
    expect(fromBytes(data)).toBe('nested');
  });
});

describe('read helpers', () => {
  let treeOid: string;

  beforeEach(async () => {
    const f = await snap.write('hello.txt', toBytes('hello'));
    const f2 = await f.write('d/sub.txt', toBytes('sub'));
    treeOid = f2._treeOid;
  });

  it('readBlobAtPath reads data', async () => {
    const data = await readBlobAtPath(nodeFs, store._gitdir, treeOid, 'hello.txt');
    expect(fromBytes(data)).toBe('hello');
  });

  it('readBlobAtPath missing throws', async () => {
    await expect(
      readBlobAtPath(nodeFs, store._gitdir, treeOid, 'nope.txt'),
    ).rejects.toThrow(FileNotFoundError);
  });

  it('readBlobAtPath directory throws', async () => {
    await expect(
      readBlobAtPath(nodeFs, store._gitdir, treeOid, 'd'),
    ).rejects.toThrow(IsADirectoryError);
  });

  it('listTreeAtPath root', async () => {
    const items = await listTreeAtPath(nodeFs, store._gitdir, treeOid);
    expect(items.sort()).toEqual(['d', 'hello.txt']);
  });

  it('listTreeAtPath subdir', async () => {
    const items = await listTreeAtPath(nodeFs, store._gitdir, treeOid, 'd');
    expect(items).toEqual(['sub.txt']);
  });

  it('listTreeAtPath file throws', async () => {
    await expect(
      listTreeAtPath(nodeFs, store._gitdir, treeOid, 'hello.txt'),
    ).rejects.toThrow(NotADirectoryError);
  });

  it('existsAtPath file', async () => {
    expect(await existsAtPath(nodeFs, store._gitdir, treeOid, 'hello.txt')).toBe(true);
  });

  it('existsAtPath directory', async () => {
    expect(await existsAtPath(nodeFs, store._gitdir, treeOid, 'd')).toBe(true);
  });

  it('existsAtPath missing', async () => {
    expect(await existsAtPath(nodeFs, store._gitdir, treeOid, 'nope.txt')).toBe(false);
  });
});

describe('walkTree', () => {
  it('empty tree', async () => {
    const entries = [];
    for await (const e of walkTree(nodeFs, store._gitdir, snap._treeOid)) entries.push(e);
    expect(entries.length).toBe(1);
    expect(entries[0][0]).toBe('');
    expect(entries[0][1]).toEqual([]);
    expect(entries[0][2]).toEqual([]);
  });

  it('nested tree', async () => {
    const f = await snap.write('a.txt', toBytes('a'));
    const f2 = await f.write('d/sub/deep.txt', toBytes('deep'));
    const entries = [];
    for await (const e of walkTree(nodeFs, store._gitdir, f2._treeOid)) entries.push(e);

    // Root entry
    expect(entries[0][0]).toBe('');
    expect(entries[0][1]).toContain('d');
    expect(entries[0][2].map((f: any) => f.name)).toContain('a.txt');

    // d/ entry
    const dEntry = entries.find((e) => e[0] === 'd');
    expect(dEntry).toBeDefined();
    expect(dEntry![1]).toContain('sub');

    // d/sub entry
    const subEntry = entries.find((e) => e[0] === 'd/sub');
    expect(subEntry).toBeDefined();
    expect(subEntry![2].map((f: any) => f.name)).toContain('deep.txt');
  });
});
