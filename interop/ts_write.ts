/**
 * Write repos from fixtures.json so Python can read them.
 * Usage: npx tsx interop/ts_write.ts <fixtures.json> <output_dir>
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { GitStore, MODE_BLOB_EXEC } from '../ts/src/index.js';

const enc = new TextEncoder();

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

async function writeScenario(store: GitStore, branch: string, spec: Spec) {
  let snapshot = await store.branches.get(branch);
  const batch = snapshot.batch({ message: 'interop' });

  for (const [filepath, content] of Object.entries(spec.files ?? {})) {
    await batch.write(filepath, enc.encode(content));
  }
  for (const [filepath, target] of Object.entries(spec.symlinks ?? {})) {
    await batch.writeSymlink(filepath, target);
  }
  for (const [filepath, b64] of Object.entries(spec.binary_files ?? {})) {
    await batch.write(filepath, Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
  }
  for (const [filepath, content] of Object.entries(spec.executable_files ?? {})) {
    await batch.write(filepath, enc.encode(content), { mode: MODE_BLOB_EXEC });
  }

  await batch.commit();
}

async function writeHistory(store: GitStore, branch: string, spec: Spec) {
  let snapshot = await store.branches.get(branch);

  for (const step of spec.commits!) {
    const batch = snapshot.batch({ message: step.message });
    for (const [filepath, content] of Object.entries(step.files ?? {})) {
      await batch.write(filepath, enc.encode(content));
    }
    for (const filepath of step.removes ?? []) {
      await batch.remove(filepath);
    }
    snapshot = await batch.commit();
  }
}

async function main() {
  const fixturesPath = process.argv[2];
  const outputDir = process.argv[3];

  const fixtures: Record<string, Spec> = JSON.parse(fs.readFileSync(fixturesPath, 'utf-8'));

  for (const [name, spec] of Object.entries(fixtures)) {
    const repoPath = path.join(outputDir, `ts_${name}.git`);
    const branch = spec.branch ?? 'main';

    const store = await GitStore.open(repoPath, { fs, branch });

    if (spec.commits) {
      await writeHistory(store, branch, spec);
    } else {
      await writeScenario(store, branch, spec);
    }

    if (spec.notes) {
      const snapshot = await store.branches.get(branch);
      const commitHash = snapshot.commitHash;
      for (const [namespace, text] of Object.entries(spec.notes)) {
        await store.notes.namespace(namespace).set(commitHash, text);
      }
    }

    await store.backup(path.join(outputDir, `ts_${name}.bundle`));
    console.log(`  ts_write: ${name} -> ${repoPath}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
