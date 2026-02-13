import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, rmTmpDir } from './helpers.js';
import { GitStore, FS } from '../src/index.js';

let store: GitStore;
let snap: FS;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;

  let f = await store.branches.get('main');
  const b = f.batch({ message: 'seed' });
  await b.write('readme.txt', toBytes('readme'));
  await b.write('setup.py', toBytes('setup'));
  await b.write('.hidden', toBytes('hidden'));
  await b.write('src/main.py', toBytes('main'));
  await b.write('src/util.py', toBytes('util'));
  await b.write('src/.config', toBytes('config'));
  await b.write('src/sub/deep.txt', toBytes('deep'));
  await b.write('docs/guide.md', toBytes('guide'));
  await b.write('docs/api.md', toBytes('api'));
  await b.write('data.txt', toBytes('data'));
  snap = await b.commit();
});

afterEach(() => rmTmpDir(tmpDir));

describe('isDir', () => {
  it('directory', async () => {
    expect(await snap.isDir('src')).toBe(true);
  });

  it('file', async () => {
    expect(await snap.isDir('readme.txt')).toBe(false);
  });

  it('nested directory', async () => {
    expect(await snap.isDir('src/sub')).toBe(true);
  });

  it('nonexistent', async () => {
    expect(await snap.isDir('nope')).toBe(false);
  });
});

describe('glob star', () => {
  it('*.txt matches txt files', async () => {
    const result = await snap.glob('*.txt');
    expect(result).toContain('readme.txt');
    expect(result).toContain('data.txt');
    expect(result).not.toContain('setup.py');
  });

  it('* excludes dotfiles', async () => {
    const result = await snap.glob('*');
    expect(result).not.toContain('.hidden');
  });

  it('.* matches dotfiles', async () => {
    const result = await snap.glob('.*');
    expect(result).toContain('.hidden');
  });

  it('src/* works', async () => {
    const result = await snap.glob('src/*');
    expect(result).toContain('src/main.py');
    expect(result).toContain('src/util.py');
    expect(result).toContain('src/sub');
    expect(result).not.toContain('src/.config');
  });

  it('src/*.py filters extension', async () => {
    const result = await snap.glob('src/*.py');
    expect(result.sort()).toEqual(['src/main.py', 'src/util.py']);
  });

  it('docs/*.md', async () => {
    const result = await snap.glob('docs/*.md');
    expect(result.sort()).toEqual(['docs/api.md', 'docs/guide.md']);
  });
});

describe('glob question mark', () => {
  it('docs/???.md matches 3-char names', async () => {
    const result = await snap.glob('docs/???.md');
    expect(result).toEqual(['docs/api.md']);
  });
});

describe('glob nested', () => {
  it('src/sub/*.txt', async () => {
    const result = await snap.glob('src/sub/*.txt');
    expect(result).toEqual(['src/sub/deep.txt']);
  });

  it('*/main.py', async () => {
    const result = await snap.glob('*/main.py');
    expect(result).toEqual(['src/main.py']);
  });
});

describe('glob edge cases', () => {
  it('no matches returns empty', async () => {
    const result = await snap.glob('*.xyz');
    expect(result).toEqual([]);
  });

  it('literal path returns itself', async () => {
    const result = await snap.glob('readme.txt');
    expect(result).toEqual(['readme.txt']);
  });

  it('literal missing returns empty', async () => {
    const result = await snap.glob('nope.txt');
    expect(result).toEqual([]);
  });

  it('empty pattern returns empty', async () => {
    const result = await snap.glob('');
    expect(result).toEqual([]);
  });

  it('results are sorted', async () => {
    const result = await snap.glob('*.txt');
    expect(result).toEqual([...result].sort());
  });
});

describe('glob doublestar', () => {
  it('** matches all recursively (no dotfiles)', async () => {
    const result = await snap.glob('**');
    expect(result).toContain('readme.txt');
    expect(result).toContain('src/main.py');
    expect(result).toContain('src/sub/deep.txt');
    expect(result).not.toContain('.hidden');
    expect(result).not.toContain('src/.config');
  });

  it('**/*.py matches at all depths', async () => {
    const result = await snap.glob('**/*.py');
    expect(result).toContain('setup.py');
    expect(result).toContain('src/main.py');
    expect(result).toContain('src/util.py');
  });

  it('src/**/*.py scoped', async () => {
    const result = await snap.glob('src/**/*.py');
    expect(result).toContain('src/main.py');
    expect(result).toContain('src/util.py');
    expect(result).not.toContain('setup.py');
  });

  it('src/**/deep.txt', async () => {
    const result = await snap.glob('src/**/deep.txt');
    expect(result).toContain('src/sub/deep.txt');
  });

  it('no dotfiles with **', async () => {
    const result = await snap.glob('**');
    expect(result.filter((p) => p.includes('/.')).length).toBe(0);
    expect(result.filter((p) => p.startsWith('.')).length).toBe(0);
  });

  it('no duplicates', async () => {
    const result = await snap.glob('**');
    expect(new Set(result).size).toBe(result.length);
  });

  it('empty repo returns empty for **', async () => {
    const emptyFs = await store.branches.get('main');
    // Navigate to initial empty commit
    const { store: s2, tmpDir: td } = await freshStore();
    const f = await s2.branches.get('main');
    const result = await f.glob('**');
    // The initial commit has an empty tree
    expect(result).toEqual([]);
    rmTmpDir(td);
  });

  it('**/readme.txt matches root', async () => {
    const result = await snap.glob('**/readme.txt');
    expect(result).toContain('readme.txt');
  });

  it('results are sorted', async () => {
    const result = await snap.glob('**/*.py');
    expect(result).toEqual([...result].sort());
  });
});

describe('glob pivot', () => {
  it('src/./sub/*.txt preserves pivot', async () => {
    const result = await snap.glob('src/./sub/*.txt');
    expect(result).toContain('src/./sub/deep.txt');
  });

  it('recursive with pivot', async () => {
    const result = await snap.glob('src/./**/*.py');
    expect(result.some((p) => p.startsWith('src/./'))).toBe(true);
  });

  it('no match returns empty', async () => {
    const result = await snap.glob('src/./nope/*.xyz');
    expect(result).toEqual([]);
  });

  it('results are sorted', async () => {
    const result = await snap.glob('src/./**');
    expect(result).toEqual([...result].sort());
  });
});
