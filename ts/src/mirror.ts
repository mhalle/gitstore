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

async function getLocalRefsNative(
  store: GitStore,
): Promise<Map<string, string>> {
  const fs = store._fsModule;
  const gitdir = store._gitdir;
  const refs = new Map<string, string>();

  // Branches
  const branches = await git.listBranches({ fs, gitdir });
  for (const branch of branches) {
    const oid = await git.resolveRef({ fs, gitdir, ref: `refs/heads/${branch}` });
    refs.set(`refs/heads/${branch}`, oid);
  }

  // Tags
  const tags = await git.listTags({ fs, gitdir });
  for (const tag of tags) {
    const oid = await git.resolveRef({ fs, gitdir, ref: `refs/tags/${tag}` });
    refs.set(`refs/tags/${tag}`, oid);
  }

  // Notes — no isomorphic-git API for listing note namespaces; read directory
  const notesDir = `${gitdir}/refs/notes`;
  try {
    const entries = await fs.promises.readdir(notesDir);
    for (const name of entries) {
      const ref = `refs/notes/${name}`;
      try {
        const oid = await git.resolveRef({ fs, gitdir, ref });
        refs.set(ref, oid);
      } catch {
        // skip unresolvable entries
      }
    }
  } catch {
    // refs/notes/ doesn't exist — no notes
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
// Object graph walker (for native bundle export)
// ---------------------------------------------------------------------------

async function collectReachableOids(
  fsModule: any,
  gitdir: string,
  startOids: string[],
): Promise<Set<string>> {
  const visited = new Set<string>();
  const queue = [...startOids];

  while (queue.length > 0) {
    const oid = queue.pop()!;
    if (visited.has(oid)) continue;
    visited.add(oid);

    const obj = await git.readObject({ fs: fsModule, gitdir, oid, format: 'parsed' });

    switch (obj.type) {
      case 'commit': {
        const commit = obj.object as any;
        queue.push(commit.tree);
        if (commit.parent) {
          for (const p of commit.parent) queue.push(p);
        }
        break;
      }
      case 'tree': {
        const entries = obj.object as any[];
        for (const entry of entries) {
          if (visited.has(entry.oid)) continue;
          if (entry.type === 'blob') {
            // Blobs are leaves — add to visited but don't read
            visited.add(entry.oid);
          } else if (entry.type === 'tree') {
            queue.push(entry.oid);
          }
          // skip 'commit' entries (submodules)
        }
        break;
      }
      case 'tag': {
        const tag = obj.object as any;
        queue.push(tag.object);
        break;
      }
      // blob: leaf — no children
    }
  }

  return visited;
}

// ---------------------------------------------------------------------------
// Bundle v2 header parser
// ---------------------------------------------------------------------------

interface BundleHeader {
  refs: Map<string, string>;
  prerequisites: string[];
  packOffset: number;
}

function parseBundleHeader(data: Uint8Array): BundleHeader {
  // Find the blank line (\n\n) that separates header from packfile
  let headerEnd = -1;
  for (let i = 0; i < data.length - 1; i++) {
    if (data[i] === 0x0a && data[i + 1] === 0x0a) {
      headerEnd = i;
      break;
    }
  }
  if (headerEnd < 0) {
    throw new Error('Invalid bundle: no header/packfile separator found');
  }

  const headerText = new TextDecoder().decode(data.subarray(0, headerEnd));
  const lines = headerText.split('\n');

  if (lines[0] !== '# v2 git bundle') {
    throw new Error(`Invalid bundle signature: ${lines[0]}`);
  }

  const refs = new Map<string, string>();
  const prerequisites: string[] = [];

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;
    if (line.startsWith('-')) {
      prerequisites.push(line.slice(1));
      continue;
    }
    const space = line.indexOf(' ');
    if (space < 0) continue;
    const sha = line.slice(0, space);
    const refName = line.slice(space + 1);
    refs.set(refName, sha);
  }

  return { refs, prerequisites, packOffset: headerEnd + 2 };
}

// ---------------------------------------------------------------------------
// Bundle helpers (native — no git CLI)
// ---------------------------------------------------------------------------

export async function bundleExport(
  store: GitStore,
  destPath: string,
  refs?: string[],
): Promise<void> {
  const fsModule = store._fsModule;
  const gitdir = store._gitdir;

  // Get all local refs
  const localRefs = await getLocalRefsNative(store);

  // Filter if requested
  let filtered: Map<string, string>;
  if (refs && refs.length > 0) {
    const resolved = resolveRefNames(refs, localRefs);
    filtered = new Map();
    for (const [k, v] of localRefs) {
      if (resolved.has(k)) filtered.set(k, v);
    }
  } else {
    filtered = localRefs;
  }

  if (filtered.size === 0) {
    throw new Error('Nothing to bundle: no matching refs');
  }

  // Collect all reachable OIDs
  const startOids = [...new Set(filtered.values())];
  const allOids = await collectReachableOids(fsModule, gitdir, startOids);

  // Create packfile
  const { packfile } = await git.packObjects({
    fs: fsModule as any,
    gitdir,
    oids: [...allOids],
  });

  if (!packfile) {
    throw new Error('packObjects returned no data');
  }

  // Build bundle v2 header
  let header = '# v2 git bundle\n';
  for (const [refName, sha] of filtered) {
    header += `${sha} ${refName}\n`;
  }
  header += '\n';

  // Concatenate header + packfile
  const headerBytes = new TextEncoder().encode(header);
  const bundle = new Uint8Array(headerBytes.length + packfile.length);
  bundle.set(headerBytes, 0);
  bundle.set(packfile, headerBytes.length);

  await fsModule.promises.writeFile(destPath, bundle);
}

async function bundleListHeads(
  store: GitStore,
  bundlePath: string,
): Promise<Map<string, string>> {
  const raw = await store._fsModule.promises.readFile(bundlePath);
  const data = raw instanceof Uint8Array ? raw : new TextEncoder().encode(raw);
  const { refs } = parseBundleHeader(data);
  return refs;
}

export async function bundleImport(
  store: GitStore,
  bundlePath: string,
  refs?: string[],
): Promise<void> {
  const fsModule = store._fsModule;
  const gitdir = store._gitdir;

  // Read bundle file
  const raw = await fsModule.promises.readFile(bundlePath);
  const data = raw instanceof Uint8Array ? raw : new TextEncoder().encode(raw);
  const { refs: bundleRefs, packOffset } = parseBundleHeader(data);

  // Extract packfile bytes
  const packData = data.subarray(packOffset);

  // Ensure objects/pack directory exists
  const packDir = `${gitdir}/objects/pack`;
  try {
    await fsModule.promises.mkdir(packDir, { recursive: true });
  } catch {
    // already exists
  }

  // Write packfile — use checksum from last 20 bytes for git-conventional naming
  const checksum = Array.from(packData.subarray(-20))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  const packRelPath = `objects/pack/pack-${checksum}.pack`;
  await fsModule.promises.writeFile(`${gitdir}/${packRelPath}`, packData);

  // Index the packfile (creates .idx alongside .pack)
  await git.indexPack({
    fs: fsModule as any,
    dir: gitdir,
    gitdir,
    filepath: packRelPath,
  });

  // Determine which refs to set
  let refsToSet: Map<string, string>;
  if (refs && refs.length > 0) {
    const resolved = resolveRefNames(refs, bundleRefs);
    refsToSet = new Map();
    for (const [k, v] of bundleRefs) {
      if (resolved.has(k)) refsToSet.set(k, v);
    }
  } else {
    refsToSet = bundleRefs;
  }

  // Set each ref
  for (const [ref, oid] of refsToSet) {
    await git.writeRef({
      fs: fsModule as any,
      gitdir,
      ref,
      value: oid,
      force: true,
    });
  }
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
    const localRefs = await getLocalRefsNative(store);
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
      await bundleExport(store, url, opts.refs);
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
    const bundleRefs = await bundleListHeads(store, url);
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
    const localRefs = await getLocalRefsNative(store);
    const diff = diffRefsMap(filtered, localRefs);
    diff.delete = []; // additive: no deletes

    if (!opts.dryRun) {
      await bundleImport(store, url, opts.refs);
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
