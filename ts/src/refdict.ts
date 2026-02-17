/**
 * RefDict: Map-like access to git branches or tags.
 */

import git from 'isomorphic-git';
import { PermissionError, type FsModule, type ReflogEntry } from './types.js';
import { validateRefName } from './paths.js';
import { withRepoLock } from './lock.js';
import { readReflog, writeReflogEntry, ZERO_SHA } from './reflog.js';
import { FS } from './fs.js';
import type { GitStore } from './gitstore.js';

export class RefDict {
  private _store: GitStore;
  private _prefix: string; // "refs/heads/" or "refs/tags/"

  constructor(store: GitStore, prefix: string) {
    this._store = store;
    this._prefix = prefix;
  }

  private get _isTags(): boolean {
    return this._prefix === 'refs/tags/';
  }

  private get _fsModule(): FsModule {
    return this._store._fsModule;
  }

  private get _gitdir(): string {
    return this._store._gitdir;
  }

  private _refName(name: string): string {
    return `${this._prefix}${name}`;
  }

  toString(): string {
    const kind = this._isTags ? 'tags' : 'branches';
    return `RefDict('${kind}')`;
  }

  /**
   * Get a branch or tag as an FS snapshot.
   */
  async get(name: string): Promise<FS> {
    const refName = this._refName(name);
    let oid: string;
    try {
      oid = await git.resolveRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName });
    } catch {
      throw new Error(`Key not found: ${name}`);
    }

    if (this._isTags) {
      // Tags may point to annotated tag objects — peel to commit
      const { commit } = await git.readCommit({
        fs: this._fsModule,
        gitdir: this._gitdir,
        oid,
      });
      // oid is already the commit oid after resolveRef for lightweight tags.
      // For annotated tags, readCommit may fail — try reading as tag first.
      return FS._fromCommit(this._store, oid, null);
    }

    return FS._fromCommit(this._store, oid, name);
  }

  /**
   * Set/create a branch from an FS snapshot.
   */
  async set(name: string, fs: FS): Promise<void> {
    validateRefName(name);
    if (!(fs instanceof FS)) throw new TypeError(`Expected FS, got ${typeof fs}`);

    const selfPath = this._fsModule.realpathSync(this._gitdir);
    const fsPath = this._fsModule.realpathSync(fs._gitdir);
    if (selfPath !== fsPath) {
      throw new Error('FS belongs to a different repository');
    }

    const refName = this._refName(name);
    const sig = this._store._signature;
    const committerStr = `${sig.name} <${sig.email}>`;

    await withRepoLock(this._fsModule, this._gitdir, async () => {
      let exists = false;
      try {
        await git.resolveRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName });
        exists = true;
      } catch { /* not found */ }

      if (exists && this._isTags) {
        throw new Error(`Tag '${name}' already exists`);
      }

      await git.writeRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
        value: fs._commitOid,
        force: true,
      });

      // Write reflog
      const msg = exists
        ? `branch: set to ${(await fs.getMessage()).split('\n')[0]}`
        : `branch: Created from ${(await fs.getMessage()).split('\n')[0]}`;

      const oldSha = exists
        ? await git.resolveRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName }).catch(() => ZERO_SHA)
        : ZERO_SHA;

      await writeReflogEntry(
        this._fsModule,
        this._gitdir,
        refName,
        typeof oldSha === 'string' ? oldSha : ZERO_SHA,
        fs._commitOid,
        committerStr,
        msg,
      );
    });
  }

  /**
   * Set branch and return a writable FS bound to it. Convenience for set + get.
   */
  async setAndGet(name: string, fs: FS): Promise<FS> {
    await this.set(name, fs);
    return this.get(name);
  }

  /**
   * Delete a branch or tag.
   */
  async delete(name: string): Promise<void> {
    const refName = this._refName(name);
    await withRepoLock(this._fsModule, this._gitdir, async () => {
      try {
        await git.resolveRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName });
      } catch {
        throw new Error(`Key not found: ${name}`);
      }
      await git.deleteRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName });
    });
  }

  /**
   * Check if a branch/tag exists.
   */
  async has(name: string): Promise<boolean> {
    const refName = this._refName(name);
    try {
      await git.resolveRef({ fs: this._fsModule, gitdir: this._gitdir, ref: refName });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * List all branch/tag names.
   */
  async list(): Promise<string[]> {
    if (this._isTags) {
      return git.listTags({ fs: this._fsModule, gitdir: this._gitdir });
    }
    return git.listBranches({ fs: this._fsModule, gitdir: this._gitdir });
  }

  /**
   * Async iteration over branch/tag names.
   */
  async *[Symbol.asyncIterator](): AsyncGenerator<string> {
    const names = await this.list();
    for (const name of names) {
      yield name;
    }
  }

  /**
   * Get/set the default branch (HEAD). Only valid for branches.
   */
  async getDefault(): Promise<string | null> {
    if (this._isTags) throw new Error('Tags do not have a default');
    const branch = await git.currentBranch({
      fs: this._fsModule,
      gitdir: this._gitdir,
      fullname: false,
    });
    return branch ?? null;
  }

  async setDefault(name: string): Promise<void> {
    if (this._isTags) throw new Error('Tags do not have a default');
    if (!(await this.has(name))) throw new Error(`Branch not found: '${name}'`);
    await git.writeRef({
      fs: this._fsModule,
      gitdir: this._gitdir,
      ref: 'HEAD',
      value: `refs/heads/${name}`,
      symbolic: true,
      force: true,
    });
  }

  /**
   * Read reflog entries for a branch.
   */
  async reflog(name: string): Promise<ReflogEntry[]> {
    if (this._isTags) throw new Error('Tags do not have reflog');
    if (!(await this.has(name))) throw new Error(`Key not found: ${name}`);
    return readReflog(this._fsModule, this._gitdir, name);
  }
}
