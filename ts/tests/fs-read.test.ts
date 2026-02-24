import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  FileNotFoundError,
  IsADirectoryError,
  NotADirectoryError,
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
  f = await f.write('hello.txt', toBytes('Hello!'));
  f = await f.write('src/main.py', toBytes("print('hi')"));
  snap = await f.write('src/lib/util.py', toBytes('# util'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('read', () => {
  it('reads a file', async () => {
    expect(fromBytes(await snap.read('hello.txt'))).toBe('Hello!');
  });

  it('reads nested file', async () => {
    expect(fromBytes(await snap.read('src/main.py'))).toBe("print('hi')");
  });

  it('missing file throws FileNotFoundError', async () => {
    await expect(snap.read('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('reading a directory throws IsADirectoryError', async () => {
    await expect(snap.read('src')).rejects.toThrow(IsADirectoryError);
  });
});

describe('readText', () => {
  it('reads text', async () => {
    expect(await snap.readText('hello.txt')).toBe('Hello!');
  });

  it('reads with encoding', async () => {
    // Write raw latin-1 bytes for 'café'
    const bytes = new Uint8Array([0x63, 0x61, 0x66, 0xe9]);
    const f2 = await snap.write('latin.txt', bytes);
    const text = await f2.readText('latin.txt', 'latin1');
    expect(text).toBe('café');
  });
});

describe('ls', () => {
  it('lists root', async () => {
    const items = (await snap.ls()).sort();
    expect(items).toEqual(['hello.txt', 'src']);
  });

  it('lists subdirectory', async () => {
    const items = (await snap.ls('src')).sort();
    expect(items).toEqual(['lib', 'main.py']);
  });

  it('ls on file throws NotADirectoryError', async () => {
    await expect(snap.ls('hello.txt')).rejects.toThrow(NotADirectoryError);
  });
});

describe('walk', () => {
  it('walks root', async () => {
    const entries = [];
    for await (const e of snap.walk()) entries.push(e);
    const [dirpath, dirs, files] = entries[0];
    expect(dirpath).toBe('');
    expect(dirs).toContain('src');
    expect(files.map((f) => f.name)).toContain('hello.txt');
  });

  it('walks subdirectory', async () => {
    const entries = [];
    for await (const e of snap.walk('src')) entries.push(e);
    const [dirpath, , files] = entries[0];
    expect(dirpath).toBe('src');
    expect(files.map((f) => f.name)).toContain('main.py');
  });

  it('walk on file throws NotADirectoryError', async () => {
    const entries = [];
    await expect(async () => {
      for await (const e of snap.walk('hello.txt')) entries.push(e);
    }).rejects.toThrow(NotADirectoryError);
  });
});

describe('exists', () => {
  it('file exists', async () => {
    expect(await snap.exists('hello.txt')).toBe(true);
  });

  it('directory exists', async () => {
    expect(await snap.exists('src')).toBe(true);
  });

  it('missing returns false', async () => {
    expect(await snap.exists('nope.txt')).toBe(false);
  });
});

describe('copyOut root', () => {
  it('copyOut creates files on disk', async () => {
    const outDir = path.join(tmpDir, 'export');
    await snap.copyOut('/', outDir);
    expect(fs.readFileSync(path.join(outDir, 'hello.txt'), 'utf-8')).toBe('Hello!');
    expect(fs.readFileSync(path.join(outDir, 'src/main.py'), 'utf-8')).toBe("print('hi')");
    expect(fs.readFileSync(path.join(outDir, 'src/lib/util.py'), 'utf-8')).toBe('# util');
  });

  it('copyOut empty repository', async () => {
    const { store: s2, tmpDir: td2 } = await freshStore();
    const emptyFs = await s2.branches.get('main');
    const outDir = path.join(td2, 'export');
    fs.mkdirSync(outDir, { recursive: true });
    await emptyFs.copyOut('/', outDir);
    expect(fs.existsSync(outDir)).toBe(true);
    rmTmpDir(td2);
  });

  it('copyOut into existing directory', async () => {
    const outDir = path.join(tmpDir, 'export');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'hello.txt'), 'old');
    await snap.copyOut('/', outDir);
    expect(fs.readFileSync(path.join(outDir, 'hello.txt'), 'utf-8')).toBe('Hello!');
  });

  it('copyOut symlinks', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    const outDir = path.join(tmpDir, 'export-sym');
    await f2.copyOut('/', outDir);
    const target = fs.readlinkSync(path.join(outDir, 'link.txt'));
    expect(target).toBe('hello.txt');
  });

  it('copyOut symlinks overwriting regular files', async () => {
    const f2 = await snap.writeSymlink('hello.txt', 'src/main.py');
    const outDir = path.join(tmpDir, 'export-overwrite');
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'hello.txt'), 'old');
    await f2.copyOut('/', outDir);
    const target = fs.readlinkSync(path.join(outDir, 'hello.txt'));
    expect(target).toBe('src/main.py');
  });
});

describe('fileType', () => {
  it('blob type', async () => {
    expect(await snap.fileType('hello.txt')).toBe(FileType.BLOB);
  });

  it('tree type', async () => {
    expect(await snap.fileType('src')).toBe(FileType.TREE);
  });

  it('nested file type', async () => {
    expect(await snap.fileType('src/main.py')).toBe(FileType.BLOB);
  });

  it('executable type', async () => {
    const f2 = await snap.write('run.sh', toBytes('#!/bin/sh'), { mode: FileType.EXECUTABLE });
    expect(await f2.fileType('run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('symlink type', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    expect(await f2.fileType('link.txt')).toBe(FileType.LINK);
  });

  it('missing throws FileNotFoundError', async () => {
    await expect(snap.fileType('nope.txt')).rejects.toThrow(FileNotFoundError);
  });
});

describe('size', () => {
  it('file size', async () => {
    expect(await snap.size('hello.txt')).toBe(toBytes('Hello!').length);
  });

  it('nested file size', async () => {
    expect(await snap.size('src/main.py')).toBe(toBytes("print('hi')").length);
  });

  it('missing throws FileNotFoundError', async () => {
    await expect(snap.size('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('size matches read length', async () => {
    const data = await snap.read('hello.txt');
    expect(await snap.size('hello.txt')).toBe(data.length);
  });
});

describe('objectHash', () => {
  it('returns 40-char hex string', async () => {
    const h = await snap.objectHash('hello.txt');
    expect(h).toMatch(/^[0-9a-f]{40}$/);
  });

  it('same content same hash', async () => {
    const f2 = await snap.write('copy.txt', toBytes('Hello!'));
    expect(await f2.objectHash('hello.txt')).toBe(await f2.objectHash('copy.txt'));
  });

  it('different content different hash', async () => {
    expect(await snap.objectHash('hello.txt')).not.toBe(await snap.objectHash('src/main.py'));
  });

  it('tree hash is valid hex', async () => {
    const h = await snap.objectHash('src');
    expect(h).toMatch(/^[0-9a-f]{40}$/);
  });

  it('missing throws FileNotFoundError', async () => {
    await expect(snap.objectHash('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('stable across calls', async () => {
    const h1 = await snap.objectHash('hello.txt');
    const h2 = await snap.objectHash('hello.txt');
    expect(h1).toBe(h2);
  });
});

describe('properties', () => {
  it('commitHash is 40-char hex', () => {
    expect(snap.commitHash).toMatch(/^[0-9a-f]{40}$/);
  });

  it('refName is main', () => {
    expect(snap.refName).toBe('main');
  });

  it('message contains last written file', async () => {
    const msg = await snap.getMessage();
    expect(msg).toContain('util.py');
  });
});

describe('readlink', () => {
  it('reads symlink target', async () => {
    const f2 = await snap.writeSymlink('link.txt', 'hello.txt');
    expect(await f2.readlink('link.txt')).toBe('hello.txt');
  });

  it('missing symlink throws FileNotFoundError', async () => {
    await expect(snap.readlink('nope.txt')).rejects.toThrow(FileNotFoundError);
  });

  it('readlink on regular file throws', async () => {
    await expect(snap.readlink('hello.txt')).rejects.toThrow(/Not a symlink/);
  });
});

// ---------------------------------------------------------------------------
// glob ** patterns on repo (ported from Python)
// ---------------------------------------------------------------------------

describe('glob', () => {
  it('** recursive pattern', async () => {
    const matches = await snap.glob('**/*.py');
    expect(matches).toContain('src/main.py');
    expect(matches).toContain('src/lib/util.py');
  });

  it('* single level', async () => {
    const matches = await snap.glob('src/*.py');
    expect(matches).toContain('src/main.py');
    expect(matches).not.toContain('src/lib/util.py');
  });

  it('no matches returns empty', async () => {
    const matches = await snap.glob('*.xyz');
    expect(matches).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// walk validates full tuple structure
// ---------------------------------------------------------------------------

describe('walk tuple structure', () => {
  it('yields [dirpath, subdirs, files] tuples', async () => {
    const entries = [];
    for await (const e of snap.walk()) entries.push(e);

    // Each entry is a 3-tuple
    for (const entry of entries) {
      expect(entry).toHaveLength(3);
      const [dirpath, subdirs, files] = entry;
      expect(typeof dirpath).toBe('string');
      expect(Array.isArray(subdirs)).toBe(true);
      expect(Array.isArray(files)).toBe(true);
    }

    // Root should have 'src' subdir and 'hello.txt' file
    const root = entries.find(([dp]) => dp === '');
    expect(root).toBeDefined();
    const [, rootDirs, rootFiles] = root!;
    expect(rootDirs).toContain('src');
    expect(rootFiles.some((f) => f.name === 'hello.txt')).toBe(true);
  });

  it('file entries have name, oid, mode', async () => {
    const entries = [];
    for await (const e of snap.walk()) entries.push(e);
    const root = entries.find(([dp]) => dp === '');
    expect(root).toBeDefined();
    const [, , files] = root!;
    const helloFile = files.find((f) => f.name === 'hello.txt');
    expect(helloFile).toBeDefined();
    expect(helloFile!.name).toBe('hello.txt');
    expect(helloFile!.oid).toMatch(/^[0-9a-f]{40}$/);
    expect(typeof helloFile!.mode).toBe('string');
  });
});

// ---------------------------------------------------------------------------
// isDir checks
// ---------------------------------------------------------------------------

describe('isDir', () => {
  it('directory returns true', async () => {
    expect(await snap.isDir('src')).toBe(true);
  });

  it('file returns false', async () => {
    expect(await snap.isDir('hello.txt')).toBe(false);
  });

  it('missing returns false', async () => {
    expect(await snap.isDir('nope')).toBe(false);
  });

  it('nested directory', async () => {
    expect(await snap.isDir('src/lib')).toBe(true);
  });
});
