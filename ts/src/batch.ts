/**
 * Batch: accumulates writes and removes, commits once on commit().
 */

import git from 'isomorphic-git';
import {
  MODE_BLOB,
  MODE_LINK,
  MODE_TREE,
  FileNotFoundError,
  IsADirectoryError,
  type FsModule,
} from './types.js';
import { normalizePath } from './paths.js';
import { modeFromDisk, walkTo, existsAtPath, type TreeWrite } from './tree.js';

import type { FS } from './fs.js';
import type { GitStore } from './gitstore.js';

/**
 * Accumulates writes and removes, then commits all changes atomically
 * when `commit()` is called.
 */
export class Batch {
  private _fs: FS;
  private _store: GitStore;
  private _fsModule: FsModule;
  private _gitdir: string;
  private _message: string | null;
  private _operation: string | null;
  private _writes = new Map<string, TreeWrite>();
  private _removes = new Set<string>();
  private _closed = false;

  /** The resulting FS snapshot after commit. Null until commit() completes. */
  result: FS | null = null;

  constructor(fs: FS, message?: string | null, operation?: string | null) {
    if (!fs._writable) {
      throw new Error('Cannot batch on a read-only snapshot');
    }
    this._fs = fs;
    this._store = fs._store;
    this._fsModule = fs._store._fsModule;
    this._gitdir = fs._store._gitdir;
    this._message = message ?? null;
    this._operation = operation ?? null;
  }

  private _checkOpen(): void {
    if (this._closed) throw new Error('Batch is closed');
  }

  /**
   * Stage a blob write. Creates the blob immediately in the object store.
   */
  async write(path: string, data: Uint8Array, opts?: { mode?: string }): Promise<void> {
    this._checkOpen();
    const normalized = normalizePath(path);
    this._removes.delete(normalized);
    const blobOid = await git.writeBlob({ fs: this._fsModule, gitdir: this._gitdir, blob: data });
    this._writes.set(normalized, {
      oid: blobOid,
      mode: opts?.mode ?? MODE_BLOB,
    });
  }

  /**
   * Stage a write from a local file. Reads the file and creates the blob.
   */
  async writeFromFile(
    path: string,
    localPath: string,
    opts?: { mode?: string },
  ): Promise<void> {
    this._checkOpen();
    const normalized = normalizePath(path);
    this._removes.delete(normalized);

    const detectedMode = await modeFromDisk(this._fsModule, localPath);
    const mode = opts?.mode ?? detectedMode;
    const data = (await this._fsModule.promises.readFile(localPath)) as Uint8Array;
    const blobOid = await git.writeBlob({ fs: this._fsModule, gitdir: this._gitdir, blob: data });
    this._writes.set(normalized, { oid: blobOid, mode });
  }

  /**
   * Stage a symlink write.
   */
  async writeSymlink(path: string, target: string): Promise<void> {
    this._checkOpen();
    const normalized = normalizePath(path);
    this._removes.delete(normalized);
    const data = new TextEncoder().encode(target);
    const blobOid = await git.writeBlob({ fs: this._fsModule, gitdir: this._gitdir, blob: data });
    this._writes.set(normalized, { oid: blobOid, mode: MODE_LINK });
  }

  /**
   * Stage a file removal.
   */
  async remove(path: string): Promise<void> {
    this._checkOpen();
    const normalized = normalizePath(path);
    const pendingWrite = this._writes.has(normalized);
    const existsInBase = await existsAtPath(
      this._fsModule,
      this._gitdir,
      this._fs._treeOid,
      normalized,
    );

    if (!pendingWrite && !existsInBase) {
      throw new FileNotFoundError(normalized);
    }

    // Don't allow removing directories
    if (existsInBase) {
      const entry = await walkTo(this._fsModule, this._gitdir, this._fs._treeOid, normalized);
      if (entry.mode === MODE_TREE) {
        throw new IsADirectoryError(normalized);
      }
    }

    this._writes.delete(normalized);
    if (existsInBase) {
      this._removes.add(normalized);
    }
  }

  /**
   * Commit all accumulated changes. Returns the new FS snapshot.
   */
  async commit(): Promise<FS> {
    if (this._closed) throw new Error('Batch is already committed');
    this._closed = true;

    if (this._writes.size === 0 && this._removes.size === 0) {
      this.result = this._fs;
      return this._fs;
    }

    this.result = await this._fs._commitChanges(
      this._writes,
      this._removes,
      this._message,
      this._operation,
    );
    return this.result;
  }
}
