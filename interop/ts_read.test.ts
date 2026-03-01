/**
 * Read repos written by Python and verify contents match fixtures.
 * Usage: npx tsx interop/ts_read.test.ts <fixtures.json> <repo_dir>
 */

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { GitStore, FileType, fileTypeFromMode } from '../ts/src/index.js';

interface Spec {
  branch?: string;
  files?: Record<string, string>;
  symlinks?: Record<string, string>;
  binary_files?: Record<string, string>;
  executable_files?: Record<string, string>;
  commits?: Array<{
    message: string;
    files?: Record<string, string>;
    removes?: string[];
  }>;
  notes?: Record<string, string>;
}

function b64ToBytes(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

async function checkBasic(snapshot: Awaited<ReturnType<typeof GitStore.prototype.branches.get>>, spec: Spec, name: string): Promise<number> {
  let failures = 0;

  // Text files
  for (const [filepath, expected] of Object.entries(spec.files ?? {})) {
    const actual = await snapshot.readText(filepath);
    if (actual !== expected) {
      console.log(`  FAIL ${name}: ${filepath} content expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
      failures++;
    } else {
      console.log(`  OK   ${name}: ${filepath}`);
    }
  }

  // Symlinks
  for (const [filepath, expectedTarget] of Object.entries(spec.symlinks ?? {})) {
    const actualTarget = await snapshot.readlink(filepath);
    if (actualTarget !== expectedTarget) {
      console.log(`  FAIL ${name}: ${filepath} link target expected ${JSON.stringify(expectedTarget)}, got ${JSON.stringify(actualTarget)}`);
      failures++;
    } else {
      console.log(`  OK   ${name}: symlink ${filepath} -> ${actualTarget}`);
    }
  }

  // Binary files
  for (const [filepath, b64] of Object.entries(spec.binary_files ?? {})) {
    const expectedBytes = b64ToBytes(b64);
    const actualBytes = await snapshot.read(filepath);
    if (!bytesEqual(actualBytes, expectedBytes)) {
      console.log(`  FAIL ${name}: ${filepath} binary content mismatch`);
      failures++;
    } else {
      console.log(`  OK   ${name}: binary ${filepath} (${actualBytes.length} bytes)`);
    }
  }

  // Executable files
  for (const [filepath, expected] of Object.entries(spec.executable_files ?? {})) {
    const actual = await snapshot.readText(filepath);
    if (actual !== expected) {
      console.log(`  FAIL ${name}: ${filepath} content expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
      failures++;
      continue;
    }
    // Check mode via walk
    let found = false;
    for await (const [dirpath, , entries] of snapshot.walk()) {
      for (const entry of entries) {
        const rel = dirpath ? `${dirpath}/${entry.name}` : entry.name;
        if (rel === filepath) {
          const ft = fileTypeFromMode(entry.mode);
          if (ft !== FileType.EXECUTABLE) {
            console.log(`  FAIL ${name}: ${filepath} expected EXECUTABLE, got ${ft}`);
            failures++;
          } else {
            console.log(`  OK   ${name}: executable ${filepath}`);
          }
          found = true;
          break;
        }
      }
      if (found) break;
    }
  }

  // Verify file count
  const allFiles = new Set<string>();
  for await (const [dirpath, , entries] of snapshot.walk()) {
    for (const entry of entries) {
      const rel = dirpath ? `${dirpath}/${entry.name}` : entry.name;
      allFiles.add(rel);
    }
  }
  const expectedFiles = new Set([
    ...Object.keys(spec.files ?? {}),
    ...Object.keys(spec.symlinks ?? {}),
    ...Object.keys(spec.binary_files ?? {}),
    ...Object.keys(spec.executable_files ?? {}),
  ]);

  const extra = [...allFiles].filter((f) => !expectedFiles.has(f));
  const missing = [...expectedFiles].filter((f) => !allFiles.has(f));
  if (extra.length > 0) {
    console.log(`  FAIL ${name}: unexpected files ${JSON.stringify(extra)}`);
    failures++;
  }
  if (missing.length > 0) {
    console.log(`  FAIL ${name}: missing files ${JSON.stringify(missing)}`);
    failures++;
  }

  return failures;
}

async function checkHistory(store: GitStore, branch: string, spec: Spec, name: string): Promise<number> {
  let failures = 0;
  let snapshot = await store.branches.get(branch);

  // Final state: last commit's cumulative result
  const last = spec.commits![spec.commits!.length - 1];
  for (const [filepath, expected] of Object.entries(last.files ?? {})) {
    const actual = await snapshot.readText(filepath);
    if (actual !== expected) {
      console.log(`  FAIL ${name}: HEAD ${filepath} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
      failures++;
    } else {
      console.log(`  OK   ${name}: HEAD ${filepath}`);
    }
  }

  // Removed files should not exist
  for (const filepath of last.removes ?? []) {
    if (await snapshot.exists(filepath)) {
      console.log(`  FAIL ${name}: ${filepath} should have been removed`);
      failures++;
    } else {
      console.log(`  OK   ${name}: ${filepath} removed`);
    }
  }

  // Check we can walk back through history
  const numCommits = spec.commits!.length;
  const backSnapshot = await snapshot.back(numCommits - 1);
  const first = spec.commits![0];
  for (const [filepath, expected] of Object.entries(first.files ?? {})) {
    const actual = await backSnapshot.readText(filepath);
    if (actual !== expected) {
      console.log(`  FAIL ${name}: commit[0] ${filepath} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
      failures++;
    } else {
      console.log(`  OK   ${name}: commit[0] ${filepath}`);
    }
  }

  // Verify commit count by walking parents
  let count = 0;
  let current = snapshot;
  while (true) {
    count++;
    const parent = await current.getParent();
    if (parent === null) break;
    current = parent;
  }
  // +1 for the initial empty commit created by GitStore.open
  if (count !== numCommits + 1) {
    console.log(`  FAIL ${name}: expected ${numCommits + 1} commits, found ${count}`);
    failures++;
  } else {
    console.log(`  OK   ${name}: ${count} commits in history`);
  }

  return failures;
}

async function main() {
  const fixturesPath = process.argv[2];
  const repoDir = process.argv[3];
  const prefix = process.argv[4] ?? 'py';
  const mode = process.argv[5] ?? 'repo';

  const fixtures: Record<string, Spec> = JSON.parse(fs.readFileSync(fixturesPath, 'utf-8'));
  let failures = 0;
  const tempDirs: string[] = [];
  const bundleTmpMap = new Map<string, string>();

  for (const [name, spec] of Object.entries(fixtures)) {
    const branch = spec.branch ?? 'main';
    let store: GitStore;

    if (mode === 'bundle') {
      const bundlePath = path.join(repoDir, `${prefix}_${name}.bundle`);
      if (!fs.existsSync(bundlePath)) {
        console.log(`  FAIL ${name}: bundle not found at ${bundlePath}`);
        failures++;
        continue;
      }
      const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vost-bundle-'));
      tempDirs.push(tmpDir);
      bundleTmpMap.set(name, tmpDir);
      store = await GitStore.open(tmpDir, { fs, branch });
      await store.restore(bundlePath);
    } else {
      const repoPath = path.join(repoDir, `${prefix}_${name}.git`);
      if (!fs.existsSync(repoPath)) {
        console.log(`  FAIL ${name}: repo not found at ${repoPath}`);
        failures++;
        continue;
      }
      store = await GitStore.open(repoPath, { fs, create: false });
    }

    if (spec.commits) {
      failures += await checkHistory(store, branch, spec, name);
    } else {
      const snapshot = await store.branches.get(branch);
      failures += await checkBasic(snapshot, spec, name);
    }
  }

  // Check notes
  for (const [name, spec] of Object.entries(fixtures)) {
    if (!spec.notes) continue;

    let notesStore: GitStore;
    if (mode === 'bundle') {
      const tmpDir = bundleTmpMap.get(name);
      if (!tmpDir) continue;
      notesStore = await GitStore.open(tmpDir, { fs, create: false });
    } else {
      const repoPath = path.join(repoDir, `${prefix}_${name}.git`);
      if (!fs.existsSync(repoPath)) continue;
      notesStore = await GitStore.open(repoPath, { fs, create: false });
    }

    const branch = spec.branch ?? 'main';
    const snapshot = await notesStore.branches.get(branch);
    const commitHash = snapshot.commitHash;

    for (const [namespace, expectedText] of Object.entries(spec.notes)) {
      try {
        const actual = await notesStore.notes.namespace(namespace).get(commitHash);
        if (actual !== expectedText) {
          console.log(`  FAIL ${name}: notes[${namespace}] expected ${JSON.stringify(expectedText)}, got ${JSON.stringify(actual)}`);
          failures++;
        } else {
          console.log(`  OK   ${name}: notes[${namespace}]`);
        }
      } catch {
        console.log(`  FAIL ${name}: notes[${namespace}] not found for ${commitHash}`);
        failures++;
      }
    }
  }

  // Clean up temp dirs
  for (const tmpDir of tempDirs) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }

  if (failures) {
    console.log(`\n${failures} failure(s)`);
    process.exit(1);
  } else {
    console.log('\nAll checks passed');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
