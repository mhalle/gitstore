import { describe, it, expect, afterEach } from 'vitest';
import {
  freshStore,
  toBytes,
  fromBytes,
  rmTmpDir,
} from './helpers.js';
import {
  FileNotFoundError,
  IsADirectoryError,
  PermissionError,
} from '../src/index.js';

async function storeWithFiles() {
  const { store, tmpDir } = await freshStore();
  let fs = await store.branches.get('main');
  const batch = fs.batch({ message: 'seed' });
  await batch.write('hello.txt', toBytes('hello world'));
  await batch.write('dir/a.txt', toBytes('aaa'));
  await batch.write('dir/b.txt', toBytes('bbb'));
  await batch.write('other/c.txt', toBytes('ccc'));
  fs = await batch.commit();
  return { store, fs, tmpDir };
}

let _tmpDir: string;
afterEach(() => {
  if (_tmpDir) rmTmpDir(_tmpDir);
});

describe('move rename', () => {
  it('renames a file', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'renamed.txt');
    expect(fromBytes(await fs.read('renamed.txt'))).toBe('hello world');
    expect(await fs.exists('hello.txt')).toBe(false);
  });

  it('preserves other files', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'renamed.txt');
    expect(fromBytes(await fs.read('dir/a.txt'))).toBe('aaa');
  });

  it('moves into directory with trailing slash', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'dir/');
    expect(fromBytes(await fs.read('dir/hello.txt'))).toBe('hello world');
    expect(await fs.exists('hello.txt')).toBe(false);
  });

  it('moves multiple files into directory', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move(['hello.txt', 'other/c.txt'], 'dir/');
    expect(await fs.exists('dir/hello.txt')).toBe(true);
    expect(await fs.exists('dir/c.txt')).toBe(true);
    expect(await fs.exists('hello.txt')).toBe(false);
    expect(await fs.exists('other/c.txt')).toBe(false);
  });

  it('renames a directory recursively', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('dir', 'newdir', { recursive: true });
    expect(fromBytes(await fs.read('newdir/a.txt'))).toBe('aaa');
    expect(fromBytes(await fs.read('newdir/b.txt'))).toBe('bbb');
    expect(await fs.exists('dir/a.txt')).toBe(false);
  });
});

describe('move atomicity', () => {
  it('creates a single commit', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'moved.txt');
    expect(await fs.exists('moved.txt')).toBe(true);
    expect(await fs.exists('hello.txt')).toBe(false);
    // Previous commit has the original
    const prev = await fs.back(1);
    expect(await prev.exists('hello.txt')).toBe(true);
    expect(await prev.exists('moved.txt')).toBe(false);
  });
});

describe('move dry run', () => {
  it('does not modify files', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'renamed.txt', { dryRun: true });
    expect(await fs.exists('hello.txt')).toBe(true);
    expect(await fs.exists('renamed.txt')).toBe(false);
    expect(fs.changes).not.toBeNull();
    expect(fs.changes!.add.length).toBe(1);
    expect(fs.changes!.delete.length).toBe(1);
  });

  it('reports correct paths', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'renamed.txt', { dryRun: true });
    const addPaths = fs.changes!.add.map((e) => e.path);
    const delPaths = fs.changes!.delete.map((e) => e.path);
    expect(addPaths).toContain('renamed.txt');
    expect(delPaths).toContain('hello.txt');
  });
});

describe('move errors', () => {
  it('rejects same source and dest', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    await expect(fs.move('hello.txt', 'hello.txt')).rejects.toThrow(/same/i);
  });

  it('rejects nonexistent source', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    await expect(fs.move('missing.txt', 'dest.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('rejects directory without recursive', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    await expect(fs.move('dir', 'newdir')).rejects.toThrow(IsADirectoryError);
  });

  it('rejects write to tag (read-only)', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    const branchFs = await store.branches.get('main');
    await store.tags.set('v1', branchFs);
    const tagFs = await store.tags.get('v1');
    await expect(tagFs.move('hello.txt', 'renamed.txt')).rejects.toThrow(PermissionError);
  });
});

describe('move message', () => {
  it('uses custom commit message', async () => {
    const { store, tmpDir } = await storeWithFiles();
    _tmpDir = tmpDir;
    let fs = await store.branches.get('main');
    fs = await fs.move('hello.txt', 'renamed.txt', { message: 'renamed hello' });
    const msg = await fs.getMessage();
    expect(msg).toContain('renamed hello');
  });
});
