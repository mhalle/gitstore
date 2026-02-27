/**
 * Mirror (backup/restore) operations for vost.
 *
 * Uses isomorphic-git's push/fetch for HTTP transport.
 * For local paths and bundles, shells out to the `git` CLI.
 * Each ref is pushed/fetched individually to achieve mirror semantics.
 */

import git from 'isomorphic-git';
import type { MirrorDiff, RefChange, HttpClient } from './types.js';
import type { GitStore } from './gitstore.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isBundlePath(path: string): boolean {
  return path.toLowerCase().endsWith('.bundle');
}

function resolveRefNames(
  names: string[],
  available: Map<string, string>,
): Set<string> {
  const result = new Set<string>();
  for (const name of names) {
    if (name.startsWith('refs/')) {
      result.add(name);
      continue;
    }
    let found = false;
    for (const prefix of ['refs/heads/', 'refs/tags/', 'refs/notes/']) {
      const candidate = `${prefix}${name}`;
      if (available.has(candidate)) {
        result.add(candidate);
        found = true;
        break;
      }
    }
    if (!found) {
      result.add(`refs/heads/${name}`);
    }
  }
  return result;
}

function isLocalPath(url: string): boolean {
  return (
    !url.startsWith('http://') &&
    !url.startsWith('https://') &&
    !url.startsWith('git://') &&
    !url.startsWith('ssh://')
  );
}

// ---------------------------------------------------------------------------
// Git CLI helpers (for local paths and bundles)
// ---------------------------------------------------------------------------

async function getLocalRefsGit(gitdir: string): Promise<Map<string, string>> {
  const { execFileSync } = await import('node:child_process');
  let output: string;
  try {
    output = execFileSync(
      'git',
      ['for-each-ref', '--format=%(objectname) %(refname)'],
      { cwd: gitdir, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );
  } catch {
    return new Map();
  }
  const refs = new Map<string, string>();
  for (const line of output.trim().split('\n')) {
    if (!line) continue;
    const space = line.indexOf(' ');
    if (space < 0) continue;
    const sha = line.slice(0, space);
    const name = line.slice(space + 1);
    if (name === 'HEAD') continue;
    refs.set(name, sha);
  }
  return refs;
}

async function getRemoteRefsGit(
  gitdir: string,
  url: string,
): Promise<Map<string, string>> {
  // For local paths, open directly
  if (isLocalPath(url) || url.startsWith('file://')) {
    const localPath = url.startsWith('file://') ? url.slice(7) : url;
    const { existsSync } = await import('node:fs');
    if (!existsSync(localPath)) return new Map();
    return getLocalRefsGit(localPath);
  }
  // Remote URL
  const { execFileSync } = await import('node:child_process');
  let output: string;
  try {
    output = execFileSync('git', ['ls-remote', url], {
      cwd: gitdir,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch {
    return new Map();
  }
  const refs = new Map<string, string>();
  for (const line of output.trim().split('\n')) {
    if (!line) continue;
    const parts = line.split('\t');
    if (parts.length < 2) continue;
    const [sha, name] = parts;
    if (name === 'HEAD' || name.endsWith('^{}')) continue;
    refs.set(name, sha);
  }
  return refs;
}

// ---------------------------------------------------------------------------
// Bundle helpers
// ---------------------------------------------------------------------------

async function bundleExport(
  gitdir: string,
  path: string,
  refs?: string[],
): Promise<void> {
  const { execFileSync } = await import('node:child_process');
  const args = ['bundle', 'create', path];
  if (refs && refs.length > 0) {
    const localRefs = await getLocalRefsGit(gitdir);
    const resolved = resolveRefNames(refs, localRefs);
    args.push(...resolved);
  } else {
    args.push('--all');
  }
  execFileSync('git', ['-C', gitdir, ...args], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 30000,
  });
}

async function bundleListHeads(
  path: string,
): Promise<Map<string, string>> {
  const { execFileSync } = await import('node:child_process');
  let output: string;
  try {
    output = execFileSync('git', ['bundle', 'list-heads', path], {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch {
    return new Map();
  }
  const refs = new Map<string, string>();
  for (const line of output.trim().split('\n')) {
    if (!line) continue;
    const space = line.indexOf(' ');
    if (space < 0) continue;
    const sha = line.slice(0, space);
    const name = line.slice(space + 1);
    if (name === 'HEAD' || name.endsWith('^{}')) continue;
    refs.set(name, sha);
  }
  return refs;
}

async function bundleImport(
  gitdir: string,
  path: string,
  refs?: string[],
): Promise<void> {
  const { execFileSync } = await import('node:child_process');
  const bundleRefs = await bundleListHeads(path);

  let refsToImport: Map<string, string>;
  if (refs && refs.length > 0) {
    const resolved = resolveRefNames(refs, bundleRefs);
    refsToImport = new Map<string, string>();
    for (const [k, v] of bundleRefs) {
      if (resolved.has(k)) refsToImport.set(k, v);
    }
  } else {
    refsToImport = bundleRefs;
  }

  if (refsToImport.size === 0) return;

  const refspecs = [...refsToImport.keys()].map((r) => `+${r}:${r}`);
  execFileSync('git', ['-C', gitdir, 'fetch', path, ...refspecs], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 30000,
  });
}

// ---------------------------------------------------------------------------
// Transport helpers (git CLI for local paths)
// ---------------------------------------------------------------------------

async function autoCreateBareRepo(url: string): Promise<void> {
  if (!isLocalPath(url)) return;
  const localPath = url.startsWith('file://') ? url.slice(7) : url;
  const { existsSync } = await import('node:fs');
  if (existsSync(localPath)) return;
  const { execFileSync } = await import('node:child_process');
  execFileSync('git', ['init', '--bare', localPath], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

async function mirrorPushGit(
  gitdir: string,
  url: string,
): Promise<void> {
  const { execFileSync } = await import('node:child_process');
  execFileSync('git', ['-C', gitdir, 'push', '--mirror', url], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });
}

async function targetedPushGit(
  gitdir: string,
  url: string,
  refFilter: Set<string>,
): Promise<void> {
  const { execFileSync } = await import('node:child_process');
  const refspecs = [...refFilter].map((r) => `+${r}:${r}`);
  execFileSync('git', ['-C', gitdir, 'push', url, ...refspecs], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });
}

async function additiveFetchGit(
  gitdir: string,
  url: string,
  refs?: string[],
): Promise<void> {
  const remoteRefs = await getRemoteRefsGit(gitdir, url);
  if (remoteRefs.size === 0) return;

  let refsToFetch: Map<string, string>;
  if (refs && refs.length > 0) {
    const resolved = resolveRefNames(refs, remoteRefs);
    refsToFetch = new Map();
    for (const [k, v] of remoteRefs) {
      if (resolved.has(k)) refsToFetch.set(k, v);
    }
  } else {
    refsToFetch = remoteRefs;
  }

  if (refsToFetch.size === 0) return;

  const { execFileSync } = await import('node:child_process');
  const refspecs = [...refsToFetch.keys()].map((r) => `+${r}:${r}`);
  execFileSync('git', ['-C', gitdir, 'fetch', url, ...refspecs, '--force'], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });
  // No deletes — additive
}

// ---------------------------------------------------------------------------
// Diff computation
// ---------------------------------------------------------------------------

function diffRefsMap(
  src: Map<string, string>,
  dest: Map<string, string>,
): MirrorDiff {
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

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

/**
 * Inject credentials into an HTTPS URL if available.
 *
 * Tries `git credential fill` first (works with any configured helper:
 * osxkeychain, wincred, libsecret, `gh auth setup-git`, etc.).  Falls
 * back to `gh auth token` for GitHub hosts.  Non-HTTPS URLs and URLs
 * that already contain credentials are returned unchanged.
 *
 * Requires Node.js — returns the original URL unchanged in browser
 * environments where `child_process` is not available.
 *
 * @param url - The URL to resolve credentials for.
 * @returns The URL with credentials injected, or the original URL.
 */
export async function resolveCredentials(url: string): Promise<string> {
  if (!url.startsWith('https://')) return url;

  const parsed = new URL(url);
  if (parsed.username) return url; // already has credentials

  const hostname = parsed.hostname;

  let execFileSync: typeof import('node:child_process').execFileSync;
  try {
    const cp = await import('node:child_process');
    execFileSync = cp.execFileSync;
  } catch {
    return url; // Not in Node.js
  }

  // Try git credential fill
  try {
    const input = `protocol=https\nhost=${hostname}\n\n`;
    const output = execFileSync('git', ['credential', 'fill'], {
      input,
      timeout: 5000,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    const creds: Record<string, string> = {};
    for (const line of output.trim().split('\n')) {
      const eq = line.indexOf('=');
      if (eq > 0) creds[line.slice(0, eq)] = line.slice(eq + 1);
    }
    if (creds.username && creds.password) {
      parsed.username = creds.username;
      parsed.password = creds.password;
      return parsed.toString();
    }
  } catch {
    // git credential fill failed or not available
  }

  // Fallback: gh auth token (GitHub-specific)
  try {
    const token = execFileSync(
      'gh',
      ['auth', 'token', '--hostname', hostname],
      {
        timeout: 5000,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'ignore'],
      },
    ).trim();
    if (token) {
      parsed.username = 'x-access-token';
      parsed.password = token;
      return parsed.toString();
    }
  } catch {
    // gh not available or not authenticated
  }

  return url;
}

// ---------------------------------------------------------------------------
// backup
// ---------------------------------------------------------------------------

/**
 * Push all local refs to url, creating an exact mirror.
 * Remote-only refs are deleted (unless `refs` filtering is used).
 *
 * Supports HTTP URLs (via isomorphic-git), local bare-repo paths
 * (via `git` CLI), and `.bundle` files.
 *
 * @param store - The GitStore to backup from.
 * @param url   - Remote repository URL, local path, or bundle file path.
 * @param opts  - Options: `http` client (required for HTTP URLs only),
 *                `dryRun` to compute diff without pushing, optional
 *                `onAuth` callback, `refs` to filter which refs to push,
 *                `format` to force bundle format.
 * @returns A {@link MirrorDiff} describing what changed (or would change).
 */
export async function backup(
  store: GitStore,
  url: string,
  opts: {
    http?: HttpClient;
    dryRun?: boolean;
    onAuth?: Function;
    refs?: string[];
    format?: string;
  } = {},
): Promise<MirrorDiff> {
  const useBundle = opts.format === 'bundle' || isBundlePath(url);
  const gitdir = store._gitdir;

  if (useBundle) {
    // Bundle export
    const localRefs = await getLocalRefsGit(gitdir);
    let filtered: Map<string, string>;
    if (opts.refs && opts.refs.length > 0) {
      const resolved = resolveRefNames(opts.refs, localRefs);
      filtered = new Map();
      for (const [k, v] of localRefs) {
        if (resolved.has(k)) filtered.set(k, v);
      }
    } else {
      filtered = localRefs;
    }
    // All refs are "add" for bundle export
    const add: RefChange[] = [];
    for (const [ref, sha] of filtered) {
      add.push({ ref, newTarget: sha });
    }
    const diff: MirrorDiff = { add, update: [], delete: [] };

    if (!opts.dryRun) {
      await bundleExport(gitdir, url, opts.refs);
    }
    return diff;
  }

  // Non-bundle: local path or HTTP URL
  const useGit = isLocalPath(url) || url.startsWith('file://');

  if (useGit) {
    await autoCreateBareRepo(url);
    const localRefs = await getLocalRefsGit(gitdir);
    const remoteRefs = await getRemoteRefsGit(gitdir, url);

    if (opts.refs && opts.refs.length > 0) {
      const refSet = resolveRefNames(opts.refs, localRefs);
      const diff = diffRefsMap(localRefs, remoteRefs);
      diff.add = diff.add.filter((r) => refSet.has(r.ref));
      diff.update = diff.update.filter((r) => refSet.has(r.ref));
      diff.delete = []; // no deletes with --ref
      if (!opts.dryRun && (diff.add.length || diff.update.length)) {
        await targetedPushGit(gitdir, url, refSet);
      }
      return diff;
    }

    const diff = diffRefsMap(localRefs, remoteRefs);
    if (
      !opts.dryRun &&
      (diff.add.length || diff.update.length || diff.delete.length)
    ) {
      await mirrorPushGit(gitdir, url);
    }
    return diff;
  }

  // HTTP URL — use existing isomorphic-git path
  if (!opts.http) {
    throw new Error('http client required for HTTP URLs');
  }
  const diff = await diffRefs(store, url, 'push', opts as any);

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

// ---------------------------------------------------------------------------
// restore
// ---------------------------------------------------------------------------

/**
 * Fetch refs from url additively into the local store.
 * Local-only refs are preserved (not deleted).
 *
 * Supports HTTP URLs (via isomorphic-git), local bare-repo paths
 * (via `git` CLI), and `.bundle` files.
 *
 * @param store - The GitStore to restore into.
 * @param url   - Remote repository URL, local path, or bundle file path.
 * @param opts  - Options: `http` client (required for HTTP URLs only),
 *                `dryRun` to compute diff without fetching, optional
 *                `onAuth` callback, `refs` to filter which refs to pull,
 *                `format` to force bundle format.
 * @returns A {@link MirrorDiff} describing what changed (or would change).
 */
export async function restore(
  store: GitStore,
  url: string,
  opts: {
    http?: HttpClient;
    dryRun?: boolean;
    onAuth?: Function;
    refs?: string[];
    format?: string;
  } = {},
): Promise<MirrorDiff> {
  const useBundle = opts.format === 'bundle' || isBundlePath(url);
  const gitdir = store._gitdir;

  if (useBundle) {
    // Bundle import
    const bundleRefs = await bundleListHeads(url);
    let filtered: Map<string, string>;
    if (opts.refs && opts.refs.length > 0) {
      const resolved = resolveRefNames(opts.refs, bundleRefs);
      filtered = new Map();
      for (const [k, v] of bundleRefs) {
        if (resolved.has(k)) filtered.set(k, v);
      }
    } else {
      filtered = bundleRefs;
    }
    const localRefs = await getLocalRefsGit(gitdir);
    const diff = diffRefsMap(filtered, localRefs);
    diff.delete = []; // additive: no deletes

    if (!opts.dryRun) {
      await bundleImport(gitdir, url, opts.refs);
    }
    return diff;
  }

  // Non-bundle: local path or HTTP URL
  const useGit = isLocalPath(url) || url.startsWith('file://');

  if (useGit) {
    const localRefs = await getLocalRefsGit(gitdir);
    const remoteRefs = await getRemoteRefsGit(gitdir, url);
    const diff = diffRefsMap(remoteRefs, localRefs);

    if (opts.refs && opts.refs.length > 0) {
      const refSet = resolveRefNames(opts.refs, remoteRefs);
      diff.add = diff.add.filter((r) => refSet.has(r.ref));
      diff.update = diff.update.filter((r) => refSet.has(r.ref));
    }
    diff.delete = []; // additive: never delete

    if (!opts.dryRun && (diff.add.length || diff.update.length)) {
      await additiveFetchGit(gitdir, url, opts.refs);
    }
    return diff;
  }

  // HTTP URL — use existing isomorphic-git path, but make additive
  if (!opts.http) {
    throw new Error('http client required for HTTP URLs');
  }
  const diff = await diffRefs(store, url, 'pull', opts as any);

  if (opts.refs && opts.refs.length > 0) {
    // Build available refs set from the remote
    const remoteRefMap = new Map<string, string>();
    for (const rc of [...diff.add, ...diff.update]) {
      if (rc.newTarget) remoteRefMap.set(rc.ref, rc.newTarget);
    }
    const refSet = resolveRefNames(opts.refs, remoteRefMap);
    diff.add = diff.add.filter((r) => refSet.has(r.ref));
    diff.update = diff.update.filter((r) => refSet.has(r.ref));
  }
  diff.delete = []; // additive: never delete

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

    // Update local refs to match remote (only set, don't delete)
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

    let refsToSet: Map<string, string>;
    if (opts.refs && opts.refs.length > 0) {
      const refSet = resolveRefNames(opts.refs, remoteRefMap);
      refsToSet = new Map();
      for (const [k, v] of remoteRefMap) {
        if (refSet.has(k)) refsToSet.set(k, v);
      }
    } else {
      refsToSet = remoteRefMap;
    }

    // Set local refs (NO deletes — additive)
    for (const [ref, oid] of refsToSet) {
      await git.writeRef({
        fs: store._fsModule,
        gitdir: store._gitdir,
        ref,
        value: oid,
        force: true,
      });
    }
  }

  return diff;
}

// ---------------------------------------------------------------------------
// diffRefs (isomorphic-git HTTP path)
// ---------------------------------------------------------------------------

/**
 * Compare local and remote refs via isomorphic-git (HTTP transport).
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

  return diffRefsMap(src, dest);
}
