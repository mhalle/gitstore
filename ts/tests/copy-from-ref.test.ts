import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { freshStore, toBytes, fromBytes, rmTmpDir } from './helpers.js';
import {
  GitStore,
  FS,
  FileType,
  StaleSnapshotError,
  PermissionError,
  FileNotFoundError,
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

describe('copyFromRef basic', () => {
  it('copies subtree and adds files (dir mode)', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('results/b.json'))).toBe('{"b":2}');
    // Existing files untouched
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });

  it('copies with updates (dir mode)', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'data');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
    expect(fromBytes(await main.read('data/y.txt'))).toBe('y-worker');
  });

  it('defaults dest to root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results');
    expect(await main.exists('results/a.json')).toBe(true);
    expect(await main.exists('results/b.json')).toBe(true);
  });

  it('copies contents to different dest', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results/', 'backup/results');
    expect(fromBytes(await main.read('backup/results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('backup/results/b.json'))).toBe('{"b":2}');
    // Original path untouched
    expect(await main.exists('results/a.json')).toBe(false);
  });

  it('copies root to root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker);
    // Worker files present
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
    expect(fromBytes(await main.read('data/y.txt'))).toBe('y-worker');
    // Existing main files still present (no delete)
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });
});

describe('copyFromRef delete', () => {
  it('removes extra dest files', async () => {
    let main = await store.branches.get('main');
    let worker = await store.branches.get('worker');

    // First sync data/
    main = await main.copyFromRef(worker, 'data');
    expect(await main.exists('data/y.txt')).toBe(true);

    // Remove y from worker and sync with delete
    worker = await store.branches.get('worker');
    worker = await worker.remove('data/y.txt');
    main = await store.branches.get('main');
    main = await main.copyFromRef(
      await store.branches.get('worker'),
      'data',
      '',
      { delete: true },
    );
    expect(await main.exists('data/x.txt')).toBe(true);
    expect(await main.exists('data/y.txt')).toBe(false);
  });

  it('only affects dest path', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results', '', { delete: true });
    // readme.txt is outside dest_path, should be untouched
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });

  it('delete with dir mode', async () => {
    let main = await store.branches.get('main');
    let worker = await store.branches.get('worker');

    // First copy results into main
    main = await main.copyFromRef(worker, 'results');
    // Add an extra file under results/
    main = await main.write('results/extra.txt', toBytes('extra'));

    // Now copy again with delete — extra.txt should be removed
    worker = await store.branches.get('worker');
    main = await main.copyFromRef(worker, 'results', '', { delete: true });
    expect(await main.exists('results/a.json')).toBe(true);
    expect(await main.exists('results/b.json')).toBe(true);
    expect(await main.exists('results/extra.txt')).toBe(false);
  });
});

describe('copyFromRef dryRun', () => {
  it('does not commit', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');
    const originalHash = main.commitHash;

    const result = await main.copyFromRef(worker, 'results', '', { dryRun: true });
    expect(result.commitHash).toBe(originalHash);
    expect(result.changes).not.toBeNull();
    expect(result.changes!.add.length).toBe(2);
    // Verify files not actually written
    expect(await result.exists('results/a.json')).toBe(false);
  });

  it('classifies updates', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    const result = await main.copyFromRef(worker, 'data', '', { dryRun: true });
    expect(result.changes).not.toBeNull();
    expect(paths(result.changes!.update)).toEqual(new Set(['data/x.txt']));
    expect(paths(result.changes!.add)).toEqual(new Set(['data/y.txt']));
  });

  it('classifies deletes', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Put extra file in main's results
    main = await main.write('results/extra.txt', toBytes('extra'));

    const result = await main.copyFromRef(worker, 'results', '', {
      delete: true,
      dryRun: true,
    });
    expect(result.changes).not.toBeNull();
    expect(paths(result.changes!.delete)).toEqual(new Set(['results/extra.txt']));
  });
});

describe('copyFromRef from tag', () => {
  it('copies from tag', async () => {
    const worker = await store.branches.get('worker');
    await store.tags.set('v1.0', worker);

    let main = await store.branches.get('main');
    const tagFs = await store.tags.get('v1.0');
    main = await main.copyFromRef(tagFs, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
  });

  it('copies from detached commit', async () => {
    const worker = await store.branches.get('worker');
    const detached = await FS._fromCommit(store, worker.commitHash, null);

    let main = await store.branches.get('main');
    main = await main.copyFromRef(detached, 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
  });
});

describe('copyFromRef noop', () => {
  it('returns same fs when source matches dest', async () => {
    let main = await store.branches.get('main');
    let worker = await store.branches.get('worker');

    // Copy results in
    main = await main.copyFromRef(worker, 'results');
    const hashAfterFirst = main.commitHash;

    // Copy again — same content, should be a noop
    worker = await store.branches.get('worker');
    main = await main.copyFromRef(worker, 'results');
    expect(main.commitHash).toBe(hashAfterFirst);
  });
});

describe('copyFromRef validation', () => {
  it('rejects cross-repo', async () => {
    const res2 = await freshStore();
    const store2 = res2.store;
    let fs1 = await store.branches.get('main');
    let fs2 = await store2.branches.get('main');
    fs2 = await fs2.write('b.txt', toBytes('b'));

    await expect(fs1.copyFromRef(fs2, 'b.txt')).rejects.toThrow('same repo');
    rmTmpDir(res2.tmpDir);
  });

  it('rejects readonly dest', async () => {
    const worker = await store.branches.get('worker');
    const readonly = await FS._fromCommit(store, worker.commitHash, null);

    await expect(readonly.copyFromRef(worker, 'results')).rejects.toThrow(PermissionError);
  });

  it('nonexistent src raises FileNotFoundError', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    await expect(main.copyFromRef(worker, 'nonexistent')).rejects.toThrow(FileNotFoundError);
  });
});

describe('copyFromRef mode', () => {
  it('preserves executable mode', async () => {
    let worker = await store.branches.get('worker');
    worker = await worker.write('bin/run.sh', toBytes('#!/bin/sh'), {
      mode: FileType.EXECUTABLE,
    });

    let main = await store.branches.get('main');
    main = await main.copyFromRef(worker, 'bin');
    expect(await main.fileType('bin/run.sh')).toBe(FileType.EXECUTABLE);
  });

  it('preserves symlink', async () => {
    let worker = await store.branches.get('worker');
    worker = await worker.writeSymlink('links/readme', '../readme.txt');

    let main = await store.branches.get('main');
    main = await main.copyFromRef(worker, 'links');
    expect(await main.fileType('links/readme')).toBe(FileType.LINK);
    expect(await main.readlink('links/readme')).toBe('../readme.txt');
  });
});

describe('copyFromRef message', () => {
  it('uses custom message', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results', '', {
      message: 'Import results from worker',
    });
    expect(await main.getMessage()).toBe('Import results from worker');
  });

  it('generates auto message', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results');
    const msg = await main.getMessage();
    expect(msg).toBeTruthy();
  });
});

describe('copyFromRef path normalization', () => {
  it('trailing slash = contents mode', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Trailing slash → contents mode: pour into root
    main = await main.copyFromRef(worker, 'results/');
    expect(fromBytes(await main.read('a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('b.json'))).toBe('{"b":2}');
  });

  it('contents mode to explicit dest', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results/', 'imported');
    const entries = await main.ls('imported');
    expect(entries).toContain('a.json');
    expect(entries).toContain('b.json');
    expect(fromBytes(await main.read('imported/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('imported/b.json'))).toBe('{"b":2}');
  });

  it('root slash src copies root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, '/');
    // Worker files present
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
  });
});

describe('copyFromRef stale', () => {
  it('propagates stale snapshot error', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    // Advance main behind our back
    const main2 = await store.branches.get('main');
    await main2.write('conflict.txt', toBytes('conflict'));

    await expect(main.copyFromRef(worker, 'results')).rejects.toThrow(StaleSnapshotError);
  });
});

describe('copyFromRef single file', () => {
  it('single file to root', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results/a.json');
    expect(fromBytes(await main.read('a.json'))).toBe('{"a":1}');
  });

  it('single file to dest', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results/a.json', 'backup');
    expect(fromBytes(await main.read('backup/a.json'))).toBe('{"a":1}');
  });

  it('single file dry run', async () => {
    const main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    const result = await main.copyFromRef(worker, 'results/a.json', '', { dryRun: true });
    expect(result.changes).not.toBeNull();
    expect(result.changes!.add.length).toBe(1);
    expect(result.changes!.add[0].path).toBe('a.json');
  });
});

describe('copyFromRef dir vs contents mode', () => {
  it('dir mode to explicit dest preserves dirname', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results', 'backup');
    expect(fromBytes(await main.read('backup/results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('backup/results/b.json'))).toBe('{"b":2}');
  });

  it('contents mode to explicit dest omits dirname', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, 'results/', 'backup');
    expect(fromBytes(await main.read('backup/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('backup/b.json'))).toBe('{"b":2}');
    expect(await main.exists('backup/results')).toBe(false);
  });
});

describe('copyFromRef multiple sources', () => {
  it('multiple mixed sources', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, ['results', 'data/x.txt']);
    // Dir mode: results/ → results/
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('results/b.json'))).toBe('{"b":2}');
    // File mode: data/x.txt → x.txt at root
    expect(fromBytes(await main.read('x.txt'))).toBe('x-worker');
  });

  it('multiple sources to dest', async () => {
    let main = await store.branches.get('main');
    const worker = await store.branches.get('worker');

    main = await main.copyFromRef(worker, ['results/', 'data/x.txt'], 'backup');
    // Contents: results/ contents poured into backup/
    expect(fromBytes(await main.read('backup/a.json'))).toBe('{"a":1}');
    // File: x.txt placed in backup/
    expect(fromBytes(await main.read('backup/x.txt'))).toBe('x-worker');
  });
});

describe('copyFromRef by name', () => {
  let store: GitStore;
  let tmpDir: string;

  beforeEach(async () => {
    ({ store, tmpDir } = await freshStore());

    // Seed main with some files
    let main = await store.branches.get('main');
    main = await main.writeText('readme.txt', 'hello');
    main = await main.writeText('data/x.txt', 'x-main');

    // Create worker branch from main
    await store.branches.set('worker', main);
    let worker = await store.branches.get('worker');
    worker = await worker.writeText('results/a.json', '{"a":1}');
    worker = await worker.writeText('results/b.json', '{"b":2}');
    worker = await worker.writeText('data/x.txt', 'x-worker');
  });

  it('copies from branch name string', async () => {
    let main = await store.branches.get('main');
    main = await main.copyFromRef('worker', 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
    expect(fromBytes(await main.read('results/b.json'))).toBe('{"b":2}');
    expect(fromBytes(await main.read('readme.txt'))).toBe('hello');
  });

  it('copies from tag name string', async () => {
    const worker = await store.branches.get('worker');
    await store.tags.set('v1', worker);
    let main = await store.branches.get('main');
    main = await main.copyFromRef('v1', 'results');
    expect(fromBytes(await main.read('results/a.json'))).toBe('{"a":1}');
  });

  it('throws for nonexistent name', async () => {
    const main = await store.branches.get('main');
    await expect(main.copyFromRef('no-such-branch', 'results'))
      .rejects.toThrow(/Cannot resolve/);
  });

  it('prefers branch over tag with same name', async () => {
    // Create tag 'worker' pointing to main (different content)
    const mainFs = await store.branches.get('main');
    await store.tags.set('worker', mainFs);
    let main = await store.branches.get('main');
    main = await main.copyFromRef('worker', 'data');
    // Should get worker branch's version, not main's
    expect(fromBytes(await main.read('data/x.txt'))).toBe('x-worker');
  });
});
