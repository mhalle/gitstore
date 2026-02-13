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
});
