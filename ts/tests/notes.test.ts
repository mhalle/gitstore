import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import git from 'isomorphic-git';
import { freshStore, toBytes, rmTmpDir, fs } from './helpers.js';
import {
  GitStore,
  NoteDict,
  NoteNamespace,
  NotesBatch,
  GitStoreError,
  MODE_BLOB,
  MODE_TREE,
} from '../src/index.js';

let store: GitStore;
let tmpDir: string;
let commitHash: string;

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;
  const snap = await store.branches.get('main');
  commitHash = snap.commitHash;
});

afterEach(() => rmTmpDir(tmpDir));

// ---------------------------------------------------------------------------
// Helper: create a note in 2/38 fanout layout directly via isomorphic-git
// ---------------------------------------------------------------------------

async function createFanoutNote(
  store: GitStore,
  namespace: string,
  hash: string,
  text: string,
): Promise<void> {
  const fsModule = store._fsModule;
  const gitdir = store._gitdir;
  const refName = `refs/notes/${namespace}`;

  // Create blob
  const blobOid = await git.writeBlob({
    fs: fsModule,
    gitdir,
    blob: new TextEncoder().encode(text),
  });

  // Build subtree: h[2:] -> blob
  const prefix = hash.slice(0, 2);
  const suffix = hash.slice(2);
  const subTreeOid = await git.writeTree({
    fs: fsModule,
    gitdir,
    tree: [{ mode: MODE_BLOB, path: suffix, oid: blobOid, type: 'blob' }],
  });

  // Build root tree: existing entries + fanout dir
  let parents: string[] = [];
  let rootEntries: Array<{ mode: string; path: string; oid: string; type: string }> = [];

  try {
    const tipOid = await git.resolveRef({ fs: fsModule, gitdir, ref: refName });
    parents = [tipOid];
    const { commit: c } = await git.readCommit({ fs: fsModule, gitdir, oid: tipOid });
    const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: c.tree });
    rootEntries = tree.map((e) => ({
      mode: e.mode,
      path: e.path,
      oid: e.oid,
      type: e.mode === MODE_TREE ? 'tree' : 'blob',
    }));
  } catch {
    // No existing ref
  }

  rootEntries.push({ mode: MODE_TREE, path: prefix, oid: subTreeOid, type: 'tree' });

  const rootTreeOid = await git.writeTree({ fs: fsModule, gitdir, tree: rootEntries });

  const now = Math.floor(Date.now() / 1000);
  const commitOid = await git.writeCommit({
    fs: fsModule,
    gitdir,
    commit: {
      message: 'fanout note\n',
      tree: rootTreeOid,
      parent: parents,
      author: { name: 'test', email: 'test@test', timestamp: now, timezoneOffset: 0 },
      committer: { name: 'test', email: 'test@test', timestamp: now, timezoneOffset: 0 },
    },
  });

  await git.writeRef({ fs: fsModule, gitdir, ref: refName, value: commitOid, force: true });
}

// ---------------------------------------------------------------------------
// Basic CRUD
// ---------------------------------------------------------------------------

describe('basic CRUD', () => {
  it('set and get', async () => {
    await store.notes.commits.set(commitHash, 'hello');
    expect(await store.notes.commits.get(commitHash)).toBe('hello');
  });

  it('get missing throws', async () => {
    await expect(store.notes.commits.get(commitHash)).rejects.toThrow(GitStoreError);
  });

  it('has returns true', async () => {
    await store.notes.commits.set(commitHash, 'note');
    expect(await store.notes.commits.has(commitHash)).toBe(true);
  });

  it('has returns false', async () => {
    expect(await store.notes.commits.has(commitHash)).toBe(false);
  });

  it('delete', async () => {
    await store.notes.commits.set(commitHash, 'note');
    await store.notes.commits.delete(commitHash);
    expect(await store.notes.commits.has(commitHash)).toBe(false);
  });

  it('delete missing throws', async () => {
    await expect(store.notes.commits.delete(commitHash)).rejects.toThrow(GitStoreError);
  });

  it('overwrite', async () => {
    await store.notes.commits.set(commitHash, 'first');
    await store.notes.commits.set(commitHash, 'second');
    expect(await store.notes.commits.get(commitHash)).toBe('second');
  });

  it('empty note text', async () => {
    await store.notes.commits.set(commitHash, '');
    expect(await store.notes.commits.get(commitHash)).toBe('');
  });
});

// ---------------------------------------------------------------------------
// getCurrentRef
// ---------------------------------------------------------------------------

describe('getCurrentRef', () => {
  it('read current ref', async () => {
    await store.notes.commits.set(commitHash, 'my note');
    expect(await store.notes.commits.getCurrentRef()).toBe('my note');
  });

  it('write current ref', async () => {
    await store.notes.commits.setCurrentRef('written via method');
    expect(await store.notes.commits.get(commitHash)).toBe('written via method');
  });

  it('no note raises', async () => {
    await expect(store.notes.commits.getCurrentRef()).rejects.toThrow(GitStoreError);
  });

  it('after new commit', async () => {
    const snap = await store.branches.get('main');
    await store.notes.commits.set(snap.commitHash, 'note on old');
    // Create a new commit
    await snap.write('file.txt', toBytes('data'));
    // current_ref should now point to the new commit (which has no note)
    await expect(store.notes.commits.getCurrentRef()).rejects.toThrow(GitStoreError);
  });
});

// ---------------------------------------------------------------------------
// Iteration / size
// ---------------------------------------------------------------------------

describe('iteration', () => {
  it('list empty', async () => {
    expect(await store.notes.commits.list()).toEqual([]);
  });

  it('list multiple', async () => {
    const fs1 = await store.branches.get('main');
    const h1 = fs1.commitHash;
    const fs2 = await fs1.write('a.txt', toBytes('a'));
    const h2 = fs2.commitHash;
    await store.notes.commits.set(h1, 'note1');
    await store.notes.commits.set(h2, 'note2');
    const hashes = await store.notes.commits.list();
    expect(new Set(hashes)).toEqual(new Set([h1, h2]));
  });

  it('size empty', async () => {
    expect(await store.notes.commits.size()).toBe(0);
  });

  it('size after adds', async () => {
    const fs1 = await store.branches.get('main');
    const h1 = fs1.commitHash;
    const fs2 = await fs1.write('a.txt', toBytes('a'));
    const h2 = fs2.commitHash;
    await store.notes.commits.set(h1, 'n1');
    await store.notes.commits.set(h2, 'n2');
    expect(await store.notes.commits.size()).toBe(2);
  });

  it('size after delete', async () => {
    await store.notes.commits.set(commitHash, 'note');
    expect(await store.notes.commits.size()).toBe(1);
    await store.notes.commits.delete(commitHash);
    expect(await store.notes.commits.size()).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe('edge cases', () => {
  it('unicode text', async () => {
    const text = 'Unicode: \u00e9\u00e8\u00ea \u2603 \uD83D\uDE00';
    await store.notes.commits.set(commitHash, text);
    expect(await store.notes.commits.get(commitHash)).toBe(text);
  });

  it('multiline text', async () => {
    const text = 'line1\nline2\nline3\n';
    await store.notes.commits.set(commitHash, text);
    expect(await store.notes.commits.get(commitHash)).toBe(text);
  });

  it('invalid hash raises', async () => {
    await expect(store.notes.commits.set('not-a-hash', 'note')).rejects.toThrow(GitStoreError);
  });

  it('invalid hash too short', async () => {
    await expect(store.notes.commits.set('abcd', 'note')).rejects.toThrow(GitStoreError);
  });

  it('uppercase hash rejected', async () => {
    await expect(store.notes.commits.set('A'.repeat(40), 'note')).rejects.toThrow(GitStoreError);
  });

  it('note on nonexistent commit', async () => {
    const fakeHash = 'a'.repeat(40);
    await store.notes.commits.set(fakeHash, 'orphan note');
    expect(await store.notes.commits.get(fakeHash)).toBe('orphan note');
  });
});

// ---------------------------------------------------------------------------
// Commit chain
// ---------------------------------------------------------------------------

describe('commit chain', () => {
  it('first note no parent', async () => {
    await store.notes.commits.set(commitHash, 'first');
    const tipOid = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: 'refs/notes/commits',
    });
    const { commit } = await git.readCommit({
      fs: store._fsModule,
      gitdir: store._gitdir,
      oid: tipOid,
    });
    expect(commit.parent).toEqual([]);
  });

  it('second note has parent', async () => {
    const fs1 = await store.branches.get('main');
    const h1 = fs1.commitHash;
    const fs2 = await fs1.write('f.txt', toBytes('x'));
    const h2 = fs2.commitHash;

    await store.notes.commits.set(h1, 'first');
    const firstTip = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: 'refs/notes/commits',
    });

    await store.notes.commits.set(h2, 'second');
    const secondTip = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: 'refs/notes/commits',
    });
    const { commit } = await git.readCommit({
      fs: store._fsModule,
      gitdir: store._gitdir,
      oid: secondTip,
    });
    expect(commit.parent).toEqual([firstTip]);
  });

  it('multiple notes chain', async () => {
    let snap = await store.branches.get('main');
    const hashes = [snap.commitHash];
    for (let i = 0; i < 3; i++) {
      snap = await snap.write(`f${i}.txt`, toBytes('x'));
      hashes.push(snap.commitHash);
    }
    for (let i = 0; i < hashes.length; i++) {
      await store.notes.commits.set(hashes[i], `note ${i}`);
    }

    // Walk the chain
    let tip: string | null = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: 'refs/notes/commits',
    });
    let chainLen = 0;
    while (tip !== null) {
      const { commit } = await git.readCommit({
        fs: store._fsModule,
        gitdir: store._gitdir,
        oid: tip,
      });
      chainLen++;
      tip = commit.parent.length > 0 ? commit.parent[0] : null;
    }
    expect(chainLen).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// Fanout interop
// ---------------------------------------------------------------------------

describe('fanout interop', () => {
  it('read fanout note', async () => {
    await createFanoutNote(store, 'commits', commitHash, 'fanout note');
    expect(await store.notes.commits.get(commitHash)).toBe('fanout note');
  });

  it('list fanout', async () => {
    await createFanoutNote(store, 'commits', commitHash, 'fanout');
    const hashes = await store.notes.commits.list();
    expect(hashes).toContain(commitHash);
  });

  it('has fanout', async () => {
    await createFanoutNote(store, 'commits', commitHash, 'fanout');
    expect(await store.notes.commits.has(commitHash)).toBe(true);
  });

  it('delete fanout', async () => {
    await createFanoutNote(store, 'commits', commitHash, 'fanout');
    await store.notes.commits.delete(commitHash);
    expect(await store.notes.commits.has(commitHash)).toBe(false);
  });

  it('overwrite fanout with flat', async () => {
    await createFanoutNote(store, 'commits', commitHash, 'fanout original');
    await store.notes.commits.set(commitHash, 'flat replacement');
    expect(await store.notes.commits.get(commitHash)).toBe('flat replacement');
  });
});

// ---------------------------------------------------------------------------
// NoteDict container
// ---------------------------------------------------------------------------

describe('NoteDict', () => {
  it('commits property', () => {
    const ns = store.notes.commits;
    expect(ns).toBeInstanceOf(NoteNamespace);
    expect(ns._namespace).toBe('commits');
  });

  it('custom namespace', async () => {
    const reviews = store.notes.namespace('reviews');
    expect(reviews).toBeInstanceOf(NoteNamespace);
    await reviews.set(commitHash, 'LGTM');
    expect(await store.notes.namespace('reviews').get(commitHash)).toBe('LGTM');
  });

  it('separate namespaces independent', async () => {
    await store.notes.commits.set(commitHash, 'default note');
    await store.notes.namespace('reviews').set(commitHash, 'review note');
    expect(await store.notes.commits.get(commitHash)).toBe('default note');
    expect(await store.notes.namespace('reviews').get(commitHash)).toBe('review note');
  });

  it('toString', () => {
    expect(store.notes.toString()).toContain('NoteDict');
  });
});

// ---------------------------------------------------------------------------
// Batch
// ---------------------------------------------------------------------------

describe('batch', () => {
  it('multiple writes single commit', async () => {
    const fs1 = await store.branches.get('main');
    const h1 = fs1.commitHash;
    const fs2 = await fs1.write('a.txt', toBytes('a'));
    const h2 = fs2.commitHash;

    const b = store.notes.commits.batch();
    await b.set(h1, 'note 1');
    await b.set(h2, 'note 2');
    await b.commit();

    expect(await store.notes.commits.get(h1)).toBe('note 1');
    expect(await store.notes.commits.get(h2)).toBe('note 2');

    // Only one commit on the notes ref (no parents)
    const tipOid = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: 'refs/notes/commits',
    });
    const { commit } = await git.readCommit({
      fs: store._fsModule,
      gitdir: store._gitdir,
      oid: tipOid,
    });
    expect(commit.parent).toEqual([]);
  });

  it('write and delete', async () => {
    await store.notes.commits.set(commitHash, 'old');

    const fs2 = (await store.branches.get('main'));
    const snap2 = await fs2.write('a.txt', toBytes('a'));
    const h2 = snap2.commitHash;

    const b = store.notes.commits.batch();
    b.delete(commitHash);
    await b.set(h2, 'new');
    await b.commit();

    expect(await store.notes.commits.has(commitHash)).toBe(false);
    expect(await store.notes.commits.get(h2)).toBe('new');
  });

  it('delete missing raises', async () => {
    const b = store.notes.commits.batch();
    b.delete(commitHash);
    await expect(b.commit()).rejects.toThrow(GitStoreError);
  });

  it('overwrite in batch', async () => {
    const b = store.notes.commits.batch();
    await b.set(commitHash, 'first');
    await b.set(commitHash, 'second');
    await b.commit();

    expect(await store.notes.commits.get(commitHash)).toBe('second');
  });

  it('noop no commit', async () => {
    const b = store.notes.commits.batch();
    await b.commit();
    // No notes ref should exist
    try {
      await git.resolveRef({
        fs: store._fsModule,
        gitdir: store._gitdir,
        ref: 'refs/notes/commits',
      });
      expect.fail('should not have created ref');
    } catch {
      // expected
    }
  });

  it('set then delete same hash no prior', async () => {
    const b = store.notes.commits.batch();
    await b.set(commitHash, 'will be deleted');
    b.delete(commitHash);
    await expect(b.commit()).rejects.toThrow(GitStoreError);
  });

  it('set then delete same hash with prior', async () => {
    await store.notes.commits.set(commitHash, 'original');

    const b = store.notes.commits.batch();
    await b.set(commitHash, 'overwritten');
    b.delete(commitHash);
    await b.commit();

    expect(await store.notes.commits.has(commitHash)).toBe(false);
  });

  it('delete then set same hash', async () => {
    await store.notes.commits.set(commitHash, 'original');

    const b = store.notes.commits.batch();
    b.delete(commitHash);
    await b.set(commitHash, 'restored');
    await b.commit();

    expect(await store.notes.commits.get(commitHash)).toBe('restored');
  });

  it('closed batch rejects', async () => {
    const b = store.notes.commits.batch();
    await b.commit();
    await expect(b.set(commitHash, 'x')).rejects.toThrow(GitStoreError);
    await expect(b.commit()).rejects.toThrow(GitStoreError);
  });

  it('validation in batch', async () => {
    const b = store.notes.commits.batch();
    await expect(b.set('bad', 'note')).rejects.toThrow(GitStoreError);
  });
});

// ---------------------------------------------------------------------------
// Mapping extras (get with default via try/catch)
// ---------------------------------------------------------------------------

describe('mapping extras', () => {
  it('get with default', async () => {
    let result: string;
    try {
      result = await store.notes.commits.get(commitHash);
    } catch {
      result = 'default';
    }
    expect(result).toBe('default');

    await store.notes.commits.set(commitHash, 'note');
    result = await store.notes.commits.get(commitHash);
    expect(result).toBe('note');
  });

  it('list returns all hashes', async () => {
    const fs1 = await store.branches.get('main');
    const h1 = fs1.commitHash;
    const fs2 = await fs1.write('a.txt', toBytes('a'));
    const h2 = fs2.commitHash;
    await store.notes.commits.set(h1, 'n1');
    await store.notes.commits.set(h2, 'n2');

    const hashes = await store.notes.commits.list();
    expect(new Set(hashes)).toEqual(new Set([h1, h2]));
  });
});
