import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir, fs } from './helpers.js';
import { GitStore, FS, PermissionError } from '../src/index.js';

let store: GitStore;
let snap: FS;
let tmpDir: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
  let f = await store.branches.get('main');
  snap = await f.write('hello.txt', toBytes('Hello'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('FsWriter', () => {
  it('write chunks and close', async () => {
    const w = snap.writer('out.bin');
    w.write(new Uint8Array([1, 2, 3]));
    w.write(new Uint8Array([4, 5]));
    await w.close();
    expect(w.fs).not.toBeNull();
    const data = await w.fs!.read('out.bin');
    expect(data).toEqual(new Uint8Array([1, 2, 3, 4, 5]));
  });

  it('write string encodes as UTF-8', async () => {
    const w = snap.writer('text.txt');
    w.write('hello ');
    w.write('world');
    await w.close();
    expect(fromBytes(await w.fs!.read('text.txt'))).toBe('hello world');
  });

  it('result is new snapshot', async () => {
    const w = snap.writer('new.txt');
    w.write(toBytes('data'));
    await w.close();
    expect(w.fs!.commitHash).not.toBe(snap.commitHash);
  });

  it('on tag throws PermissionError', async () => {
    await store.tags.set('v1', snap);
    const tagFs = await store.tags.get('v1');
    expect(() => tagFs.writer('x.txt')).toThrow(PermissionError);
  });

  it('result stays null on no close', () => {
    const w = snap.writer('x.txt');
    w.write(toBytes('data'));
    // don't close
    expect(w.fs).toBeNull();
  });

  it('write after close throws', async () => {
    const w = snap.writer('x.txt');
    w.write(toBytes('data'));
    await w.close();
    expect(() => w.write(toBytes('more'))).toThrow('closed');
  });

  it('double close is idempotent', async () => {
    const w = snap.writer('x.txt');
    w.write(toBytes('data'));
    await w.close();
    const hash = w.fs!.commitHash;
    await w.close();
    expect(w.fs!.commitHash).toBe(hash);
  });

  it('closed property', async () => {
    const w = snap.writer('x.txt');
    expect(w.closed).toBe(false);
    w.write(toBytes('data'));
    await w.close();
    expect(w.closed).toBe(true);
  });
});

describe('BatchWriter', () => {
  it('write chunks then commit batch', async () => {
    const b = snap.batch();
    const w = b.writer('streamed.bin');
    w.write(new Uint8Array([10, 20]));
    w.write(new Uint8Array([30]));
    await w.close();
    const f2 = await b.commit();
    expect(await f2.read('streamed.bin')).toEqual(new Uint8Array([10, 20, 30]));
  });

  it('write string in batch', async () => {
    const b = snap.batch();
    const w = b.writer('log.txt');
    w.write('line 1\n');
    w.write('line 2\n');
    await w.close();
    const f2 = await b.commit();
    expect(fromBytes(await f2.read('log.txt'))).toBe('line 1\nline 2\n');
  });

  it('on closed batch throws', async () => {
    const b = snap.batch();
    await b.commit();
    expect(() => b.writer('x.txt')).toThrow('closed');
  });

  it('write after close throws', async () => {
    const b = snap.batch();
    const w = b.writer('x.txt');
    w.write(toBytes('data'));
    await w.close();
    expect(() => w.write(toBytes('more'))).toThrow('closed');
  });
});
