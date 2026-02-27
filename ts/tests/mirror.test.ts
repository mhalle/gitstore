import { describe, it, expect, afterEach } from 'vitest';
import { freshStore } from './helpers.js';
import { GitStore } from '../src/index.js';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// Helper to create a temp directory for remotes/bundles
function makeTmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'vost-mirror-'));
}

const cleanups: string[] = [];

afterEach(() => {
  for (const d of cleanups) {
    fs.rmSync(d, { recursive: true, force: true });
  }
  cleanups.length = 0;
});

// ---------------------------------------------------------------------------
// backup / restore via local path
// ---------------------------------------------------------------------------

describe('Mirror: local path backup/restore', () => {
  it('backup to local bare repo', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');

    const diff = await store.backup(remoteUrl);
    expect(diff.add.length).toBeGreaterThan(0);

    // Verify remote has the refs
    const remote = await GitStore.open(remoteUrl, { fs });
    expect(await remote.branches.has('main')).toBe(true);
    expect(await (await remote.branches.get('main')).readText('a.txt')).toBe(
      'hello',
    );
  });

  it('restore from local bare repo', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    // Create empty store and restore
    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);

    const diff = await store2.restore(remoteUrl);
    expect(diff.add.length).toBeGreaterThan(0);
    expect(await store2.branches.has('main')).toBe(true);
    expect(
      await (await store2.branches.get('main')).readText('a.txt'),
    ).toBe('hello');
  });

  it('restore is additive', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    // Create a local-only branch
    await store.branches.set('local-only', snap);
    expect(await store.branches.has('local-only')).toBe(true);

    // Restore — local-only should survive
    const diff = await store.restore(remoteUrl);
    expect(diff.delete.length).toBe(0);
    expect(await store.branches.has('local-only')).toBe(true);
  });

  it('dry-run backup makes no changes', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    // Write more data
    snap = await store.branches.get('main');
    snap = await snap.writeText('b.txt', 'world');

    const diff = await store.backup(remoteUrl, { dryRun: true });
    expect(diff.update.length + diff.add.length).toBeGreaterThan(0);

    // Remote should still not have b.txt
    const remote = await GitStore.open(remoteUrl, { fs });
    expect(await (await remote.branches.get('main')).exists('b.txt')).toBe(
      false,
    );
  });

  it('backup deletes stale remote refs', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.branches.set('extra', snap);

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    {
      const remote = await GitStore.open(remoteUrl, { fs });
      expect(await remote.branches.has('extra')).toBe(true);
    }

    // Delete extra locally
    await store.branches.delete('extra');

    // Backup again — should delete from remote
    const diff = await store.backup(remoteUrl);
    expect(diff.delete.some((r) => r.ref.includes('extra'))).toBe(true);

    const remote = await GitStore.open(remoteUrl, { fs });
    expect(await remote.branches.has('extra')).toBe(false);
  });

  it('round-trip backup then restore', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'aaa');
    snap = await snap.writeText('b.txt', 'bbb');
    await store.branches.set('feature', snap);
    let feat = await store.branches.get('feature');
    feat = await feat.writeText('c.txt', 'ccc');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);
    await store2.restore(remoteUrl);

    expect(
      await (await store2.branches.get('main')).readText('a.txt'),
    ).toBe('aaa');
    expect(
      await (await store2.branches.get('main')).readText('b.txt'),
    ).toBe('bbb');
    expect(await store2.branches.has('feature')).toBe(true);
    expect(
      await (await store2.branches.get('feature')).readText('c.txt'),
    ).toBe('ccc');
  });

  it('backup when already in sync', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    const diff = await store.backup(remoteUrl);
    expect(diff.add.length + diff.update.length + diff.delete.length).toBe(0);
  });

  it('backup with tags', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    const remote = await GitStore.open(remoteUrl, { fs });
    expect(await remote.tags.has('v1.0')).toBe(true);
    expect(await (await remote.tags.get('v1.0')).readText('a.txt')).toBe(
      'hello',
    );
  });
});

// ---------------------------------------------------------------------------
// bundle
// ---------------------------------------------------------------------------

describe('Mirror: bundle', () => {
  it('backup to bundle', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const bundlePath = path.join(tmpDir, 'backup.bundle');
    const diff = await store.backup(bundlePath);

    expect(diff.add.length).toBeGreaterThan(0);
    expect(fs.existsSync(bundlePath)).toBe(true);
  });

  it('restore from bundle', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const bundlePath = path.join(tmpDir, 'backup.bundle');
    await store.backup(bundlePath);

    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);

    const diff = await store2.restore(bundlePath);
    expect(diff.add.length).toBeGreaterThan(0);
    expect(await store2.branches.has('main')).toBe(true);
    expect(
      await (await store2.branches.get('main')).readText('a.txt'),
    ).toBe('hello');
    expect(await store2.tags.has('v1.0')).toBe(true);
  });

  it('bundle dry run', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');

    const bundlePath = path.join(tmpDir, 'backup.bundle');
    const diff = await store.backup(bundlePath, { dryRun: true });

    expect(diff.add.length).toBeGreaterThan(0);
    expect(fs.existsSync(bundlePath)).toBe(false);
  });

  it('bundle round trip', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'aaa');
    snap = await snap.writeText('b.txt', 'bbb');
    await store.tags.set('v1.0', snap);

    const bundlePath = path.join(tmpDir, 'roundtrip.bundle');
    await store.backup(bundlePath);

    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);
    await store2.restore(bundlePath);

    expect(
      await (await store2.branches.get('main')).readText('a.txt'),
    ).toBe('aaa');
    expect(
      await (await store2.branches.get('main')).readText('b.txt'),
    ).toBe('bbb');
    expect(await store2.tags.has('v1.0')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// refs filtering
// ---------------------------------------------------------------------------

describe('Mirror: refs filtering', () => {
  it('backup with refs filter', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl, { refs: ['main'] });

    const remote = await GitStore.open(remoteUrl, { fs });
    expect(await remote.branches.has('main')).toBe(true);
    expect(await remote.tags.has('v1.0')).toBe(false);
  });

  it('restore with refs filter', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const remoteDir = makeTmpDir();
    cleanups.push(remoteDir);
    const remoteUrl = path.join(remoteDir, 'remote.git');
    await store.backup(remoteUrl);

    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);
    await store2.restore(remoteUrl, { refs: ['v1.0'] });

    expect(await store2.tags.has('v1.0')).toBe(true);
  });

  it('backup bundle with refs', async () => {
    const { store, tmpDir } = await freshStore();
    cleanups.push(tmpDir);
    let snap = await store.branches.get('main');
    snap = await snap.writeText('a.txt', 'hello');
    await store.tags.set('v1.0', snap);

    const bundlePath = path.join(tmpDir, 'main-only.bundle');
    await store.backup(bundlePath, { refs: ['main'] });

    const { store: store2, tmpDir: td2 } = await freshStore({ branch: null });
    cleanups.push(td2);
    await store2.restore(bundlePath);

    expect(await store2.branches.has('main')).toBe(true);
    expect(await store2.tags.has('v1.0')).toBe(false);
  });
});
