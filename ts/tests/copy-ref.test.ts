import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  StaleSnapshotError,
  PermissionError,
} from '../src/index.js';

let store: GitStore;
let tmpDir: string;

function paths(entries: Array<{ path: string }> | undefined): Set<string> {
  return new Set((entries ?? []).map((e) => e.path));
}

beforeEach(async () => {
  const res = await freshStore();
  store = res.store;
  tmpDir = res.tmpDir;

  // Seed main with some files
  let main = await store.branches.get('main');
  main = await main.write('readme.txt', toBytes('hello'));
  main = await main.write('data/x.txt', toBytes('x-main'));

  // Create worker branch from main
  await store.branches.set('worker', main);
  let worker = await store.branches.get('worker');
  worker = await worker.write('results/a.json', toBytes('{"a":1}'));
  worker = await worker.write('results/b.json', toBytes('{"b":2}'));
  worker = await worker.write('data/x.txt', toBytes('x-worker'));
  worker = await worker.write('data/y.txt', toBytes('y-worker'));
});

afterEach(() => rmTmpDir(tmpDir));

describe('copyRef basic', () => {
  it('copies subtree and adds files', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('results/b.json'))).toBe('{"b":2}');
    // Existing files untouched
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });

  it('copies with updates', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'data');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
    expect(fromBytes(await main.read('data/y.txt'))).toBe('y-worker');
  });

  it('defaults dest to src path', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results');
    expect(await main.exists('results/a.json')).toBe(true);
    expect(await main.exists('results/b.json')).toBe(true);
  });

  it('copies to different dest', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results', 'backup/results');
    expect(fromBytes(await main.read('backup/results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('backup/results/b.json'))).toBe('{"b":2}');
    // Original path untouched
    expect(await main.exists('results/a.json')).toBe(false);
  });

  it('copies root to root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker);
    // Worker files present
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
    expect(fromBytes(await main.read('data/y.txt'))).toBe('y-worker');
    // Existing main files still present (no delete)
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });
});

describe('copyRef delete', () => {
  it('removes extra dest files', async () => {
    let main = await store.branches.get('main');
    let worker = await store.branches.get('worker');

    // First sync data/
    main = await main.copyRef(worker, 'data');
    expect(await main.exists('data/y.txt')).toBe(true);

    // Remove y from worker and sync with delete
    worker = await store.branches.get('worker');
    worker = await worker.remove('data/y.txt');
    main = await store.branches.get('main');
    main = await main.copyRef(worker, 'data', null, { delete: true });
    expect(await main.exists('data/x.txt')).toBe(true);
    expect(await main.exists('data/y.txt')).toBe(false);
  });

  it('only affects dest path', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results', null, { delete: true });
    // readme.txt is outside dest_path, should be untouched
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });
});

describe('copyRef dryRun', () => {
  it('does not commit', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');
    const originalHash = main.commitHash;

    const result = await main.copyRef(worker, 'results', null, { dryRun: true });
    expect(result.commitHash).toBe(originalHash);
    expect(result.changes).not.toBeNull();
    expect(result.changes!.add.length).toBe(2);
    // Verify files not actually written
    expect(await result.exists('results/a.json')).toBe(false);
  });

  it('classifies updates', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    const result = await main.copyRef(worker, 'data', null, { dryRun: true });
    expect(result.changes).not.toBeNull();
    expect(paths(result.changes!.update)).toEqual(new Set(['data/x.txt']));
    expect(paths(result.changes!.add)).toEqual(new Set(['data/y.txt']));
  });

  it('classifies deletes', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Put extra file in main's results
    main = await main.write('results/extra.txt', toBytes('extra'));

    const result = await main.copyRef(worker, 'results', null, {
      delete: true,
      dryRun: true,
    });
    expect(result.changes).not.toBeNull();
    expect(paths(result.changes!.delete)).toEqual(new Set(['results/extra.txt']));
  });
});

describe('copyRef from tag', () => {
  it('copies from tag', async () => {
    const worker = await store.branches.get('worker');
    await store.tags.set('v1.0', worker);

    let main = await store.branches.get('main');
    const tagFs = await store.tags.get('v1.0');
    main = await main.copyRef(tagFs, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
  });

  it('copies from detached commit', async () => {
    const worker = await store.branches.get('worker');
    const detached = await FS._fromCommit(store, worker.commitHash, null);

    let main = await store.branches.get('main');
    main = await main.copyRef(detached, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
  });
});

describe('copyRef noop', () => {
  it('returns same fs when source matches dest', async () => {
    let main = await store.branches.get('main');
    let worker = await store.branches.get('worker');

    // Copy results in
    main = await main.copyRef(worker, 'results');
    const hashAfterFirst = main.commitHash;

    // Copy again — same content, should be a noop
    worker = await store.branches.get('worker');
    main = await main.copyRef(worker, 'results');
    expect(main.commitHash).toBe(hashAfterFirst);
  });
});

describe('copyRef validation', () => {
  it('rejects cross-repo', async () => {
    const res2 = await freshStore();
    const store2 = res2.store;
    let fs1 = await store.branches.get('main');
    let fs2 = await store2.branches.get('main');
    fs2 = await fs2.write('b.txt', toBytes('b'));

    await expect(fs1.copyRef(fs2, 'b.txt')).rejects.toThrow('same repo');
    rmTmpDir(res2.tmpDir);
  });

  it('rejects readonly dest', async () => {
    const worker = await store.branches.get('worker');
    const readonly = await FS._fromCommit(store, worker.commitHash, null);

    await expect(readonly.copyRef(worker, 'results')).rejects.toThrow(PermissionError);
  });

  it('nonexistent src path is noop', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');
    const originalHash = main.commitHash;

    main = await main.copyRef(worker, 'nonexistent');
    expect(main.commitHash).toBe(originalHash);
  });
});

describe('copyRef mode', () => {
  it('preserves executable mode', async () => {
    let worker = await store.branches.get('worker');
    worker = await worker.write('bin/run.sh', toBytes('#!/bin/sh'), {
      mode: FileType.EXECUTABLE,
    });

    let main = await store.branches.get('main');
    main = await main.copyRef(worker, 'bin');
    expect(await main.fileType('bin/run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('preserves symlink', async () => {
    let worker = await store.branches.get('worker');
    worker = await worker.writeSymlink('links/readme', '../readme.txt');

    let main = await store.branches.get('main');
    main = await main.copyRef(worker, 'links');
    expect(await main.fileType('links/readme')).toBe(FileType.LINK);
    expect(await main.readlink('links/readme')).toBe('../readme.txt');
  });
});

describe('copyRef message', () => {
  it('uses custom message', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results', null, {
      message: 'Import results from worker',
    });
    expect(await main.getMessage()).toBe('Import results from worker');
  });

  it('generates auto message', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, 'results');
    const msg = await main.getMessage();
    expect(msg).toBeTruthy();
  });
});

describe('copyRef path normalization', () => {
  it('normalizes slashed src and dest paths', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Use slashed paths — should not produce invalid tree entries
    main = await main.copyRef(worker, '/results/', '/imported/');
    const entries = await main.ls('imported');
    expect(entries).toContain('a.json');
    expect(entries).toContain('b.json');
    expect(fromBytes(await main.read('imported/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('imported/b.json'))).toBe('{"b":2}');
  });

  it('root slash src copies root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyRef(worker, '/');
    // Worker files present
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
  });
});

describe('copyRef stale', () => {
  it('propagates stale snapshot error', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Advance main behind our back
    const main2 = await store.branches.get('main');
    await main2.write('conflict.txt', toBytes('conflict'));

    await expect(main.copyRef(worker, 'results')).rejects.toThrow(StaleSnapshotError);
  });
});
