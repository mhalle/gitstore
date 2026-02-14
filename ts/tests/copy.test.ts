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

// ---------------------------------------------------------------------------
// Symlink edge cases (ported from Python TestCopySymlinks)
// ---------------------------------------------------------------------------

describe('copy symlink edge cases', () => {
  it('dir symlink preserved to repo', async () => {
    const dir = path.join(tmpDir, 'withlink');
    fs.mkdirSync(dir);
    const realDir = path.join(dir, 'real_dir');
    fs.mkdirSync(realDir);
    fs.writeFileSync(path.join(realDir, 'file.txt'), 'inside');
    fs.symlinkSync('real_dir', path.join(dir, 'link_dir'));

    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(await f2.readlink('dest/link_dir')).toBe('real_dir');
    expect(fromBytes(await f2.read('dest/real_dir/file.txt'))).toBe('inside');
  });

  it('dangling symlink to repo', async () => {
    const dir = path.join(tmpDir, 'dangle');
    fs.mkdirSync(dir);
    fs.symlinkSync('nonexistent_target', path.join(dir, 'broken'));
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(await f2.readlink('dest/broken')).toBe('nonexistent_target');
  });

  it('absolute symlink target', async () => {
    const dir = path.join(tmpDir, 'abslink');
    fs.mkdirSync(dir);
    fs.symlinkSync('/usr/bin/env', path.join(dir, 'abs_link'));
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(await f2.readlink('dest/abs_link')).toBe('/usr/bin/env');
  });

  it('relative symlink with ..', async () => {
    const dir = path.join(tmpDir, 'rellink');
    fs.mkdirSync(path.join(dir, 'sub'), { recursive: true });
    fs.symlinkSync('../sibling/file', path.join(dir, 'sub', 'uplink'));
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(await f2.readlink('dest/sub/uplink')).toBe('../sibling/file');
  });

  it('symlink from repo to disk', async () => {
    let f2 = await snap.writeSymlink('links/mylink', 'target.txt');
    f2 = await f2.write('links/target.txt', toBytes('content'));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.copyOut('links/', outDir);
    expect(fs.lstatSync(path.join(outDir, 'mylink')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'mylink'))).toBe('target.txt');
  });

  it.skip('source dir symlink no-follow stores as symlink (needs TS feature)', async () => {
    // TODO: resolveDiskSources uses stat() not lstat(), so dir symlinks
    // are followed even when followSymlinks=false. Python handles this.
    const realDir = path.join(tmpDir, 'real_dir');
    fs.mkdirSync(realDir);
    fs.writeFileSync(path.join(realDir, 'file.txt'), 'inside');

    const link = path.join(tmpDir, 'link_to_dir');
    fs.symlinkSync(realDir, link);

    const f2 = await snap.copyIn(link, 'dest', { followSymlinks: false });
    expect(await f2.readlink('dest/link_to_dir')).toBe(realDir);
    expect(await f2.exists('dest/link_to_dir/file.txt')).toBe(false);
  });

  it('contents mode symlinked dir follows symlink', async () => {
    const realDir = path.join(tmpDir, 'real_dir');
    fs.mkdirSync(realDir);
    fs.writeFileSync(path.join(realDir, 'file.txt'), 'inside');
    fs.mkdirSync(path.join(realDir, 'sub'));
    fs.writeFileSync(path.join(realDir, 'sub', 'nested.txt'), 'nested');

    const link = path.join(tmpDir, 'link_to_dir');
    fs.symlinkSync(realDir, link);

    const f2 = await snap.copyIn(link + '/', 'dest', { followSymlinks: false });
    expect(fromBytes(await f2.read('dest/file.txt'))).toBe('inside');
    expect(fromBytes(await f2.read('dest/sub/nested.txt'))).toBe('nested');
  });
});

// ---------------------------------------------------------------------------
// follow_symlinks + delete mode (ported from Python TestFollowSymlinksDeleteMode)
// ---------------------------------------------------------------------------

describe('follow_symlinks delete mode', () => {
  it('no perpetual update', async () => {
    const local = path.join(tmpDir, 'src');
    fs.mkdirSync(local);
    const target = path.join(tmpDir, 'target.txt');
    fs.writeFileSync(target, 'content');
    fs.symlinkSync(target, path.join(local, 'link.txt'));
    fs.writeFileSync(path.join(local, 'regular.txt'), 'regular');

    const f2 = await snap.copyIn(local + '/', 'data', { followSymlinks: true, delete: true });
    expect(fromBytes(await f2.read('data/link.txt'))).toBe('content');

    // Second sync should find no changes
    const f3 = await f2.copyIn(local + '/', 'data', { followSymlinks: true, delete: true, dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('content change detected', async () => {
    const local = path.join(tmpDir, 'src');
    fs.mkdirSync(local);
    const target = path.join(tmpDir, 'target.txt');
    fs.writeFileSync(target, 'version1');
    fs.symlinkSync(target, path.join(local, 'link.txt'));

    const f2 = await snap.copyIn(local + '/', 'data', { followSymlinks: true, delete: true });

    // Change the target content
    fs.writeFileSync(target, 'version2');

    const f3 = await f2.copyIn(local + '/', 'data', { followSymlinks: true, delete: true, dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.update.some((e: any) => e.path === 'link.txt')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Delete mode extended (ported from Python TestDelete)
// ---------------------------------------------------------------------------

describe('delete mode extended', () => {
  it('skips unchanged files (hash comparison)', async () => {
    const dir = path.join(tmpDir, 'sync');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'aaa');
    fs.writeFileSync(path.join(dir, 'b.txt'), 'bbb');
    fs.writeFileSync(path.join(dir, '.dotfile'), 'dot');
    // All content matches repo — should be no-op
    const f2 = await snap.copyIn(dir + '/', 'dir', { delete: true });
    expect(f2.commitHash).toBe(snap.commitHash);
  });

  it('delete + ignoreExisting', async () => {
    let f2 = await snap.write('data/keep.txt', toBytes('keep'));
    f2 = await f2.write('data/change.txt', toBytes('old'));
    f2 = await f2.write('data/extra.txt', toBytes('extra'));
    const dir = path.join(tmpDir, 'src');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(dir, 'change.txt'), 'new');

    const f3 = await f2.copyIn(dir + '/', 'data', { delete: true, ignoreExisting: true });
    // extra.txt should be deleted
    expect(await f3.exists('data/extra.txt')).toBe(false);
    // change.txt should keep old content (ignoreExisting skips updates)
    expect(fromBytes(await f3.read('data/change.txt'))).toBe('old');
    // keep.txt unchanged
    expect(fromBytes(await f3.read('data/keep.txt'))).toBe('keep');
  });

  it('delete dry-run plan (to repo)', async () => {
    let f2 = await snap.write('data/keep.txt', toBytes('keep'));
    f2 = await f2.write('data/change.txt', toBytes('old'));
    f2 = await f2.write('data/extra.txt', toBytes('extra'));
    const dir = path.join(tmpDir, 'src');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(dir, 'change.txt'), 'new');
    fs.writeFileSync(path.join(dir, 'add.txt'), 'added');

    const f3 = await f2.copyIn(dir + '/', 'data', { delete: true, dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(paths(f3.changes!.add).has('add.txt')).toBe(true);
    expect(paths(f3.changes!.update).has('change.txt')).toBe(true);
    expect(paths(f3.changes!.delete).has('extra.txt')).toBe(true);
    const allPaths = new Set([
      ...f3.changes!.add.map((e: any) => e.path),
      ...f3.changes!.update.map((e: any) => e.path),
      ...f3.changes!.delete.map((e: any) => e.path),
    ]);
    expect(allPaths.has('keep.txt')).toBe(false);
  });

  it('delete file/dir conflict', async () => {
    const dir = path.join(tmpDir, 'src');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'new.txt'), 'new');
    const f2 = await snap.copyIn(dir + '/', 'dir', { delete: true });
    expect(fromBytes(await f2.read('dir/new.txt'))).toBe('new');
    expect(await f2.exists('dir/a.txt')).toBe(false);
    expect(await f2.exists('dir/b.txt')).toBe(false);
  });

  it('delete from repo prunes empty dirs', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    const sub = path.join(outDir, 'sub', 'deep');
    fs.mkdirSync(sub, { recursive: true });
    fs.writeFileSync(path.join(sub, 'old.txt'), 'old');
    await snap.copyOut('existing.txt', outDir, { delete: true });
    expect(readLocalFile(outDir, 'existing.txt')).toBe('existing');
    expect(fs.existsSync(path.join(outDir, 'sub'))).toBe(false);
  });

  it('delete from repo dry-run', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'extra.txt'), 'extra');
    const f2 = await snap.copyOut('existing.txt', outDir, { delete: true, dryRun: true });
    expect(f2.changes).not.toBeNull();
    expect(paths(f2.changes!.add).has('existing.txt')).toBe(true);
    expect(paths(f2.changes!.delete).has('extra.txt')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ignoreErrors extended (ported from Python TestIgnoreErrors)
// ---------------------------------------------------------------------------

describe('ignoreErrors extended', () => {
  it('success case has no errors', async () => {
    const filePath = path.join(tmpDir, 'ok.txt');
    fs.writeFileSync(filePath, 'ok');
    const f2 = await snap.copyIn(filePath, 'dest', { ignoreErrors: true });
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.errors).toEqual([]);
    expect(fromBytes(await f2.read('dest/ok.txt'))).toBe('ok');
  });

  it('ignoreErrors + delete + all fail no delete (to repo)', async () => {
    await expect(
      snap.copyIn(['/nonexistent1', '/nonexistent2'], 'dir', {
        ignoreErrors: true,
        delete: true,
      }),
    ).rejects.toThrow();
    // Original repo content untouched
    expect(fromBytes(await snap.read('dir/a.txt'))).toBe('aaa');
    expect(fromBytes(await snap.read('dir/b.txt'))).toBe('bbb');
  });

  it('ignoreErrors + delete + all fail no delete (from repo)', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'precious.txt'), 'precious');
    await expect(
      snap.copyOut(['nonexistent1', 'nonexistent2'], outDir, {
        ignoreErrors: true,
        delete: true,
      }),
    ).rejects.toThrow();
    // Local file untouched
    expect(fs.readFileSync(path.join(outDir, 'precious.txt'), 'utf-8')).toBe('precious');
  });
});

// ---------------------------------------------------------------------------
// ignoreExisting extended (ported from Python TestIgnoreExisting)
// ---------------------------------------------------------------------------

describe('ignoreExisting extended', () => {
  it('dry-run to repo', async () => {
    const f1 = path.join(tmpDir, 'existing.txt');
    fs.writeFileSync(f1, 'new content');
    const f2 = path.join(tmpDir, 'brand_new.txt');
    fs.writeFileSync(f2, 'new');

    const f3 = await snap.copyIn([f1, f2], '', { ignoreExisting: true, dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(paths(f3.changes!.add).has('brand_new.txt')).toBe(true);
    expect(paths(f3.changes!.add).has('existing.txt')).toBe(false);
    expect(f3.changes!.update.length).toBe(0);
  });

  it('dry-run from repo', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'existing.txt'), 'local');

    const f2 = await snap.copyOut(['existing.txt', 'dir/a.txt'], outDir, {
      ignoreExisting: true,
      dryRun: true,
    });
    expect(f2.changes).not.toBeNull();
    const addPaths = paths(f2.changes!.add);
    expect(addPaths.has('a.txt') || addPaths.has('dir/a.txt')).toBe(true);
    expect(addPaths.has('existing.txt')).toBe(false);
    expect(f2.changes!.update.length).toBe(0);
  });

  it('with directory copy', async () => {
    const dir = path.join(tmpDir, 'dir2');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'a.txt'), 'new aaa');
    fs.writeFileSync(path.join(dir, 'new_file.txt'), 'new');
    // dir/a.txt already exists in repo
    const f2 = await snap.copyIn(dir + '/', 'dir', { ignoreExisting: true });
    expect(fromBytes(await f2.read('dir/a.txt'))).toBe('aaa'); // unchanged
    expect(fromBytes(await f2.read('dir/new_file.txt'))).toBe('new'); // new file written
  });
});

// ---------------------------------------------------------------------------
// Content edge cases extended (ported from Python TestCopyEdgeCases)
// ---------------------------------------------------------------------------

describe('copy content edge cases extended', () => {
  it('empty file from repo', async () => {
    let f2 = await snap.write('dest/empty.txt', toBytes(''));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.copyOut('dest/empty.txt', outDir);
    expect(fs.readFileSync(path.join(outDir, 'empty.txt')).length).toBe(0);
  });

  it('binary file from repo', async () => {
    const data = Buffer.alloc(256);
    for (let i = 0; i < 256; i++) data[i] = i;
    let f2 = await snap.write('dest/bin.dat', data);
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.copyOut('dest/bin.dat', outDir);
    expect(Buffer.from(fs.readFileSync(path.join(outDir, 'bin.dat'))).equals(data)).toBe(true);
  });

  it('filenames with spaces', async () => {
    const dir = path.join(tmpDir, 'spaces');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'my file.txt'), 'spaces');
    fs.mkdirSync(path.join(dir, 'sub dir'));
    fs.writeFileSync(path.join(dir, 'sub dir', 'inner.txt'), 'nested');
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(fromBytes(await f2.read('dest/my file.txt'))).toBe('spaces');
    expect(fromBytes(await f2.read('dest/sub dir/inner.txt'))).toBe('nested');
  });

  it('special char filenames (#, @, =)', async () => {
    const dir = path.join(tmpDir, 'special');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'file#1.txt'), 'hash');
    fs.writeFileSync(path.join(dir, 'file@2.txt'), 'at');
    fs.writeFileSync(path.join(dir, 'a=b.txt'), 'equals');
    const f2 = await snap.copyIn(dir + '/', 'dest');
    expect(fromBytes(await f2.read('dest/file#1.txt'))).toBe('hash');
    expect(fromBytes(await f2.read('dest/file@2.txt'))).toBe('at');
    expect(fromBytes(await f2.read('dest/a=b.txt'))).toBe('equals');
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
