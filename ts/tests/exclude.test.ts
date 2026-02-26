import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, storeWithFiles, toBytes, rmTmpDir, makeTmpDir } from './helpers.js';
import { GitStore, FS, ExcludeFilter } from '../src/index.js';
import * as fs from 'node:fs';
import * as path from 'node:path';

// ---------------------------------------------------------------------------
// Unit tests (no repo needed)
// ---------------------------------------------------------------------------

describe('ExcludeFilter unit', () => {
  it('basic pattern matching', () => {
    const ef = new ExcludeFilter({ patterns: ['*.pyc'] });
    expect(ef.isExcluded('foo.pyc')).toBe(true);
    expect(ef.isExcluded('dir/bar.pyc')).toBe(true);
    expect(ef.isExcluded('foo.py')).toBe(false);
  });

  it('negation pattern', () => {
    const ef = new ExcludeFilter({ patterns: ['*.pyc', '!important.pyc'] });
    expect(ef.isExcluded('foo.pyc')).toBe(true);
    expect(ef.isExcluded('important.pyc')).toBe(false);
  });

  it('directory-only pattern', () => {
    const ef = new ExcludeFilter({ patterns: ['build/'] });
    expect(ef.isExcluded('build', true)).toBe(true);
    expect(ef.isExcluded('build', false)).toBe(false);
    expect(ef.isExcluded('project/build', true)).toBe(true);
  });

  it('anchored pattern with slash', () => {
    const ef = new ExcludeFilter({ patterns: ['src/*.tmp'] });
    expect(ef.isExcluded('src/foo.tmp')).toBe(true);
    expect(ef.isExcluded('other/foo.tmp')).toBe(false);
  });

  it('basename matching without slash', () => {
    const ef = new ExcludeFilter({ patterns: ['*.log'] });
    expect(ef.isExcluded('app.log')).toBe(true);
    expect(ef.isExcluded('deep/nested/debug.log')).toBe(true);
    expect(ef.isExcluded('readme.txt')).toBe(false);
  });

  it('comments and blank lines are ignored', () => {
    const ef = new ExcludeFilter({ patterns: ['# comment', '', '  ', '*.pyc'] });
    expect(ef.isExcluded('foo.pyc')).toBe(true);
    expect(ef.isExcluded('foo.py')).toBe(false);
  });

  it('empty filter is not active', () => {
    const ef = new ExcludeFilter();
    expect(ef.active).toBe(false);
    expect(ef.isExcluded('anything')).toBe(false);
  });

  it('load from file', () => {
    const tmpDir = makeTmpDir();
    try {
      const filePath = path.join(tmpDir, 'patterns.txt');
      fs.writeFileSync(filePath, '# comment\n*.log\n!important.log\nbuild/\n');
      const ef = new ExcludeFilter({ excludeFrom: filePath });
      expect(ef.active).toBe(true);
      expect(ef.isExcluded('app.log')).toBe(true);
      expect(ef.isExcluded('important.log')).toBe(false);
      expect(ef.isExcluded('build', true)).toBe(true);
      expect(ef.isExcluded('build', false)).toBe(false);
    } finally {
      rmTmpDir(tmpDir);
    }
  });

  it('load from nonexistent file is silent', () => {
    const ef = new ExcludeFilter({ excludeFrom: '/nonexistent/file.txt' });
    expect(ef.active).toBe(false);
  });

  it('last matching rule wins', () => {
    const ef = new ExcludeFilter({ patterns: ['*.pyc', '!*.pyc', '*.pyc'] });
    expect(ef.isExcluded('foo.pyc')).toBe(true);
  });

  it('question mark wildcard', () => {
    const ef = new ExcludeFilter({ patterns: ['?.txt'] });
    expect(ef.isExcluded('a.txt')).toBe(true);
    expect(ef.isExcluded('ab.txt')).toBe(false);
  });

  it('no dotfile protection', () => {
    const ef = new ExcludeFilter({ patterns: ['*.pyc'] });
    expect(ef.isExcluded('.hidden.pyc')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Integration with copyIn / syncIn
// ---------------------------------------------------------------------------

describe('ExcludeFilter integration', () => {
  let store: GitStore;
  let snap: FS;
  let tmpDir: string;

  beforeEach(async () => {
    const res = await freshStore();
    store = res.store;
    snap = await store.branches.get('main');
    tmpDir = res.tmpDir;

    // Seed with an initial file so the branch has a commit
    snap = await snap.writeText('init.txt', 'init');
  });

  afterEach(() => rmTmpDir(tmpDir));

  it('copyIn excludes files matching pattern', async () => {
    const srcDir = path.join(tmpDir, 'src');
    fs.mkdirSync(srcDir, { recursive: true });
    fs.writeFileSync(path.join(srcDir, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(srcDir, 'skip.pyc'), 'compiled');
    fs.writeFileSync(path.join(srcDir, 'also.pyc'), 'compiled2');

    const ef = new ExcludeFilter({ patterns: ['*.pyc'] });
    const result = await snap.copyIn(srcDir + '/', 'dest', { exclude: ef });
    expect(await result.exists('dest/keep.txt')).toBe(true);
    expect(await result.exists('dest/skip.pyc')).toBe(false);
    expect(await result.exists('dest/also.pyc')).toBe(false);
  });

  it('copyIn excludes directories', async () => {
    const srcDir = path.join(tmpDir, 'src');
    fs.mkdirSync(path.join(srcDir, 'build'), { recursive: true });
    fs.writeFileSync(path.join(srcDir, 'keep.txt'), 'keep');
    fs.writeFileSync(path.join(srcDir, 'build', 'output.bin'), 'bin');

    const ef = new ExcludeFilter({ patterns: ['build/'] });
    const result = await snap.copyIn(srcDir + '/', 'dest', { exclude: ef });
    expect(await result.exists('dest/keep.txt')).toBe(true);
    expect(await result.exists('dest/build/output.bin')).toBe(false);
  });

  it('syncIn respects exclude filter', async () => {
    const srcDir = path.join(tmpDir, 'src');
    fs.mkdirSync(srcDir, { recursive: true });
    fs.writeFileSync(path.join(srcDir, 'a.txt'), 'aaa');
    fs.writeFileSync(path.join(srcDir, 'b.pyc'), 'compiled');

    const ef = new ExcludeFilter({ patterns: ['*.pyc'] });
    const result = await snap.syncIn(srcDir, 'dest', { exclude: ef });
    expect(await result.exists('dest/a.txt')).toBe(true);
    expect(await result.exists('dest/b.pyc')).toBe(false);
  });
});
