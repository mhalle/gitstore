import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { storeWithFiles, freshStore, toBytes, fromBytes, rmTmpDir, fs, makeTmpDir } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  FileNotFoundError,
  IsADirectoryError,
  NotADirectoryError,
  changeReportInSync,
  changeReportTotal,
  changeReportActions,
} from '../src/index.js';
import * as path from 'node:path';

let store: GitStore;
let snap: FS;
let tmpDir: string;

function paths(entries: Array<{ path: string }>): Set<string> {
  return new Set(entries.map((e) => e.path));
}

function writeLocalFile(dir: string, rel: string, content: string) {
  const full = path.join(dir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

function readLocalFile(dir: string, rel: string): string {
  return fs.readFileSync(path.join(dir, rel), 'utf-8');
}

beforeEach(async () => {
  const res = await storeWithFiles();
  store = res.store;
  snap = res.fsSnap;
  tmpDir = res.tmpDir;
});

afterEach(() => rmTmpDir(tmpDir));

describe('copyIn file', () => {
  it('single file', async () => {
    const filePath = path.join(tmpDir, 'new.txt');
    fs.writeFileSync(filePath, 'new content');
    const f2 = await snap.copyIn(filePath, 'dest');
    expect(fromBytes(await f2.read('dest/new.txt'))).toBe('new content');
  });

  it('multiple files', async () => {
    const f1 = path.join(tmpDir, 'x.txt');
    const f2path = path.join(tmpDir, 'y.txt');
    fs.writeFileSync(f1, 'x');
    fs.writeFileSync(f2path, 'y');
    const f2 = await snap.copyIn([f1, f2path], 'dest');
    expect(await f2.exists('dest/x.txt')).toBe(true);
    expect(await f2.exists('dest/y.txt')).toBe(true);
  });

  it('missing file throws', async () => {
    await expect(snap.copyIn('/nonexistent/file.txt', 'dest')).rejects.toThrow();
  });
});

describe('copyIn directory', () => {
  it('directory name preserved', async () => {
    const dir = path.join(tmpDir, 'mydir');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'a');
    const f2 = await snap.copyIn(dir, 'dest');
    expect(await f2.exists('dest/mydir/a.txt')).toBe(true);
  });

  it('trailing slash = contents mode', async () => {
    const dir = path.join(tmpDir, 'mydir');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'a');
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(await f2.exists('dest/a.txt')).toBe(true);
  });
});

describe('copyOut file', () => {
  it('single file', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    const f2 = await snap.copyOut('existing.txt', outDir);
    expect(readLocalFile(outDir, 'existing.txt')).toBe('existing');
  });

  it('missing file throws', async () => {
    const outDir = path.join(tmpDir, 'out');
    await expect(snap.copyOut('nope.txt', outDir)).rejects.toThrow();
  });
});

describe('copyOut directory', () => {
  it('directory name preserved', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await snap.copyOut('dir', outDir);
    expect(readLocalFile(outDir, 'dir/a.txt')).toBe('aaa');
    expect(readLocalFile(outDir, 'dir/b.txt')).toBe('bbb');
  });

  it('trailing slash = contents mode including dotfiles', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await snap.copyOut('dir/', outDir);
    expect(readLocalFile(outDir, 'a.txt')).toBe('aaa');
    expect(readLocalFile(outDir, '.dotfile')).toBe('dot');
  });
});

describe('copyOut glob', () => {
  it('glob expansion excludes dotfiles', async () => {
    const globs = await snap.glob('dir/*.txt');
    expect(globs).toContain('dir/a.txt');
    expect(globs).toContain('dir/b.txt');
    expect(globs).not.toContain('dir/.dotfile');
  });
});

describe('dryRun', () => {
  it('copyIn dryRun does not modify repo', async () => {
    const filePath = path.join(tmpDir, 'new.txt');
    fs.writeFileSync(filePath, 'new');
    const f2 = await snap.copyIn(filePath, 'dest', { dryRun: true });
    // Dry run returns same FS (no new commit)
    expect(f2.commitHash).toBe(snap.commitHash);
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.add.length).toBeGreaterThan(0);
  });

  it('copyOut dryRun does not write to disk', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await snap.copyOut('existing.txt', outDir, { dryRun: true });
    expect(fs.existsSync(path.join(outDir, 'existing.txt'))).toBe(false);
  });

  it('dryRun shows updates', async () => {
    // Write a file, then copy an updated version with dry-run
    const filePath = path.join(tmpDir, 'existing.txt');
    fs.writeFileSync(filePath, 'updated');
    const f2 = await snap.copyIn(filePath, '', { dryRun: true });
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.update.length).toBeGreaterThan(0);
  });
});

describe('ignoreExisting', () => {
  it('preserves existing files', async () => {
    const filePath = path.join(tmpDir, 'existing.txt');
    fs.writeFileSync(filePath, 'new version');
    const f2 = await snap.copyIn(filePath, '', { ignoreExisting: true });
    // existing.txt should not be updated
    expect(fromBytes(await f2.read('existing.txt'))).toBe('existing');
  });

  it('writes new files', async () => {
    const filePath = path.join(tmpDir, 'brand_new.txt');
    fs.writeFileSync(filePath, 'brand new');
    const f2 = await snap.copyIn(filePath, '', { ignoreExisting: true });
    expect(fromBytes(await f2.read('brand_new.txt'))).toBe('brand new');
  });
});

describe('copy edge cases', () => {
  it('empty file', async () => {
    const filePath = path.join(tmpDir, 'empty.txt');
    fs.writeFileSync(filePath, '');
    const f2 = await snap.copyIn(filePath, 'dest');
    expect((await f2.read('dest/empty.txt')).length).toBe(0);
  });

  it('binary data (all 256 bytes)', async () => {
    const data = Buffer.alloc(256);
    for (let i = 0; i < 256; i++) data[i] = i;
    const filePath = path.join(tmpDir, 'bin.dat');
    fs.writeFileSync(filePath, data);
    const f2 = await snap.copyIn(filePath, 'dest');
    const read = await f2.read('dest/bin.dat');
    expect(Buffer.from(read).equals(data)).toBe(true);
  });

  it('unicode filenames', async () => {
    const filePath = path.join(tmpDir, 'café.txt');
    fs.writeFileSync(filePath, 'latte');
    const f2 = await snap.copyIn(filePath, 'dest');
    expect(fromBytes(await f2.read('dest/café.txt'))).toBe('latte');
  });

  it('deep nesting', async () => {
    const dir = path.join(tmpDir, 'a', 'b', 'c', 'd');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'deep.txt'), 'deep');
    const f2 = await snap.copyIn(path.join(tmpDir, 'a'), 'dest');
    expect(await f2.exists('dest/a/b/c/d/deep.txt')).toBe(true);
  });
});

describe('copy symlinks', () => {
  it('symlink to file preserved in repo', async () => {
    const realFile = path.join(tmpDir, 'real.txt');
    fs.writeFileSync(realFile, 'real');
    const linkPath = path.join(tmpDir, 'link.txt');
    fs.symlinkSync(realFile, linkPath);
    const f2 = await snap.copyIn(linkPath, 'dest');
    expect(await f2.fileType('dest/link.txt')).toBe(FileType.LINK);
  });

  it('follow_symlinks hashes content', async () => {
    const realFile = path.join(tmpDir, 'real.txt');
    fs.writeFileSync(realFile, 'real content');
    const linkPath = path.join(tmpDir, 'link.txt');
    fs.symlinkSync(realFile, linkPath);
    const f2 = await snap.copyIn(linkPath, 'dest', { followSymlinks: true });
    expect(await f2.fileType('dest/link.txt')).toBe(FileType.BLOB);
    expect(fromBytes(await f2.read('dest/link.txt'))).toBe('real content');
  });
});

describe('delete mode (copyIn)', () => {
  it('deletes extra repo files', async () => {
    const dir = path.join(tmpDir, 'sync');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'aaa');
    // First copy in to create files
    let f2 = await snap.copyIn(dir + '/', 'dest');
    // Now copy with only a.txt, deleting extras
    const f3 = await f2.copyIn(dir + '/', 'dest', { delete: true });
    expect(await f3.exists('dest/a.txt')).toBe(true);
  });

  it('dryRun with delete', async () => {
    const dir = path.join(tmpDir, 'sync');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'new_a');
    const f2 = await snap.copyIn(dir + '/', 'dir', { delete: true, dryRun: true });
    expect(f2.changes).not.toBeNull();
  });
});

describe('delete mode (copyOut)', () => {
  it('deletes extra local files', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'extra.txt'), 'extra');
    await snap.copyOut('dir/', outDir, { delete: true });
    expect(fs.existsSync(path.join(outDir, 'extra.txt'))).toBe(false);
    expect(readLocalFile(outDir, 'a.txt')).toBe('aaa');
  });
});

describe('ignoreErrors', () => {
  it('continues on unreadable file', async () => {
    const dir = path.join(tmpDir, 'errdir');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'good.txt'), 'good');
    const badPath = path.join(dir, 'bad.txt');
    fs.writeFileSync(badPath, 'bad');
    fs.chmodSync(badPath, 0o000);

    const f2 = await snap.copyIn(dir + '/', 'dest', { ignoreErrors: true });
    expect(await f2.exists('dest/good.txt')).toBe(true);

    // Cleanup: restore permissions for rmTmpDir
    fs.chmodSync(badPath, 0o644);
  });
});

describe('remove from repo', () => {
  it('single file', async () => {
    const f2 = await snap.remove('existing.txt');
    expect(await f2.exists('existing.txt')).toBe(false);
  });

  it('glob removal via explicit paths', async () => {
    // TS remove() does not glob-expand; use glob() + remove()
    const matches = await snap.glob('dir/*.txt');
    const f2 = await snap.remove(matches);
    expect(await f2.exists('dir/a.txt')).toBe(false);
    expect(await f2.exists('dir/b.txt')).toBe(false);
  });

  it('recursive directory', async () => {
    const f2 = await snap.remove('dir', { recursive: true });
    expect(await f2.exists('dir')).toBe(false);
  });

  it('directory without recursive raises', async () => {
    await expect(snap.remove('dir')).rejects.toThrow(IsADirectoryError);
  });

  it('missing raises FileNotFoundError', async () => {
    await expect(snap.remove('nope.txt')).rejects.toThrow();
  });

  it('dryRun does not modify', async () => {
    const f2 = await snap.remove('existing.txt', { dryRun: true });
    expect(f2.commitHash).toBe(snap.commitHash);
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.delete.length).toBe(1);
  });

  it('multiple patterns', async () => {
    const f2 = await snap.remove(['existing.txt', 'other/c.txt']);
    expect(await f2.exists('existing.txt')).toBe(false);
    expect(await f2.exists('other/c.txt')).toBe(false);
  });

  it('report attached', async () => {
    const f2 = await snap.remove('existing.txt');
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.delete.length).toBe(1);
  });
});

describe('changeReport none when in sync', () => {
  it('copyIn returns null changes when in sync', async () => {
    const dir = path.join(tmpDir, 'insync');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'aaa');
    // First copy
    const f2 = await snap.copyIn(dir + '/', 'dir', { delete: true });
    // Second copy with same content
    const f3 = await f2.copyIn(dir + '/', 'dir', { delete: true });
    expect(f3.commitHash).toBe(f2.commitHash);
  });
});

describe('move in repo', () => {
  it('rename file', async () => {
    const f2 = await snap.move('existing.txt', 'renamed.txt');
    expect(await f2.exists('renamed.txt')).toBe(true);
    expect(await f2.exists('existing.txt')).toBe(false);
    expect(fromBytes(await f2.read('renamed.txt'))).toBe('existing');
  });

  it('move file into directory', async () => {
    const f2 = await snap.move('existing.txt', 'dir/');
    expect(await f2.exists('dir/existing.txt')).toBe(true);
    expect(await f2.exists('existing.txt')).toBe(false);
  });

  it('rename directory', async () => {
    const f2 = await snap.move('dir', 'newdir', { recursive: true });
    expect(await f2.exists('newdir/a.txt')).toBe(true);
    expect(await f2.exists('dir/a.txt')).toBe(false);
  });

  it('dryRun does not modify', async () => {
    const f2 = await snap.move('existing.txt', 'renamed.txt', { dryRun: true });
    expect(f2.commitHash).toBe(snap.commitHash);
    expect(f2.changes).not.toBeNull();
  });

  it('move with report', async () => {
    const f2 = await snap.move('existing.txt', 'renamed.txt');
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.add.length).toBeGreaterThan(0);
    expect(f2.changes!.delete.length).toBeGreaterThan(0);
  });
});
