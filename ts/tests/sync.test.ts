import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  changeReportInSync,
  changeReportTotal,
  changeReportActions,
} from '../src/index.js';
import * as path from 'node:path';

let store: GitStore;
let snap: FS;
let tmpDir: string;
let localDir: string;

function writeLocal(rel: string, content: string) {
  const full = path.join(localDir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

function readLocal(rel: string): string {
  return fs.readFileSync(path.join(localDir, rel), 'utf-8');
}

function existsLocal(rel: string): boolean {
  return fs.existsSync(path.join(localDir, rel));
}

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
  snap = await store.branches.get('main');

  localDir = path.join(tmpDir, 'local');
  fs.mkdirSync(localDir);
  fs.writeFileSync(path.join(localDir, 'a.txt'), 'alpha');
  fs.writeFileSync(path.join(localDir, 'b.txt'), 'beta');
});

afterEach(() => rmTmpDir(tmpDir));

describe('syncIn (disk → repo)', () => {
  it('basic sync', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/a.txt'))).toBe('alpha');
    expect(fromBytes(await f2.read('data/b.txt'))).toBe('beta');
  });

  it('deletes repo files not in local', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Add extra file to repo
    f2 = await f2.write('data/extra.txt', toBytes('extra'));
    // Sync again — extra should be deleted
    const f3 = await f2.syncIn(localDir, 'data');
    expect(await f3.exists('data/extra.txt')).toBe(false);
  });

  it('overwrites changed files', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Modify local file
    fs.writeFileSync(path.join(localDir, 'a.txt'), 'alpha_v2');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('data/a.txt'))).toBe('alpha_v2');
  });

  it('noop when identical', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(f3.commitHash).toBe(f2.commitHash);
  });

  it('custom message', async () => {
    const f2 = await snap.syncIn(localDir, 'data', { message: 'sync import' });
    expect(await f2.getMessage()).toBe('sync import');
  });

  it('auto commit message says sync not cp', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const msg = await f2.getMessage();
    expect(msg).toContain('sync');
    expect(msg).not.toContain(' cp ');
  });

  it('nested directories', async () => {
    const nested = path.join(localDir, 'sub', 'deep');
    fs.mkdirSync(nested, { recursive: true });
    fs.writeFileSync(path.join(nested, 'x.txt'), 'deep');
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/sub/deep/x.txt'))).toBe('deep');
  });

  it('empty repo path syncs to root', async () => {
    const f2 = await snap.syncIn(localDir, '');
    expect(fromBytes(await f2.read('a.txt'))).toBe('alpha');
  });

  it('symlink preserved', async () => {
    const realFile = path.join(localDir, 'real.txt');
    fs.writeFileSync(realFile, 'real');
    fs.symlinkSync('real.txt', path.join(localDir, 'link.txt'));
    const f2 = await snap.syncIn(localDir, 'data');
    expect(await f2.fileType('data/link.txt')).toBe(FileType.LINK);
  });
});

describe('syncOut (repo → disk)', () => {
  it('basic sync', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(readLocal('../out/a.txt')).toBe('alpha');
    expect(readLocal('../out/b.txt')).toBe('beta');
  });

  it('deletes local files not in repo', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'extra.txt'), 'extra');
    await f2.syncOut('data', outDir);
    expect(fs.existsSync(path.join(outDir, 'extra.txt'))).toBe(false);
  });

  it('overwrites changed files', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'a.txt'), 'old');
    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'a.txt'), 'utf-8')).toBe('alpha');
  });

  it('noop when identical', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    const f3 = await f2.syncOut('data', outDir);
    // Second sync should detect no changes
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('nested directories', async () => {
    const nested = path.join(localDir, 'sub', 'deep');
    fs.mkdirSync(nested, { recursive: true });
    fs.writeFileSync(path.join(nested, 'x.txt'), 'deep');
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'sub/deep/x.txt'), 'utf-8')).toBe('deep');
  });

  it('cleans empty dirs after delete', async () => {
    // Sync with files in subdir, then remove from repo, sync again
    const subdir = path.join(localDir, 'sub');
    fs.mkdirSync(subdir);
    fs.writeFileSync(path.join(subdir, 'x.txt'), 'x');
    let f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    // Remove subdir files from local
    fs.unlinkSync(path.join(localDir, 'sub/x.txt'));
    fs.rmdirSync(path.join(localDir, 'sub'));
    f2 = await f2.syncIn(localDir, 'data');
    await f2.syncOut('data', outDir);
    expect(fs.existsSync(path.join(outDir, 'sub'))).toBe(false);
  });

  it('creates output dir', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'newout');
    await f2.syncOut('data', outDir);
    expect(fs.existsSync(outDir)).toBe(true);
  });

  it('symlink preserved', async () => {
    fs.writeFileSync(path.join(localDir, 'real.txt'), 'real');
    fs.symlinkSync('real.txt', path.join(localDir, 'link.txt'));
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'link.txt')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'link.txt'))).toBe('real.txt');
  });
});

describe('syncIn dryRun', () => {
  it('returns report without modifying', async () => {
    const f2 = await snap.syncIn(localDir, 'data', { dryRun: true });
    expect(f2.commitHash).toBe(snap.commitHash);
    expect(f2.changes).not.toBeNull();
    expect(f2.changes!.add.length).toBeGreaterThan(0);
  });

  it('detects updates', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    fs.writeFileSync(path.join(localDir, 'a.txt'), 'changed');
    const f3 = await f2.syncIn(localDir, 'data', { dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.update.length).toBeGreaterThan(0);
  });

  it('returns null when in sync', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const f3 = await f2.syncIn(localDir, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });
});

describe('syncOut dryRun', () => {
  it('returns report without writing', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.add.length).toBeGreaterThan(0);
    // Should not have written files
    expect(fs.existsSync(path.join(outDir, 'a.txt'))).toBe(false);
  });

  it('returns null when in sync', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });
});

describe('changeReport actions', () => {
  it('actions sorted by path', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    if (f2.changes) {
      const actions = changeReportActions(f2.changes);
      const paths = actions.map((a) => a.path);
      expect(paths).toEqual([...paths].sort());
    }
  });

  it('empty plan', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const f3 = await f2.syncIn(localDir, 'data');
    if (f3.changes) {
      expect(changeReportInSync(f3.changes)).toBe(true);
      expect(changeReportTotal(f3.changes)).toBe(0);
      expect(changeReportActions(f3.changes)).toEqual([]);
    }
  });
});

describe('sync symlinks', () => {
  it('symlink target change detected (sync in)', async () => {
    fs.writeFileSync(path.join(localDir, 'real.txt'), 'real');
    fs.symlinkSync('real.txt', path.join(localDir, 'link.txt'));
    let f2 = await snap.syncIn(localDir, 'data');

    // Change symlink target
    fs.unlinkSync(path.join(localDir, 'link.txt'));
    fs.symlinkSync('other.txt', path.join(localDir, 'link.txt'));
    const f3 = await f2.syncIn(localDir, 'data');
    expect(await f3.readlink('data/link.txt')).toBe('other.txt');
  });

  it('symlink replaces regular file', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Replace a.txt with a symlink
    fs.unlinkSync(path.join(localDir, 'a.txt'));
    fs.symlinkSync('b.txt', path.join(localDir, 'a.txt'));
    const f3 = await f2.syncIn(localDir, 'data');
    expect(await f3.fileType('data/a.txt')).toBe(FileType.LINK);
  });

  it('regular file replaces symlink', async () => {
    fs.symlinkSync('b.txt', path.join(localDir, 'link.txt'));
    let f2 = await snap.syncIn(localDir, 'data');
    // Replace symlink with regular file
    fs.unlinkSync(path.join(localDir, 'link.txt'));
    fs.writeFileSync(path.join(localDir, 'link.txt'), 'now a file');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(await f3.fileType('data/link.txt')).toBe(FileType.BLOB);
  });
});

describe('sync file/directory collisions', () => {
  it('file replaces directory (syncIn)', async () => {
    // Create dir in repo
    const subdir = path.join(localDir, 'sub');
    fs.mkdirSync(subdir);
    fs.writeFileSync(path.join(subdir, 'x.txt'), 'x');
    let f2 = await snap.syncIn(localDir, 'data');

    // Replace dir with file
    fs.unlinkSync(path.join(subdir, 'x.txt'));
    fs.rmdirSync(subdir);
    fs.writeFileSync(path.join(localDir, 'sub'), 'now a file');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('data/sub'))).toBe('now a file');
  });

  it('directory replaces file (syncIn)', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Replace a.txt with a directory
    fs.unlinkSync(path.join(localDir, 'a.txt'));
    fs.mkdirSync(path.join(localDir, 'a.txt'));
    fs.writeFileSync(path.join(localDir, 'a.txt', 'nested.txt'), 'nested');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('data/a.txt/nested.txt'))).toBe('nested');
  });
});

describe('sync content edge cases', () => {
  it('empty file', async () => {
    fs.writeFileSync(path.join(localDir, 'empty.txt'), '');
    const f2 = await snap.syncIn(localDir, 'data');
    expect((await f2.read('data/empty.txt')).length).toBe(0);
  });

  it('binary file', async () => {
    const data = Buffer.alloc(256);
    for (let i = 0; i < 256; i++) data[i] = i;
    fs.writeFileSync(path.join(localDir, 'bin.dat'), data);
    const f2 = await snap.syncIn(localDir, 'data');
    const read = await f2.read('data/bin.dat');
    expect(Buffer.from(read).equals(data)).toBe(true);
  });

  it('same content different paths', async () => {
    fs.writeFileSync(path.join(localDir, 'dup1.txt'), 'same');
    fs.writeFileSync(path.join(localDir, 'dup2.txt'), 'same');
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/dup1.txt'))).toBe('same');
    expect(fromBytes(await f2.read('data/dup2.txt'))).toBe('same');
    // Same content = same hash
    const h1 = await f2.objectHash('data/dup1.txt');
    const h2 = await f2.objectHash('data/dup2.txt');
    expect(h1).toBe(h2);
  });

  it('whitespace-only difference detected', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    fs.writeFileSync(path.join(localDir, 'a.txt'), 'alpha ');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('data/a.txt'))).toBe('alpha ');
    expect(f3.commitHash).not.toBe(f2.commitHash);
  });
});

describe('sync structure edge cases', () => {
  it('empty local deletes all repo files', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Clear local dir
    fs.unlinkSync(path.join(localDir, 'a.txt'));
    fs.unlinkSync(path.join(localDir, 'b.txt'));
    const f3 = await f2.syncIn(localDir, 'data');
    expect(await f3.exists('data/a.txt')).toBe(false);
    expect(await f3.exists('data/b.txt')).toBe(false);
  });

  it('empty repo deletes all local', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir);
    fs.writeFileSync(path.join(outDir, 'x.txt'), 'x');
    // Sync empty repo path
    const { store: s2, tmpDir: td } = await freshStore();
    const emptyFs = await s2.branches.get('main');
    await emptyFs.syncOut('nonexistent', outDir);
    expect(fs.existsSync(path.join(outDir, 'x.txt'))).toBe(false);
    rmTmpDir(td);
  });

  it('mixed add/update/delete', async () => {
    let f2 = await snap.syncIn(localDir, 'data');
    // Add new, modify existing, delete one
    fs.writeFileSync(path.join(localDir, 'c.txt'), 'new');
    fs.writeFileSync(path.join(localDir, 'a.txt'), 'modified');
    fs.unlinkSync(path.join(localDir, 'b.txt'));
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('data/c.txt'))).toBe('new');
    expect(fromBytes(await f3.read('data/a.txt'))).toBe('modified');
    expect(await f3.exists('data/b.txt')).toBe(false);
  });
});

describe('sync round trip', () => {
  it('round trip preserves content', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'a.txt'), 'utf-8')).toBe('alpha');
    expect(fs.readFileSync(path.join(outDir, 'b.txt'), 'utf-8')).toBe('beta');
  });

  it('idempotent sync', async () => {
    const f2 = await snap.syncIn(localDir, 'data');
    const f3 = await f2.syncIn(localDir, 'data');
    expect(f3.commitHash).toBe(f2.commitHash);
  });
});

describe('sync dryRun exact match', () => {
  it('dryRun plan matches actual sync (add)', async () => {
    const dryFs = await snap.syncIn(localDir, 'data', { dryRun: true });
    const actualFs = await snap.syncIn(localDir, 'data');

    if (dryFs.changes && actualFs.changes) {
      expect(dryFs.changes.add.length).toBe(actualFs.changes.add.length);
    }
  });
});

describe('sync delete safety', () => {
  it('does not touch files outside target', async () => {
    // Write file outside sync target
    const f2 = await snap.write('outside.txt', toBytes('safe'));
    const f3 = await f2.syncIn(localDir, 'data');
    expect(fromBytes(await f3.read('outside.txt'))).toBe('safe');
  });
});

describe('sync unicode filenames', () => {
  it('unicode roundtrip syncIn', async () => {
    fs.writeFileSync(path.join(localDir, 'café.txt'), 'latte');
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/café.txt'))).toBe('latte');
  });

  it('unicode roundtrip syncOut', async () => {
    fs.writeFileSync(path.join(localDir, 'café.txt'), 'latte');
    const f2 = await snap.syncIn(localDir, 'data');
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'café.txt'), 'utf-8')).toBe('latte');
  });

  it('spaces in filenames', async () => {
    fs.writeFileSync(path.join(localDir, 'my file.txt'), 'spaces');
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/my file.txt'))).toBe('spaces');
  });

  it('special chars in filenames', async () => {
    fs.writeFileSync(path.join(localDir, 'a+b=c.txt'), 'special');
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/a+b=c.txt'))).toBe('special');
  });
});

describe('sync stress', () => {
  it('many files sync', async () => {
    // Create 50 files
    for (let i = 0; i < 50; i++) {
      fs.writeFileSync(path.join(localDir, `file_${String(i).padStart(3, '0')}.txt`), `content_${i}`);
    }
    const f2 = await snap.syncIn(localDir, 'data');
    expect(fromBytes(await f2.read('data/file_000.txt'))).toBe('content_0');
    expect(fromBytes(await f2.read('data/file_049.txt'))).toBe('content_49');

    // Round trip
    const outDir = path.join(tmpDir, 'out');
    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'file_000.txt'), 'utf-8')).toBe('content_0');
  });

  it('large file syncs', async () => {
    const data = Buffer.alloc(1024 * 1024, 'x'); // 1MB
    fs.writeFileSync(path.join(localDir, 'large.bin'), data);
    const f2 = await snap.syncIn(localDir, 'data');
    const read = await f2.read('data/large.bin');
    expect(read.length).toBe(1024 * 1024);
  });
});

describe('sync delete at repo path', () => {
  it('repo_path is a file: sync deletes it', async () => {
    let f2 = await snap.write('target', toBytes('file'));
    f2 = await f2.syncIn(localDir, 'target');
    expect(await f2.exists('target/a.txt')).toBe(true);
    // The original file 'target' should be gone, replaced by directory contents
  });
});

describe('sync overlapping paths', () => {
  it('independent sync paths do not interfere', async () => {
    const dir2 = path.join(tmpDir, 'local2');
    fs.mkdirSync(dir2);
    fs.writeFileSync(path.join(dir2, 'c.txt'), 'charlie');

    let f2 = await snap.syncIn(localDir, 'path1');
    f2 = await f2.syncIn(dir2, 'path2');

    expect(fromBytes(await f2.read('path1/a.txt'))).toBe('alpha');
    expect(fromBytes(await f2.read('path2/c.txt'))).toBe('charlie');
  });

  it('sync to root then subpath', async () => {
    fs.writeFileSync(path.join(localDir, 'top.txt'), 'top');
    const sub = path.join(localDir, 'sub');
    fs.mkdirSync(sub);
    fs.writeFileSync(path.join(sub, 'original.txt'), 'original');

    let f2 = await snap.syncIn(localDir, '');

    // Sync different content to just the 'sub' path
    const localSub = path.join(tmpDir, 'sub_content');
    fs.mkdirSync(localSub);
    fs.writeFileSync(path.join(localSub, 'replacement.txt'), 'replaced');

    f2 = await f2.syncIn(localSub, 'sub');

    expect(fromBytes(await f2.read('top.txt'))).toBe('top');
    expect(await f2.exists('sub/original.txt')).toBe(false);
    expect(fromBytes(await f2.read('sub/replacement.txt'))).toBe('replaced');
  });
});

// ---------------------------------------------------------------------------
// Symlink edge cases (ported from Python TestSyncSymlinks)
// ---------------------------------------------------------------------------

describe('sync symlink edge cases', () => {
  it('symlinked directory stored as symlink, not followed', async () => {
    const realSub = path.join(tmpDir, 'real_sub');
    fs.mkdirSync(realSub);
    fs.writeFileSync(path.join(realSub, 'file.txt'), 'content');

    const local = path.join(tmpDir, 'symlocal');
    fs.mkdirSync(local);
    fs.symlinkSync(realSub, path.join(local, 'linked_dir'));
    fs.writeFileSync(path.join(local, 'regular.txt'), 'regular');

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/linked_dir')).toBe(realSub);
    expect(fromBytes(await f2.read('data/regular.txt'))).toBe('regular');
  });

  it('dangling symlink to repo', async () => {
    const local = path.join(tmpDir, 'dangle');
    fs.mkdirSync(local);
    fs.symlinkSync('nonexistent_target', path.join(local, 'broken'));

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/broken')).toBe('nonexistent_target');
  });

  it('dangling symlink from repo', async () => {
    let f2 = await snap.writeSymlink('data/broken', 'nonexistent_target');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'broken')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'broken'))).toBe('nonexistent_target');
  });

  it('absolute symlink target preserved in round-trip', async () => {
    const local = path.join(tmpDir, 'abslink');
    fs.mkdirSync(local);
    fs.symlinkSync('/usr/bin/env', path.join(local, 'abs_link'));

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/abs_link')).toBe('/usr/bin/env');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'abs_link')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'abs_link'))).toBe('/usr/bin/env');
  });

  it('relative symlink with .. preserved', async () => {
    const local = path.join(tmpDir, 'rellink');
    fs.mkdirSync(path.join(local, 'sub'), { recursive: true });
    fs.symlinkSync('../sibling/file', path.join(local, 'sub', 'uplink'));

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/sub/uplink')).toBe('../sibling/file');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);
    expect(fs.readlinkSync(path.join(outDir, 'sub', 'uplink'))).toBe('../sibling/file');
  });

  it('symlink to self (circular) no crash', async () => {
    const local = path.join(tmpDir, 'selflink');
    fs.mkdirSync(local);
    fs.symlinkSync('selfref', path.join(local, 'selfref'));

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/selfref')).toBe('selfref');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'selfref')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'selfref'))).toBe('selfref');
  });

  it('walk local does not follow symlinked dirs', async () => {
    const local = path.join(tmpDir, 'walklocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'real.txt'), 'real');

    const targetDir = path.join(tmpDir, 'target_dir');
    fs.mkdirSync(targetDir);
    fs.writeFileSync(path.join(targetDir, 'hidden.txt'), 'should not appear');
    fs.mkdirSync(path.join(targetDir, 'sub'));
    fs.writeFileSync(path.join(targetDir, 'sub', 'nested.txt'), 'also hidden');

    fs.symlinkSync(targetDir, path.join(local, 'linked_dir'));

    const f2 = await snap.syncIn(local, 'data');
    // linked_dir should be stored as a symlink, not traversed
    expect(await f2.readlink('data/linked_dir')).toBe(targetDir);
    expect(await f2.exists('data/linked_dir/hidden.txt')).toBe(false);
    expect(await f2.exists('data/linked_dir/sub/nested.txt')).toBe(false);
  });

  it('symlink inside subdirectory', async () => {
    const local = path.join(tmpDir, 'sublink');
    fs.mkdirSync(path.join(local, 'sub'), { recursive: true });
    fs.writeFileSync(path.join(local, 'sub', 'real.txt'), 'content');
    fs.symlinkSync('real.txt', path.join(local, 'sub', 'link.txt'));

    const f2 = await snap.syncIn(local, 'data');
    expect(await f2.readlink('data/sub/link.txt')).toBe('real.txt');
    expect(fromBytes(await f2.read('data/sub/real.txt'))).toBe('content');
  });

  it('symlink target change detected from repo', async () => {
    let f2 = await snap.writeSymlink('data/link', 'target_v1');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);
    expect(fs.readlinkSync(path.join(outDir, 'link'))).toBe('target_v1');

    f2 = await f2.writeSymlink('data/link', 'target_v2');
    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.update.length).toBeGreaterThan(0);

    await f2.syncOut('data', outDir);
    expect(fs.readlinkSync(path.join(outDir, 'link'))).toBe('target_v2');
  });

  it('symlink replaces regular file from repo', async () => {
    let f2 = await snap.writeSymlink('data/target', 'somewhere');
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'target'), 'regular file');

    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'target')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'target'))).toBe('somewhere');
  });

  it('regular file replaces symlink from repo', async () => {
    let f2 = await snap.write('data/target', toBytes('regular file'));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.symlinkSync('somewhere', path.join(outDir, 'target'));

    await f2.syncOut('data', outDir);
    expect(fs.lstatSync(path.join(outDir, 'target')).isSymbolicLink()).toBe(false);
    expect(fs.readFileSync(path.join(outDir, 'target'), 'utf-8')).toBe('regular file');
  });
});

// ---------------------------------------------------------------------------
// Symlinks in-sync: mode comparison must not flag symlinks as updates
// ---------------------------------------------------------------------------

describe('sync symlinks in-sync', () => {
  it('file symlink in-sync to repo produces no updates', async () => {
    const local = path.join(tmpDir, 'insynclink');
    fs.mkdirSync(local);
    fs.symlinkSync('target', path.join(local, 'link'));
    fs.writeFileSync(path.join(local, 'file.txt'), 'hello');

    const f2 = await snap.syncIn(local, 'data');
    const f3 = await f2.syncIn(local, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('dir symlink in-sync to repo produces no updates', async () => {
    const targetDir = path.join(tmpDir, 'target_dir');
    fs.mkdirSync(targetDir);
    fs.writeFileSync(path.join(targetDir, 'child.txt'), 'child');

    const local = path.join(tmpDir, 'insyncdir');
    fs.mkdirSync(local);
    fs.symlinkSync(targetDir, path.join(local, 'linked_dir'));

    const f2 = await snap.syncIn(local, 'data');
    const f3 = await f2.syncIn(local, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('file symlink in-sync from repo produces no updates', async () => {
    let f2 = await snap.writeSymlink('data/link', 'target');
    f2 = await f2.write('data/file.txt', toBytes('hello'));

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);

    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('dir-targeting symlink from repo no false update', async () => {
    const targetDir = path.join(tmpDir, 'target_dir2');
    fs.mkdirSync(targetDir);
    fs.writeFileSync(path.join(targetDir, 'child.txt'), 'child');

    let f2 = await snap.writeSymlink('data/linked_dir', targetDir);
    f2 = await f2.write('data/file.txt', toBytes('hello'));

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);

    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// File/directory collisions (from repo direction + deep + dry-run)
// ---------------------------------------------------------------------------

describe('sync file/directory collisions extended', () => {
  it('file replaces directory from repo', async () => {
    let f2 = await snap.write('data/foo', toBytes('I am a file'));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(path.join(outDir, 'foo'), { recursive: true });
    fs.writeFileSync(path.join(outDir, 'foo', 'bar.txt'), 'nested');

    await f2.syncOut('data', outDir);
    expect(fs.statSync(path.join(outDir, 'foo')).isFile()).toBe(true);
    expect(fs.readFileSync(path.join(outDir, 'foo'), 'utf-8')).toBe('I am a file');
  });

  it('directory replaces file from repo', async () => {
    let f2 = await snap.write('data/foo/bar.txt', toBytes('nested'));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'foo'), 'I was a file');

    await f2.syncOut('data', outDir);
    expect(fs.statSync(path.join(outDir, 'foo')).isDirectory()).toBe(true);
    expect(fs.readFileSync(path.join(outDir, 'foo', 'bar.txt'), 'utf-8')).toBe('nested');
  });

  it('deep file replaces deep directory to repo', async () => {
    let f2 = await snap.write('data/a/b/c/d.txt', toBytes('deep'));
    const local = path.join(tmpDir, 'deeplocal');
    fs.mkdirSync(path.join(local, 'a'), { recursive: true });
    fs.writeFileSync(path.join(local, 'a', 'b'), 'shallow file');

    const f3 = await f2.syncIn(local, 'data');
    expect(fromBytes(await f3.read('data/a/b'))).toBe('shallow file');
    expect(await f3.exists('data/a/b/c/d.txt')).toBe(false);
  });

  it('dry-run shows collision operations', async () => {
    let f2 = await snap.write('data/foo/bar.txt', toBytes('nested'));
    f2 = await f2.write('data/foo/baz.txt', toBytes('nested2'));

    const local = path.join(tmpDir, 'collisionlocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'foo'), 'file');

    const f3 = await f2.syncIn(local, 'data', { dryRun: true });
    expect(f3.changes).not.toBeNull();
    const addPaths = new Set(f3.changes!.add.map((e: any) => e.path));
    const delPaths = new Set(f3.changes!.delete.map((e: any) => e.path));
    expect(addPaths.has('foo')).toBe(true);
    expect(delPaths.has('foo/bar.txt')).toBe(true);
  });

  it('symlink to directory replaced by regular dir from repo', async () => {
    let f2 = await snap.write('data/sub/file.txt', toBytes('content'));
    const elsewhere = path.join(tmpDir, 'elsewhere');
    fs.mkdirSync(elsewhere);
    fs.writeFileSync(path.join(elsewhere, 'other.txt'), 'other');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.symlinkSync(elsewhere, path.join(outDir, 'sub'));

    await f2.syncOut('data', outDir);
    expect(fs.statSync(path.join(outDir, 'sub')).isDirectory()).toBe(true);
    expect(fs.lstatSync(path.join(outDir, 'sub')).isSymbolicLink()).toBe(false);
    expect(fs.readFileSync(path.join(outDir, 'sub', 'file.txt'), 'utf-8')).toBe('content');
    // Elsewhere untouched
    expect(fs.readFileSync(path.join(elsewhere, 'other.txt'), 'utf-8')).toBe('other');
  });

  it('symlink to directory replaced by file from repo', async () => {
    let f2 = await snap.write('data/sub', toBytes('I am a file'));
    const elsewhere = path.join(tmpDir, 'elsewhere2');
    fs.mkdirSync(elsewhere);
    fs.writeFileSync(path.join(elsewhere, 'other.txt'), 'other');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.symlinkSync(elsewhere, path.join(outDir, 'sub'));

    await f2.syncOut('data', outDir);
    expect(fs.statSync(path.join(outDir, 'sub')).isFile()).toBe(true);
    expect(fs.lstatSync(path.join(outDir, 'sub')).isSymbolicLink()).toBe(false);
    expect(fs.readFileSync(path.join(outDir, 'sub'), 'utf-8')).toBe('I am a file');
    // Elsewhere untouched
    expect(fs.readFileSync(path.join(elsewhere, 'other.txt'), 'utf-8')).toBe('other');
  });
});

// ---------------------------------------------------------------------------
// Delete safety (ported from Python TestDeleteSafety)
// ---------------------------------------------------------------------------

describe('sync delete safety extended', () => {
  it('sync_out does not touch files outside target', async () => {
    let f2 = await snap.write('data/x.txt', toBytes('ex'));

    // Create sibling directory with files
    const sibling = path.join(tmpDir, 'sibling');
    fs.mkdirSync(path.join(sibling, 'sub'), { recursive: true });
    fs.writeFileSync(path.join(sibling, 'precious.txt'), 'do not delete');
    fs.writeFileSync(path.join(sibling, 'sub', 'deep.txt'), 'deep precious');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'old.txt'), 'should be deleted');

    await f2.syncOut('data', outDir);

    // Sibling untouched
    expect(fs.readFileSync(path.join(sibling, 'precious.txt'), 'utf-8')).toBe('do not delete');
    expect(fs.readFileSync(path.join(sibling, 'sub', 'deep.txt'), 'utf-8')).toBe('deep precious');
  });

  it('sync_out symlink escape prevented', async () => {
    let f2 = await snap.write('data/x.txt', toBytes('ex'));

    // Create precious files outside target
    const precious = path.join(tmpDir, 'precious');
    fs.mkdirSync(precious);
    fs.writeFileSync(path.join(precious, 'important.txt'), 'do not delete');

    // Target with symlink pointing outside
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.symlinkSync(precious, path.join(outDir, 'escape_link'));
    fs.writeFileSync(path.join(outDir, 'regular.txt'), 'delete me');

    await f2.syncOut('data', outDir);

    // Precious files must still exist
    expect(fs.readFileSync(path.join(precious, 'important.txt'), 'utf-8')).toBe('do not delete');
    expect(fs.existsSync(precious)).toBe(true);
  });

  it('sync_out preserves base dir after syncing to empty', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'a.txt'), 'a');
    fs.mkdirSync(path.join(outDir, 'sub'));
    fs.writeFileSync(path.join(outDir, 'sub', 'b.txt'), 'b');

    // Empty repo path — should delete all local files
    await snap.syncOut('data', outDir);

    // Base dir still exists, just empty
    expect(fs.existsSync(outDir)).toBe(true);
    expect(fs.readdirSync(outDir)).toEqual([]);
  });

  it('sync_out deletes only planned files', async () => {
    // Repo has 5 files
    let f2 = snap;
    for (let i = 0; i < 5; i++) {
      f2 = await f2.write(`data/keep_${i}.txt`, toBytes(`keep ${i}`));
    }

    // Local has repo files plus 5 extras
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    for (let i = 0; i < 5; i++) {
      fs.writeFileSync(path.join(outDir, `keep_${i}.txt`), `keep ${i}`);
    }
    for (let i = 0; i < 5; i++) {
      fs.writeFileSync(path.join(outDir, `delete_${i}.txt`), `delete ${i}`);
    }

    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes).not.toBeNull();
    expect(f3.changes!.delete.length).toBe(5);
    const deletePaths = new Set(f3.changes!.delete.map((e: any) => e.path));
    for (let i = 0; i < 5; i++) {
      expect(deletePaths.has(`delete_${i}.txt`)).toBe(true);
    }
    expect(f3.changes!.add.length).toBe(0);
    expect(f3.changes!.update.length).toBe(0);

    await f2.syncOut('data', outDir);

    // Verify exactly the right files remain
    const remaining = fs.readdirSync(outDir).sort();
    const expected = Array.from({ length: 5 }, (_, i) => `keep_${i}.txt`).sort();
    expect(remaining).toEqual(expected);

    // Verify content of kept files
    for (let i = 0; i < 5; i++) {
      expect(fs.readFileSync(path.join(outDir, `keep_${i}.txt`), 'utf-8')).toBe(`keep ${i}`);
    }
  });
});

// ---------------------------------------------------------------------------
// Round-trip extended (ported from Python TestSyncRoundTrip)
// ---------------------------------------------------------------------------

describe('sync round trip extended', () => {
  it('sync_out then sync_in produces identical repo state', async () => {
    let f2 = await snap.write('data/x.txt', toBytes('ex'));
    f2 = await f2.write('data/sub/y.txt', toBytes('why'));
    f2 = await f2.writeSymlink('data/link', 'x.txt');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);

    // Sync back to a different repo path
    const f3 = await f2.syncIn(outDir, 'data2');
    expect(fromBytes(await f3.read('data2/x.txt'))).toBe('ex');
    expect(fromBytes(await f3.read('data2/sub/y.txt'))).toBe('why');
    expect(await f3.readlink('data2/link')).toBe('x.txt');
  });

  it('round-trip with symlinks preserves targets', async () => {
    const local = path.join(tmpDir, 'rtlocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'a.txt'), 'alpha');
    fs.writeFileSync(path.join(local, 'b.txt'), 'beta');
    fs.symlinkSync('a.txt', path.join(local, 'link'));

    const f2 = await snap.syncIn(local, 'data');

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);

    expect(fs.readFileSync(path.join(outDir, 'a.txt'), 'utf-8')).toBe('alpha');
    expect(fs.lstatSync(path.join(outDir, 'link')).isSymbolicLink()).toBe(true);
    expect(fs.readlinkSync(path.join(outDir, 'link'))).toBe('a.txt');
  });

  it('idempotent complex tree', async () => {
    const local = path.join(tmpDir, 'complexlocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'a.txt'), 'alpha');
    fs.mkdirSync(path.join(local, 'x', 'y', 'z'), { recursive: true });
    fs.writeFileSync(path.join(local, 'x', 'y', 'z', 'deep.txt'), 'deep');
    fs.symlinkSync('a.txt', path.join(local, 'link'));

    const f2 = await snap.syncIn(local, 'data');
    const f3 = await f2.syncIn(local, 'data');
    expect(f3.commitHash).toBe(f2.commitHash);
  });
});

// ---------------------------------------------------------------------------
// Dry-run exact match extended (ported from Python TestDryRunExactMatch)
// ---------------------------------------------------------------------------

describe('sync dryRun exact match extended', () => {
  it('dry-run plan exact match to repo (detailed)', async () => {
    let f2 = await snap.write('data/keep.txt', toBytes('keep'));
    f2 = await f2.write('data/change.txt', toBytes('old'));
    f2 = await f2.write('data/remove.txt', toBytes('bye'));
    f2 = await f2.write('data/sub/deep.txt', toBytes('deep'));

    const local = path.join(tmpDir, 'exactlocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(local, 'change.txt'), 'new');
    fs.writeFileSync(path.join(local, 'add.txt'), 'added');

    const dryFs = await f2.syncIn(local, 'data', { dryRun: true });
    const actualFs = await f2.syncIn(local, 'data');

    expect(dryFs.changes).not.toBeNull();
    expect(actualFs.changes).not.toBeNull();

    // Verify adds match
    const dryAdds = new Set(dryFs.changes!.add.map((e: any) => e.path));
    expect(dryAdds.has('add.txt')).toBe(true);

    // Verify deletes match
    const dryDels = new Set(dryFs.changes!.delete.map((e: any) => e.path));
    expect(dryDels.has('remove.txt')).toBe(true);
    expect(dryDels.has('sub/deep.txt')).toBe(true);

    // Verify updates match
    const dryUpds = new Set(dryFs.changes!.update.map((e: any) => e.path));
    expect(dryUpds.has('change.txt')).toBe(true);

    // After sync, second dry-run shows in_sync
    const f3 = await actualFs.syncIn(local, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('dry-run plan exact match from repo (detailed)', async () => {
    let f2 = await snap.write('data/a.txt', toBytes('alpha'));
    f2 = await f2.write('data/sub/b.txt', toBytes('beta'));
    f2 = await f2.write('data/keep.txt', toBytes('keep'));

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'keep.txt'), 'keep'); // same content
    fs.writeFileSync(path.join(outDir, 'extra.txt'), 'should be deleted');
    fs.mkdirSync(path.join(outDir, 'orphan'));
    fs.writeFileSync(path.join(outDir, 'orphan', 'old.txt'), 'old');

    const dryFs = await f2.syncOut('data', outDir, { dryRun: true });
    expect(dryFs.changes).not.toBeNull();

    const addPaths = new Set(dryFs.changes!.add.map((e: any) => e.path));
    const delPaths = new Set(dryFs.changes!.delete.map((e: any) => e.path));

    expect(addPaths.has('a.txt')).toBe(true);
    expect(addPaths.has('sub/b.txt')).toBe(true);
    expect(delPaths.has('extra.txt')).toBe(true);
    expect(delPaths.has('orphan/old.txt')).toBe(true);

    await f2.syncOut('data', outDir);

    // After sync, should be in_sync
    const f3 = await f2.syncOut('data', outDir, { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });

  it('dry-run with collisions matches actual', async () => {
    let f2 = await snap.write('data/foo/bar.txt', toBytes('nested'));
    f2 = await f2.write('data/foo/baz.txt', toBytes('nested2'));
    f2 = await f2.write('data/other.txt', toBytes('other'));

    const local = path.join(tmpDir, 'collisionexact');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'foo'), 'I am a file now');
    fs.writeFileSync(path.join(local, 'other.txt'), 'other');

    const dryFs = await f2.syncIn(local, 'data', { dryRun: true });
    const actualFs = await f2.syncIn(local, 'data');

    expect(dryFs.changes).not.toBeNull();

    // After execution, verify result
    expect(fromBytes(await actualFs.read('data/foo'))).toBe('I am a file now');
    expect(await actualFs.exists('data/foo/bar.txt')).toBe(false);
    expect(await actualFs.exists('data/foo/baz.txt')).toBe(false);
    expect(fromBytes(await actualFs.read('data/other.txt'))).toBe('other');

    // And in_sync after
    const f3 = await actualFs.syncIn(local, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Structure edge cases extended
// ---------------------------------------------------------------------------

describe('sync structure edge cases extended', () => {
  it('deeply nested sync (5+ levels)', async () => {
    const local = path.join(tmpDir, 'deeplocal');
    const deep = path.join(local, 'a', 'b', 'c', 'd', 'e');
    fs.mkdirSync(deep, { recursive: true });
    fs.writeFileSync(path.join(deep, 'deep.txt'), 'deep');

    const f2 = await snap.syncIn(local, 'data');
    expect(fromBytes(await f2.read('data/a/b/c/d/e/deep.txt'))).toBe('deep');
  });

  it('deeply nested delete cleans parent dirs', async () => {
    let f2 = await snap.write('data/x.txt', toBytes('keep'));
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    const deep = path.join(outDir, 'a', 'b', 'c', 'd');
    fs.mkdirSync(deep, { recursive: true });
    fs.writeFileSync(path.join(deep, 'orphan.txt'), 'orphan');

    await f2.syncOut('data', outDir);
    expect(fs.readFileSync(path.join(outDir, 'x.txt'), 'utf-8')).toBe('keep');
    expect(fs.existsSync(path.join(outDir, 'a'))).toBe(false);
  });

  it('mixed add/update/delete with dry-run verification', async () => {
    let f2 = await snap.write('data/keep.txt', toBytes('keep'));
    f2 = await f2.write('data/change.txt', toBytes('old'));
    f2 = await f2.write('data/remove.txt', toBytes('bye'));

    const local = path.join(tmpDir, 'mixedlocal');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(local, 'change.txt'), 'new');
    fs.writeFileSync(path.join(local, 'add.txt'), 'new file');

    const dryFs = await f2.syncIn(local, 'data', { dryRun: true });
    expect(dryFs.changes).not.toBeNull();
    const addPaths = new Set(dryFs.changes!.add.map((e: any) => e.path));
    const updPaths = new Set(dryFs.changes!.update.map((e: any) => e.path));
    const delPaths = new Set(dryFs.changes!.delete.map((e: any) => e.path));
    expect(addPaths.has('add.txt')).toBe(true);
    expect(updPaths.has('change.txt')).toBe(true);
    expect(delPaths.has('remove.txt')).toBe(true);
    expect(addPaths.has('keep.txt') || updPaths.has('keep.txt') || delPaths.has('keep.txt')).toBe(false);

    const actualFs = await f2.syncIn(local, 'data');
    expect(fromBytes(await actualFs.read('data/keep.txt'))).toBe('keep');
    expect(fromBytes(await actualFs.read('data/change.txt'))).toBe('new');
    expect(fromBytes(await actualFs.read('data/add.txt'))).toBe('new file');
    expect(await actualFs.exists('data/remove.txt')).toBe(false);
  });

  it('repo path is a file with dry-run check', async () => {
    let f2 = await snap.write('data', toBytes("I am a file at 'data'"));
    const local = path.join(tmpDir, 'filedest');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'hello.txt'), 'hello');

    // Dry run should treat the file as "no children" (all adds)
    const dryFs = await f2.syncIn(local, 'data', { dryRun: true });
    expect(dryFs.changes).not.toBeNull();
    const addPaths = new Set(dryFs.changes!.add.map((e: any) => e.path));
    expect(addPaths.has('hello.txt')).toBe(true);

    const actualFs = await f2.syncIn(local, 'data');
    expect(fromBytes(await actualFs.read('data/hello.txt'))).toBe('hello');
    expect(await actualFs.isDir('data')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Stress extended (ported from Python TestSyncStress)
// ---------------------------------------------------------------------------

describe('sync stress extended', () => {
  it('200+ files with subdirectories', async () => {
    const local = path.join(tmpDir, 'stresslocal');
    fs.mkdirSync(local);

    const expected: Record<string, string> = {};
    for (let i = 0; i < 200; i++) {
      const subdir = `dir_${i % 10}`;
      fs.mkdirSync(path.join(local, subdir), { recursive: true });
      const name = `${subdir}/file_${i}.txt`;
      const content = `content_${i}`;
      fs.writeFileSync(path.join(local, subdir, `file_${i}.txt`), content);
      expected[name] = content;
    }

    const f2 = await snap.syncIn(local, 'data');

    // Verify all files in repo
    for (const [name, content] of Object.entries(expected)) {
      expect(fromBytes(await f2.read(`data/${name}`))).toBe(content);
    }

    // Round-trip back
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    await f2.syncOut('data', outDir);

    for (const [name, content] of Object.entries(expected)) {
      expect(fs.readFileSync(path.join(outDir, name), 'utf-8')).toBe(content);
    }

    // Final dry-run should show in_sync
    const f3 = await f2.syncIn(outDir, 'data', { dryRun: true });
    expect(f3.changes === null || changeReportInSync(f3.changes)).toBe(true);
  }, 30000);
});

// ---------------------------------------------------------------------------
// Error/boundary conditions (ported from Python TestSyncErrors)
// ---------------------------------------------------------------------------

describe('sync errors and boundary conditions', () => {
  it('sync_in nonexistent local path is noop', async () => {
    const f2 = await snap.syncIn('/nonexistent/path/that/does/not/exist', 'data');
    const entries = await f2.ls();
    expect(entries.length).toBe(0);
  });

  it('sync_in nonexistent local deletes repo content', async () => {
    let f2 = await snap.write('data/x.txt', toBytes('ex'));
    const f3 = await f2.syncIn('/nonexistent/path', 'data');
    expect(await f3.exists('data/x.txt')).toBe(false);
  });

  it('sync_out nonexistent repo path creates empty local', async () => {
    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'a.txt'), 'should be deleted');
    fs.mkdirSync(path.join(outDir, 'sub'));
    fs.writeFileSync(path.join(outDir, 'sub', 'b.txt'), 'also deleted');

    await snap.syncOut('nonexistent', outDir);
    expect(fs.readdirSync(outDir)).toEqual([]);
    expect(fs.existsSync(outDir)).toBe(true); // base dir preserved
  });

  it('dry-run plan immutability to repo', async () => {
    let f2 = await snap.write('data/a.txt', toBytes('alpha'));

    const local = path.join(tmpDir, 'immut');
    fs.mkdirSync(local);
    fs.writeFileSync(path.join(local, 'b.txt'), 'beta');

    const dry1 = await f2.syncIn(local, 'data', { dryRun: true });
    const dry2 = await f2.syncIn(local, 'data', { dryRun: true });

    expect(dry1.changes).not.toBeNull();
    expect(dry2.changes).not.toBeNull();
    expect(dry1.changes!.add.length).toBe(dry2.changes!.add.length);
    expect(dry1.changes!.update.length).toBe(dry2.changes!.update.length);
    expect(dry1.changes!.delete.length).toBe(dry2.changes!.delete.length);
  });

  it('dry-run plan immutability from repo', async () => {
    let f2 = await snap.write('data/a.txt', toBytes('alpha'));

    const outDir = path.join(tmpDir, 'out');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'b.txt'), 'beta');

    const dry1 = await f2.syncOut('data', outDir, { dryRun: true });
    const dry2 = await f2.syncOut('data', outDir, { dryRun: true });

    expect(dry1.changes).not.toBeNull();
    expect(dry2.changes).not.toBeNull();
    expect(dry1.changes!.add.length).toBe(dry2.changes!.add.length);
    expect(dry1.changes!.update.length).toBe(dry2.changes!.update.length);
    expect(dry1.changes!.delete.length).toBe(dry2.changes!.delete.length);
  });
});
