/**
 * GitStore: versioned filesystem backed by a bare git repository.
 */

import git from 'isomorphic-git';
import type { FsModule, Signature, MirrorDiff, HttpClient } from './types.js';
import { RefDict } from './refdict.js';

export class GitStore {
  /** @internal */ _fsModule: FsModule;
  /** @internal */ _gitdir: string;
  /** @internal */ _signature: Signature;

  branches: RefDict;
  tags: RefDict;

  constructor(fsModule: FsModule, gitdir: string, author: string, email: string) {
    this._fsModule = fsModule;
    this._gitdir = gitdir;
    this._signature = { name: author, email };
    this.branches = new RefDict(this, 'refs/heads/');
    this.tags = new RefDict(this, 'refs/tags/');
  }

  toString(): string {
    return `GitStore('${this._gitdir}')`;
  }

  /**
   * Open or create a bare git repository.
   *
   * @param path - Path to the bare repository directory.
   * @param opts.fs - Node.js `fs` module (or compatible).
   * @param opts.create - Create the repo if it doesn't exist (default: true).
   * @param opts.branch - Initial branch when creating (default: "main"). Null for no branch.
   * @param opts.author - Default author name (default: "gitstore").
   * @param opts.email - Default author email (default: "gitstore@localhost").
   */
  static async open(
    path: string,
    opts: {
      fs: FsModule;
      create?: boolean;
      branch?: string | null;
      author?: string;
      email?: string;
    },
  ): Promise<GitStore> {
    const fsModule = opts.fs;
    const create = opts.create ?? true;
    const branch = opts.branch !== undefined ? opts.branch : 'main';
    const author = opts.author ?? 'gitstore';
    const email = opts.email ?? 'gitstore@localhost';

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
   * Push all refs to url, creating an exact mirror. (HTTP only)
   */
  async backup(
    url: string,
    opts: { http: HttpClient; dryRun?: boolean; onAuth?: Function } = {} as any,
  ): Promise<MirrorDiff> {
    const { backup } = await import('./mirror.js');
    return backup(this, url, opts);
  }

  /**
   * Fetch all refs from url, overwriting local state. (HTTP only)
   */
  async restore(
    url: string,
    opts: { http: HttpClient; dryRun?: boolean; onAuth?: Function } = {} as any,
  ): Promise<MirrorDiff> {
    const { restore } = await import('./mirror.js');
    return restore(this, url, opts);
  }
}
