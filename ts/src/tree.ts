/**
 * Low-level tree manipulation for gitstore.
 *
 * Provides recursive tree rebuild and path-based read helpers
 * on top of isomorphic-git's readTree/writeTree/writeBlob.
 */

import git from 'isomorphic-git';
import {
  MODE_TREE,
  MODE_BLOB,
  MODE_BLOB_EXEC,
  MODE_LINK,
  typeForMode,
  FileNotFoundError,
  IsADirectoryError,
  NotADirectoryError,
  type FsModule,
  type WalkEntry,
} from './types.js';
import { normalizePath, isRootPath } from './paths.js';

// ---------------------------------------------------------------------------
// Internal type for writes passed to rebuildTree
// ---------------------------------------------------------------------------

export interface TreeWrite {
  /** Raw blob data (will create blob). Mutually exclusive with oid. */
  data?: Uint8Array;
  /** Existing blob OID (skip blob creation). Mutually exclusive with data. */
  oid?: string;
  /** Git mode string (default: '100644'). */
  mode: string;
}

// ---------------------------------------------------------------------------
// Detect executable bit from filesystem
// ---------------------------------------------------------------------------

export async function modeFromDisk(
  fsModule: FsModule,
  localPath: string,
): Promise<string> {
  const stat = await fsModule.promises.stat(localPath);
  if (stat.isDirectory()) throw new IsADirectoryError(localPath);
  // Check executable bit (any of owner/group/other)
  if ((stat.mode & 0o111) !== 0) return MODE_BLOB_EXEC;
  return MODE_BLOB;
}

// ---------------------------------------------------------------------------
// Tree entry lookup helpers
// ---------------------------------------------------------------------------

interface TreeEntryResult {
  oid: string;
  mode: string;
  type: string;
  path: string;
}

/**
 * Walk through tree to the object at the given path.
 * Returns the final tree entry.
 */
export async function walkTo(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path: string,
): Promise<TreeEntryResult> {
  const segments = path.split('/');
  let currentOid = treeOid;

  for (let i = 0; i < segments.length; i++) {
    const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: currentOid });
    const entry = tree.find((e) => e.path === segments[i]);
    if (!entry) throw new FileNotFoundError(path);

    if (i < segments.length - 1) {
      if (entry.mode !== MODE_TREE) {
        throw new NotADirectoryError(segments.slice(0, i + 1).join('/'));
      }
      currentOid = entry.oid;
    } else {
      return entry;
    }
  }
  throw new FileNotFoundError(path);
}

/**
 * Return { oid, mode } of the entry at path, or null if missing.
 */
export async function entryAtPath(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path: string,
): Promise<{ oid: string; mode: string } | null> {
  const segments = path.split('/');
  let currentOid = treeOid;

  for (let i = 0; i < segments.length; i++) {
    let tree;
    try {
      const result = await git.readTree({ fs: fsModule, gitdir, oid: currentOid });
      tree = result.tree;
    } catch {
      return null;
    }
    const entry = tree.find((e) => e.path === segments[i]);
    if (!entry) return null;

    if (i < segments.length - 1) {
      if (entry.mode !== MODE_TREE) return null;
      currentOid = entry.oid;
    } else {
      return { oid: entry.oid, mode: entry.mode };
    }
  }
  return null;
}

/**
 * Read a blob at the given path in the tree.
 */
export async function readBlobAtPath(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path: string,
): Promise<Uint8Array> {
  const normalized = normalizePath(path);
  const entry = await walkTo(fsModule, gitdir, treeOid, normalized);
  if (entry.mode === MODE_TREE) throw new IsADirectoryError(normalized);
  const { blob } = await git.readBlob({ fs: fsModule, gitdir, oid: entry.oid });
  return blob;
}

/**
 * List entry names at the given path (or root if path is null/empty).
 */
export async function listTreeAtPath(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path?: string | null,
): Promise<string[]> {
  const entries = await listEntriesAtPath(fsModule, gitdir, treeOid, path);
  return entries.map((e) => e.name);
}

/**
 * List full entries at the given path (or root if path is null/empty).
 */
export async function listEntriesAtPath(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path?: string | null,
): Promise<WalkEntry[]> {
  let targetOid = treeOid;

  if (path != null && !isRootPath(path)) {
    const normalized = normalizePath(path);
    const entry = await walkTo(fsModule, gitdir, treeOid, normalized);
    if (entry.mode !== MODE_TREE) throw new NotADirectoryError(normalized);
    targetOid = entry.oid;
  }

  const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: targetOid });
  return tree.map((e) => ({ name: e.path, oid: e.oid, mode: e.mode }));
}

/**
 * Walk the tree recursively, yielding (dirpath, dirnames, fileEntries).
 */
export async function* walkTree(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  prefix = '',
): AsyncGenerator<[string, string[], WalkEntry[]]> {
  const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: treeOid });
  const dirs: string[] = [];
  const files: WalkEntry[] = [];
  const dirOids: [string, string][] = [];

  for (const entry of tree) {
    if (entry.mode === MODE_TREE) {
      dirs.push(entry.path);
      dirOids.push([entry.path, entry.oid]);
    } else {
      files.push({ name: entry.path, oid: entry.oid, mode: entry.mode });
    }
  }

  yield [prefix, dirs, files];

  for (const [name, oid] of dirOids) {
    const childPrefix = prefix ? `${prefix}/${name}` : name;
    yield* walkTree(fsModule, gitdir, oid, childPrefix);
  }
}

/**
 * Check if a path exists in the tree.
 */
export async function existsAtPath(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
  path: string,
): Promise<boolean> {
  const normalized = normalizePath(path);
  const entry = await entryAtPath(fsModule, gitdir, treeOid, normalized);
  return entry !== null;
}

// ---------------------------------------------------------------------------
// Count subdirectories (for stat nlink)
// ---------------------------------------------------------------------------

export async function countSubdirs(
  fsModule: FsModule,
  gitdir: string,
  treeOid: string,
): Promise<number> {
  const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: treeOid });
  return tree.filter(e => e.mode === MODE_TREE).length;
}

// ---------------------------------------------------------------------------
// Recursive tree rebuild
// ---------------------------------------------------------------------------

/**
 * Rebuild a tree with writes and removes applied.
 *
 * Only the ancestor chain from changed leaves to root is rebuilt.
 * Sibling subtrees are shared by hash reference.
 */
export async function rebuildTree(
  fsModule: FsModule,
  gitdir: string,
  baseTreeOid: string | null,
  writes: Map<string, TreeWrite>,
  removes: Set<string>,
): Promise<string> {
  // Group changes by first path segment
  const subWrites = new Map<string, Map<string, TreeWrite>>();
  const leafWrites = new Map<string, TreeWrite>();
  const subRemoves = new Map<string, Set<string>>();
  const leafRemoves = new Set<string>();

  for (const [path, write] of writes) {
    const slashIdx = path.indexOf('/');
    if (slashIdx < 0) {
      leafWrites.set(path, write);
    } else {
      const first = path.slice(0, slashIdx);
      const rest = path.slice(slashIdx + 1);
      if (!subWrites.has(first)) subWrites.set(first, new Map());
      subWrites.get(first)!.set(rest, write);
    }
  }

  for (const path of removes) {
    const slashIdx = path.indexOf('/');
    if (slashIdx < 0) {
      leafRemoves.add(path);
    } else {
      const first = path.slice(0, slashIdx);
      const rest = path.slice(slashIdx + 1);
      if (!subRemoves.has(first)) subRemoves.set(first, new Set());
      subRemoves.get(first)!.add(rest);
    }
  }

  // Read existing tree entries
  let entries: Array<{ mode: string; path: string; oid: string; type: string }> = [];
  if (baseTreeOid) {
    const { tree } = await git.readTree({ fs: fsModule, gitdir, oid: baseTreeOid });
    entries = tree.map((e) => ({ ...e }));
  }

  // Build lookup: name → existing entry
  const entryMap = new Map<string, (typeof entries)[0]>();
  for (const e of entries) {
    entryMap.set(e.path, e);
  }

  // Apply leaf writes (may overwrite existing entries)
  for (const [name, write] of leafWrites) {
    let blobOid: string;
    if (write.oid) {
      blobOid = write.oid;
    } else if (write.data) {
      blobOid = await git.writeBlob({ fs: fsModule, gitdir, blob: write.data });
    } else {
      throw new Error(`Write for '${name}' has neither data nor oid`);
    }
    entryMap.set(name, {
      mode: write.mode,
      path: name,
      oid: blobOid,
      type: typeForMode(write.mode),
    });
  }

  // Apply leaf removes
  for (const name of leafRemoves) {
    entryMap.delete(name);
  }

  // Collect existing subtree OIDs
  const existingSubtrees = new Map<string, string>();
  for (const [name, entry] of entryMap) {
    if (entry.mode === MODE_TREE) {
      existingSubtrees.set(name, entry.oid);
    }
  }

  // Recurse into subdirectories
  const allSubdirs = new Set([...subWrites.keys(), ...subRemoves.keys()]);
  for (const subdir of allSubdirs) {
    let existingOid = existingSubtrees.get(subdir) ?? null;

    // If there's a non-tree entry at this name, remove it to make way for a tree
    if (existingOid === null) {
      const existing = entryMap.get(subdir);
      if (existing && existing.mode !== MODE_TREE) {
        entryMap.delete(subdir);
      }
    }

    const newSubtreeOid = await rebuildTree(
      fsModule,
      gitdir,
      existingOid,
      subWrites.get(subdir) ?? new Map(),
      subRemoves.get(subdir) ?? new Set(),
    );

    // Check if subtree is empty (prune empty directories)
    const { tree: subtreeEntries } = await git.readTree({
      fs: fsModule,
      gitdir,
      oid: newSubtreeOid,
    });
    if (subtreeEntries.length === 0) {
      entryMap.delete(subdir);
    } else {
      entryMap.set(subdir, {
        mode: MODE_TREE,
        path: subdir,
        oid: newSubtreeOid,
        type: 'tree',
      });
    }
  }

  // Write new tree from modified entries
  const treeEntries = Array.from(entryMap.values()).map((e) => ({
    mode: e.mode,
    path: e.path,
    oid: e.oid,
    type: typeForMode(e.mode) as 'blob' | 'tree' | 'commit',
  }));

  return await git.writeTree({ fs: fsModule, gitdir, tree: treeEntries });
}
