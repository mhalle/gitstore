/**
 * GitStore: versioned filesystem backed by a bare git repository.
 */

import * as nodeFs from 'node:fs';
import git from 'isomorphic-git';
import type { FsModule, Signature, MirrorDiff, HttpClient } from './types.js';
import { RefDict } from './refdict.js';
import { NoteDict } from './notes.js';

/**
 * A versioned filesystem backed by a bare git repository.
 *
 * Open or create a store with `GitStore.open()`. Access snapshots via
 * `branches`, `tags`, and `notes`.
 */
export class GitStore {
  /** @internal */ _fsModule: FsModule;
  /** @internal */ _gitdir: string;
  /** @internal */ _signature: Signature;

  /** Dict-like access to branches. */
  branches: RefDict;
  /** Dict-like access to tags. */
  tags: RefDict;
  /** Git notes namespaces. */
  notes: NoteDict;

  constructor(fsModule: FsModule, gitdir: string, author: string, email: string) {
    this._fsModule = fsModule;
    this._gitdir = gitdir;
    this._signature = { name: author, email };
    this.branches = new RefDict(this, 'refs/heads/');
    this.tags = new RefDict(this, 'refs/tags/');
    this.notes = new NoteDict(this);
  }

  toString(): string {
    return `GitStore('${this._gitdir}')`;
  }

  /**
   * Open or create a bare git repository.
   *
   * @param path - Path to the bare repository directory.
   * @param opts.fs - Filesystem module (default: Node.js `node:fs`). Override for custom implementations.
   * @param opts.create - Create the repo if it doesn't exist (default: true).
   * @param opts.branch - Initial branch when creating (default: "main"). Null for no branch.
   * @param opts.author - Default author name (default: "vost").
   * @param opts.email - Default author email (default: "vost@localhost").
   */
  static async open(
    path: string,
    opts: {
      fs?: FsModule;
      create?: boolean;
      branch?: string | null;
      author?: string;
      email?: string;
    } = {},
  ): Promise<GitStore> {
    const fsModule = opts.fs ?? nodeFs as unknown as FsModule;
    const create = opts.create ?? true;
    const branch = opts.branch !== undefined ? opts.branch : 'main';
    const author = opts.author ?? 'vost';
    const email = opts.email ?? 'vost@localhost';

    // Check if repo exists
    let exists = false;
    try {
      await fsModule.promises.stat(`${path}/HEAD`);
      exists = true;
    } catch { /* not found */ }

    if (exists) {
      return new GitStore(fsModule, path, author, email);
    }

    if (!create) {
      throw new Error(`Repository not found: ${path}`);
    }

    // Create bare repo
    await git.init({ fs: fsModule, gitdir: path, bare: true });

    const store = new GitStore(fsModule, path, author, email);

    if (branch !== null) {
      // Create initial empty commit on the branch
      const emptyTreeOid = await git.writeTree({ fs: fsModule, gitdir: path, tree: [] });
      const now = Math.floor(Date.now() / 1000);
      const commitOid = await git.writeCommit({
        fs: fsModule,
        gitdir: path,
        commit: {
          message: `Initialize ${branch}\n`,
          tree: emptyTreeOid,
          parent: [],
          author: { name: author, email, timestamp: now, timezoneOffset: 0 },
          committer: { name: author, email, timestamp: now, timezoneOffset: 0 },
        },
      });

      // Create the branch ref
      await git.writeRef({
        fs: fsModule,
        gitdir: path,
        ref: `refs/heads/${branch}`,
        value: commitOid,
      });

      // Set HEAD to point at the branch
      await git.writeRef({
        fs: fsModule,
        gitdir: path,
        ref: 'HEAD',
        value: `refs/heads/${branch}`,
        symbolic: true,
        force: true,
      });
    }

    return store;
  }

  /**
   * Push all refs to url, creating an exact mirror.
   *
   * Remote-only refs are deleted (unless `refs` filtering is used).
   * Supports HTTP URLs, local bare-repo paths, and `.bundle` files.
   *
   * @param url - Remote repository URL, local path, or bundle file path.
   * @param opts.http - HTTP client (required for HTTP URLs only).
   * @param opts.dryRun - Compute diff without pushing.
   * @param opts.onAuth - Optional authentication callback.
   * @param opts.refs - Only backup these refs (short names resolved automatically).
   * @param opts.format - Force format: `'bundle'` for git bundle output.
   * @returns A MirrorDiff describing what changed (or would change).
   */
  async backup(
    url: string,
    opts: {
      http?: HttpClient;
      dryRun?: boolean;
      onAuth?: Function;
      refs?: string[];
      format?: string;
    } = {},
  ): Promise<MirrorDiff> {
    const { backup } = await import('./mirror.js');
    return backup(this, url, opts);
  }

  /**
   * Fetch refs from url additively into the local store.
   *
   * Local-only refs are preserved (not deleted).  All branches, tags,
   * and notes from the source are merged in, but HEAD (the current
   * branch pointer) is not changed — use
   * `store.branches.setCurrent("name")` afterwards if needed.
   *
   * Supports HTTP URLs, local bare-repo paths, and `.bundle` files.
   *
   * @param url - Remote repository URL, local path, or bundle file path.
   * @param opts.http - HTTP client (required for HTTP URLs only).
   * @param opts.dryRun - Compute diff without fetching.
   * @param opts.onAuth - Optional authentication callback.
   * @param opts.refs - Only restore these refs (short names resolved automatically).
   * @param opts.format - Force format: `'bundle'` for git bundle input.
   * @returns A MirrorDiff describing what changed (or would change).
   */
  async restore(
    url: string,
    opts: {
      http?: HttpClient;
      dryRun?: boolean;
      onAuth?: Function;
      refs?: string[];
      format?: string;
    } = {},
  ): Promise<MirrorDiff> {
    const { restore } = await import('./mirror.js');
    return restore(this, url, opts);
  }

  /**
   * Export refs to a bundle file.
   *
   * @param path - Destination `.bundle` file path.
   * @param opts.refs - Only export these refs (short names resolved automatically).
   */
  async bundleExport(
    path: string,
    opts: { refs?: string[] } = {},
  ): Promise<void> {
    const { bundleExport } = await import('./mirror.js');
    return bundleExport(this, path, opts.refs);
  }

  /**
   * Import refs from a bundle file (additive — no deletes).
   *
   * @param path - Source `.bundle` file path.
   * @param opts.refs - Only import these refs (short names resolved automatically).
   */
  async bundleImport(
    path: string,
    opts: { refs?: string[] } = {},
  ): Promise<void> {
    const { bundleImport } = await import('./mirror.js');
    return bundleImport(this, path, opts.refs);
  }
}
