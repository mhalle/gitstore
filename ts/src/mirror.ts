/**
 * Mirror (backup/restore) operations for vost.
 *
 * Uses isomorphic-git's push/fetch for HTTP transport.
 * Each ref is pushed/fetched individually to achieve mirror semantics.
 */

import git from 'isomorphic-git';
import type { MirrorDiff, RefChange, HttpClient } from './types.js';
import type { GitStore } from './gitstore.js';

/**
 * Push all local refs to url, creating an exact mirror.
 * Remote-only refs are deleted.
 *
 * @param store - The GitStore to backup from.
 * @param url   - Remote repository URL (HTTPS or local path).
 * @param opts  - Options: `http` client, `dryRun` to compute diff without pushing,
 *                and optional `onAuth` callback for credentials.
 * @returns A {@link MirrorDiff} describing what changed (or would change).
 */
export async function backup(
  store: GitStore,
  url: string,
  opts: { http: HttpClient; dryRun?: boolean; onAuth?: Function },
): Promise<MirrorDiff> {
  const diff = await diffRefs(store, url, 'push', opts);

  if (!opts.dryRun) {
    // Push all local branches
    const branches = await store.branches.list();
    for (const branch of branches) {
      await git.push({
        fs: store._fsModule,
        gitdir: store._gitdir,
        http: opts.http as any,
        url,
        ref: `refs/heads/${branch}`,
        remoteRef: `refs/heads/${branch}`,
        force: true,
        onAuth: opts.onAuth as any,
      });
    }

    // Push all tags
    const tags = await store.tags.list();
    for (const tag of tags) {
      await git.push({
        fs: store._fsModule,
        gitdir: store._gitdir,
        http: opts.http as any,
        url,
        ref: `refs/tags/${tag}`,
        remoteRef: `refs/tags/${tag}`,
        force: true,
        onAuth: opts.onAuth as any,
      });
    }

    // Delete stale remote refs
    for (const change of diff.delete) {
      try {
        await git.push({
          fs: store._fsModule,
          gitdir: store._gitdir,
          http: opts.http as any,
          url,
          ref: change.ref,
          delete: true,
          onAuth: opts.onAuth as any,
        });
      } catch {
        // Ignore delete failures
      }
    }
  }

  return diff;
}

/**
 * Fetch all remote refs from url, overwriting local state.
 * Local-only refs are deleted.
 *
 * @param store - The GitStore to restore into.
 * @param url   - Remote repository URL (HTTPS or local path).
 * @param opts  - Options: `http` client, `dryRun` to compute diff without fetching,
 *                and optional `onAuth` callback for credentials.
 * @returns A {@link MirrorDiff} describing what changed (or would change).
 */
export async function restore(
  store: GitStore,
  url: string,
  opts: { http: HttpClient; dryRun?: boolean; onAuth?: Function },
): Promise<MirrorDiff> {
  const diff = await diffRefs(store, url, 'pull', opts);

  if (!opts.dryRun) {
    // Fetch all remote refs
    await git.fetch({
      fs: store._fsModule,
      gitdir: store._gitdir,
      http: opts.http as any,
      url,
      tags: true,
      prune: true,
      onAuth: opts.onAuth as any,
    });

    // Update local refs to match remote
    const remoteRefs = await git.listServerRefs({
      http: opts.http as any,
      url,
      onAuth: opts.onAuth as any,
    });

    const remoteRefMap = new Map<string, string>();
    for (const ref of remoteRefs) {
      if (ref.ref !== 'HEAD' && !ref.ref.endsWith('^{}')) {
        remoteRefMap.set(ref.ref, ref.oid);
      }
    }

    // Set local refs to match remote
    for (const [ref, oid] of remoteRefMap) {
      await git.writeRef({
        fs: store._fsModule,
        gitdir: store._gitdir,
        ref,
        value: oid,
        force: true,
      });
    }

    // Delete local refs not on remote
    const localBranches = await store.branches.list();
    for (const branch of localBranches) {
      if (!remoteRefMap.has(`refs/heads/${branch}`)) {
        await git.deleteRef({
          fs: store._fsModule,
          gitdir: store._gitdir,
          ref: `refs/heads/${branch}`,
        });
      }
    }
    const localTags = await store.tags.list();
    for (const tag of localTags) {
      if (!remoteRefMap.has(`refs/tags/${tag}`)) {
        await git.deleteRef({
          fs: store._fsModule,
          gitdir: store._gitdir,
          ref: `refs/tags/${tag}`,
        });
      }
    }
  }

  return diff;
}

/**
 * Compare local and remote refs.
 */
async function diffRefs(
  store: GitStore,
  url: string,
  direction: 'push' | 'pull',
  opts: { http: HttpClient; onAuth?: Function },
): Promise<MirrorDiff> {
  // Get remote refs
  let remoteRefs: Map<string, string>;
  try {
    const refs = await git.listServerRefs({
      http: opts.http as any,
      url,
      onAuth: opts.onAuth as any,
    });
    remoteRefs = new Map<string, string>();
    for (const ref of refs) {
      if (ref.ref !== 'HEAD' && !ref.ref.endsWith('^{}')) {
        remoteRefs.set(ref.ref, ref.oid);
      }
    }
  } catch {
    remoteRefs = new Map();
  }

  // Get local refs
  const localRefs = new Map<string, string>();
  const branches = await store.branches.list();
  for (const branch of branches) {
    const oid = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: `refs/heads/${branch}`,
    });
    localRefs.set(`refs/heads/${branch}`, oid);
  }
  const tags = await store.tags.list();
  for (const tag of tags) {
    const oid = await git.resolveRef({
      fs: store._fsModule,
      gitdir: store._gitdir,
      ref: `refs/tags/${tag}`,
    });
    localRefs.set(`refs/tags/${tag}`, oid);
  }

  const [src, dest] =
    direction === 'push' ? [localRefs, remoteRefs] : [remoteRefs, localRefs];

  const add: RefChange[] = [];
  const update: RefChange[] = [];
  const del: RefChange[] = [];

  for (const [ref, sha] of src) {
    if (!dest.has(ref)) {
      add.push({ ref, newTarget: sha });
    } else if (dest.get(ref) !== sha) {
      update.push({ ref, oldTarget: dest.get(ref), newTarget: sha });
    }
  }
  for (const [ref] of dest) {
    if (!src.has(ref)) {
      del.push({ ref, oldTarget: dest.get(ref) });
    }
  }

  return { add, update, delete: del };
}
