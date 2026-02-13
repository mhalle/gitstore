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
  f = await f.write('a.txt', toBytes('aaa'));
  snap = await f.write('b.txt', toBytes('bbb'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('parent', () => {
  it('root has no parent', async () => {
    // Go back to initial commit
    let f: FS | null = snap;
    while (true) {
      const p = await f!.getParent();
      if (p === null) break;
      f = p;
    }
    expect(await f!.getParent()).toBeNull();
  });

  it('parent chain', async () => {
    const p1 = await snap.getParent();
    expect(p1).not.toBeNull();
    const msg1 = await p1!.getMessage();
    expect(msg1).toContain('a.txt');

    const p2 = await p1!.getParent();
    expect(p2).not.toBeNull();
    const msg2 = await p2!.getMessage();
    expect(msg2).toContain('Initialize');

    expect(await p2!.getParent()).toBeNull();
  });
});

describe('back', () => {
  it('back(0) returns same', async () => {
    const f = await snap.back(0);
    expect(f.commitHash).toBe(snap.commitHash);
  });

  it('back(1) equals parent', async () => {
    const parent = await snap.getParent();
    const back1 = await snap.back(1);
    expect(back1.commitHash).toBe(parent!.commitHash);
  });

  it('back(2) equals grandparent', async () => {
    const gp = await (await snap.getParent())!.getParent();
    const back2 = await snap.back(2);
    expect(back2.commitHash).toBe(gp!.commitHash);
  });

  it('back too far raises', async () => {
    await expect(snap.back(100)).rejects.toThrow(/history too short/);
  });

  it('back negative raises', async () => {
    await expect(snap.back(-1)).rejects.toThrow(/n >= 0/);
  });
});

describe('log', () => {
  it('returns all commits', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log()) entries.push(e);
    expect(entries.length).toBe(3); // init + a.txt + b.txt
  });

  it('newest first', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log()) entries.push(e);
    expect(entries[0].commitHash).toBe(snap.commitHash);
  });

  it('each entry has commitHash and read', async () => {
    for await (const e of snap.log()) {
      expect(e.commitHash).toMatch(/^[0-9a-f]{40}$/);
      // Should be able to read from any snapshot
      const msg = await e.getMessage();
      expect(typeof msg).toBe('string');
    }
  });

  it('filter by path', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log({ path: 'a.txt' })) entries.push(e);
    // Should see the commit that added a.txt
    expect(entries.length).toBeGreaterThanOrEqual(1);
    const msgs = await Promise.all(entries.map((e) => e.getMessage()));
    expect(msgs.some((m) => m.includes('a.txt'))).toBe(true);
  });

  it('path added and removed', async () => {
    let f = await snap.write('temp.txt', toBytes('temp'));
    f = await f.remove('temp.txt');
    const entries: FS[] = [];
    for await (const e of f.log({ path: 'temp.txt' })) entries.push(e);
    // Should see both add and remove
    expect(entries.length).toBeGreaterThanOrEqual(2);
  });

  it('no matches returns empty', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log({ path: 'nope.txt' })) entries.push(e);
    expect(entries.length).toBe(0);
  });

  it('match glob filter', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log({ match: '*a.txt*' })) entries.push(e);
    expect(entries.length).toBeGreaterThanOrEqual(1);
  });

  it('combined path and match', async () => {
    const entries: FS[] = [];
    for await (const e of snap.log({ path: 'a.txt', match: '*a.txt*' })) entries.push(e);
    expect(entries.length).toBeGreaterThanOrEqual(1);
  });
});

describe('commit metadata', () => {
  it('time is Date', async () => {
    const t = await snap.getTime();
    expect(t).toBeInstanceOf(Date);
  });

  it('author name', async () => {
    const name = await snap.getAuthorName();
    expect(name).toBe('gitstore');
  });

  it('author email', async () => {
    const email = await snap.getAuthorEmail();
    expect(email).toBe('gitstore@localhost');
  });
});
