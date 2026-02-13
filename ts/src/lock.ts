/**
 * Advisory repo lock for serializing ref mutations.
 *
 * Uses an atomic lockfile (`gitstore.lock`) for cross-process coordination
 * and an in-process Promise-based mutex (JS is single-threaded, but
 * async operations interleave).
 */

import type { FsModule } from './types.js';

// Per-repo in-process async mutexes (keyed by resolved gitdir path)
const mutexes = new Map<string, Promise<void>>();

/**
 * Execute `fn` while holding an advisory lock on the repository.
 *
 * Serializes both in-process async operations (via Promise chain) and
 * cross-process access (via lockfile).
 */
export async function withRepoLock<T>(
  fsModule: FsModule,
  gitdir: string,
  fn: () => Promise<T>,
): Promise<T> {
  // In-process serialization: chain on the per-repo promise
  const prev = mutexes.get(gitdir) ?? Promise.resolve();
  let releaseMutex: () => void;
  const next = new Promise<void>((resolve) => {
    releaseMutex = resolve;
  });
  mutexes.set(gitdir, next);

  // Wait for previous operation on this repo
  await prev;

  const lockPath = `${gitdir}/gitstore.lock`;

  // Acquire lockfile (atomic create with exclusive flag)
  let acquired = false;
  const maxAttempts = 100;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      // O_CREAT | O_EXCL — fails if file already exists
      const handle = await fsModule.promises.open(lockPath, 'wx');
      await handle.close();
      acquired = true;
      break;
    } catch (err: any) {
      if (err?.code === 'EEXIST') {
        // Lock held by another process — wait and retry
        await sleep(10 + Math.random() * 20);
        continue;
      }
      // Other error (e.g. permission) — release mutex and rethrow
      releaseMutex!();
      throw err;
    }
  }

  if (!acquired) {
    releaseMutex!();
    throw new Error(`Could not acquire lock after ${maxAttempts} attempts: ${lockPath}`);
  }

  try {
    return await fn();
  } finally {
    // Release lockfile
    try {
      await fsModule.promises.unlink(lockPath);
    } catch {
      // Ignore — file may already be cleaned up
    }
    // Release in-process mutex
    releaseMutex!();
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
