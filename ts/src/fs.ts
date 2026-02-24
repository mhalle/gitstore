/**
 * FS: immutable snapshot of a committed tree state.
 *
 * Read-only when writable is false (tag/detached snapshot).
 * Writable when writable is true — writes auto-commit and return a new FS.
 */

import git from 'isomorphic-git';
import {
  MODE_TREE,
  MODE_BLOB,
  MODE_LINK,
  modeToInt,
  FileNotFoundError,
  IsADirectoryError,
  NotADirectoryError,
  PermissionError,
  StaleSnapshotError,
  fileTypeFromMode,
  fileModeFromType,
  fileEntryFromMode,
  emptyChangeReport,
  formatCommitMessage,
  finalizeChanges,
  type FsModule,
  type FileType,
  type WalkEntry,
  type WriteEntry,
  type ChangeReport,
  type CommitInfo,
  type StatResult,
} from './types.js';
import { normalizePath, isRootPath } from './paths.js';
import {
  entryAtPath,
  walkTo,
  readBlobAtPath,
  listTreeAtPath,
  listEntriesAtPath,
  walkTree,
  existsAtPath,
  rebuildTree,
  countSubdirs,
  type TreeWrite,
} from './tree.js';
import { globMatch } from './glob.js';
import { withRepoLock } from './lock.js';
import { readReflog, writeReflogEntry, ZERO_SHA } from './reflog.js';
import { Batch } from './batch.js';

import type { GitStore } from './gitstore.js';

export class FS {
  /** @internal */
  _store: GitStore;
  /** @internal */
  _commitOid: string;
  /** @internal */
  _refName: string | null;
  /** @internal */
  _writable: boolean;
  /** @internal */
  _treeOid: string;
  /** @internal */
  _changes: ChangeReport | null = null;
  /** @internal */
  _commitTime: number | null = null;

  /** @internal */
  get _fsModule(): FsModule {
    return this._store._fsModule;
  }

  /** @internal */
  get _gitdir(): string {
    return this._store._gitdir;
  }

  constructor(store: GitStore, commitOid: string, treeOid: string, refName: string | null, writable?: boolean) {
    this._store = store;
    this._commitOid = commitOid;
    this._refName = refName;
    this._writable = writable ?? (refName !== null);
    this._treeOid = treeOid;
  }

  /**
   * @internal Create an FS from a commit OID (reads the commit to get tree OID).
   */
  static async _fromCommit(
    store: GitStore,
    commitOid: string,
    refName: string | null,
    writable?: boolean,
  ): Promise<FS> {
    const { commit } = await git.readCommit({
      fs: store._fsModule,
      gitdir: store._gitdir,
      oid: commitOid,
    });
    return new FS(store, commitOid, commit.tree, refName, writable);
  }

  toString(): string {
    const short = this._commitOid.slice(0, 7);
    const parts: string[] = [];
    if (this._refName) parts.push(`refName='${this._refName}'`);
    parts.push(`commit=${short}`);
    if (!this._writable) parts.push('readonly');
    return `FS(${parts.join(', ')})`;
  }

  /** @internal */
  private _readonlyError(verb: string): PermissionError {
    if (this._refName) {
      return new PermissionError(`Cannot ${verb} read-only snapshot (ref '${this._refName}')`);
    }
    return new PermissionError(`Cannot ${verb} read-only snapshot`);
  }

  // ---------------------------------------------------------------------------
  // Properties
  // ---------------------------------------------------------------------------

  get commitHash(): string {
    return this._commitOid;
  }

  get refName(): string | null {
    return this._refName;
  }

  get writable(): boolean {
    return this._writable;
  }

  async getCommitInfo(): Promise<CommitInfo> {
    const { commit } = await git.readCommit({
      fs: this._fsModule,
      gitdir: this._gitdir,
      oid: this._commitOid,
    });
    const offsetMs = commit.author.timezoneOffset * 60 * 1000;
    return {
      message: commit.message.replace(/\n$/, ''),
      time: new Date(commit.author.timestamp * 1000 - offsetMs),
      authorName: commit.author.name,
      authorEmail: commit.author.email,
    };
  }

  async getMessage(): Promise<string> {
    return (await this.getCommitInfo()).message;
  }

  async getTime(): Promise<Date> {
    return (await this.getCommitInfo()).time;
  }

  async getAuthorName(): Promise<string> {
    return (await this.getCommitInfo()).authorName;
  }

  async getAuthorEmail(): Promise<string> {
    return (await this.getCommitInfo()).authorEmail;
  }

  get changes(): ChangeReport | null {
    return this._changes;
  }

  get treeHash(): string {
    return this._treeOid;
  }

  /** @internal */
  async _getCommitTime(): Promise<number> {
    if (this._commitTime !== null) return this._commitTime;
    const { commit } = await git.readCommit({
      fs: this._fsModule,
      gitdir: this._gitdir,
      oid: this._commitOid,
    });
    this._commitTime = commit.committer.timestamp;
    return this._commitTime;
  }

  // ---------------------------------------------------------------------------
  // Read operations
  // ---------------------------------------------------------------------------

  async read(path: string, opts?: { offset?: number; size?: number }): Promise<Uint8Array> {
    const blob = await readBlobAtPath(this._fsModule, this._gitdir, this._treeOid, path);
    if (opts && (opts.offset !== undefined || opts.size !== undefined)) {
      const offset = opts.offset ?? 0;
      const end = opts.size !== undefined ? offset + opts.size : blob.length;
      return blob.subarray(offset, end);
    }
    return blob;
  }

  async readText(path: string, encoding: string = 'utf-8'): Promise<string> {
    const data = await this.read(path);
    return new TextDecoder(encoding).decode(data);
  }

  async ls(path?: string | null): Promise<string[]> {
    return listTreeAtPath(this._fsModule, this._gitdir, this._treeOid, path);
  }

  async *walk(
    path?: string | null,
  ): AsyncGenerator<[string, string[], WalkEntry[]]> {
    if (path == null || isRootPath(path)) {
      yield* walkTree(this._fsModule, this._gitdir, this._treeOid);
    } else {
      const normalized = normalizePath(path);
      const entry = await walkTo(this._fsModule, this._gitdir, this._treeOid, normalized);
      if (entry.mode !== MODE_TREE) throw new NotADirectoryError(normalized);
      yield* walkTree(this._fsModule, this._gitdir, entry.oid, normalized);
    }
  }

  async exists(path: string): Promise<boolean> {
    return existsAtPath(this._fsModule, this._gitdir, this._treeOid, path);
  }

  async isDir(path: string): Promise<boolean> {
    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) return false;
    return entry.mode === MODE_TREE;
  }

  async fileType(path: string): Promise<FileType> {
    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) throw new FileNotFoundError(normalized);
    return fileTypeFromMode(entry.mode);
  }

  async size(path: string): Promise<number> {
    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) throw new FileNotFoundError(normalized);
    const { blob } = await git.readBlob({ fs: this._fsModule, gitdir: this._gitdir, oid: entry.oid });
    return blob.length;
  }

  async objectHash(path: string): Promise<string> {
    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) throw new FileNotFoundError(normalized);
    return entry.oid;
  }

  async readlink(path: string): Promise<string> {
    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) throw new FileNotFoundError(normalized);
    if (entry.mode !== MODE_LINK) throw new Error(`Not a symlink: ${normalized}`);
    const { blob } = await git.readBlob({ fs: this._fsModule, gitdir: this._gitdir, oid: entry.oid });
    return new TextDecoder().decode(blob);
  }

  async readByHash(hash: string, opts?: { offset?: number; size?: number }): Promise<Uint8Array> {
    const { blob } = await git.readBlob({ fs: this._fsModule, gitdir: this._gitdir, oid: hash });
    if (opts && (opts.offset !== undefined || opts.size !== undefined)) {
      const offset = opts.offset ?? 0;
      const end = opts.size !== undefined ? offset + opts.size : blob.length;
      return blob.subarray(offset, end);
    }
    return blob;
  }

  async stat(path?: string | null): Promise<StatResult> {
    const mtime = await this._getCommitTime();

    if (path == null || isRootPath(path)) {
      const nlink = 2 + await countSubdirs(this._fsModule, this._gitdir, this._treeOid);
      return {
        mode: modeToInt(MODE_TREE),
        fileType: fileTypeFromMode(MODE_TREE),
        size: 0,
        hash: this._treeOid,
        nlink,
        mtime,
      };
    }

    const normalized = normalizePath(path);
    const entry = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, normalized);
    if (entry === null) throw new FileNotFoundError(normalized);

    if (entry.mode === MODE_TREE) {
      const nlink = 2 + await countSubdirs(this._fsModule, this._gitdir, entry.oid);
      return {
        mode: modeToInt(entry.mode),
        fileType: fileTypeFromMode(entry.mode),
        size: 0,
        hash: entry.oid,
        nlink,
        mtime,
      };
    }

    const { blob } = await git.readBlob({ fs: this._fsModule, gitdir: this._gitdir, oid: entry.oid });
    return {
      mode: modeToInt(entry.mode),
      fileType: fileTypeFromMode(entry.mode),
      size: blob.length,
      hash: entry.oid,
      nlink: 1,
      mtime,
    };
  }

  async listdir(path?: string | null): Promise<WalkEntry[]> {
    return listEntriesAtPath(this._fsModule, this._gitdir, this._treeOid, path);
  }

  // ---------------------------------------------------------------------------
  // Glob
  // ---------------------------------------------------------------------------

  async glob(pattern: string): Promise<string[]> {
    const results: string[] = [];
    for await (const path of this.iglob(pattern)) {
      results.push(path);
    }
    return results.sort();
  }

  async *iglob(pattern: string): AsyncGenerator<string> {
    pattern = pattern.replace(/^\/+|\/+$/g, '');
    if (!pattern) return;

    // Handle /./  pivot marker (rsync -R style)
    const pivotIdx = pattern.indexOf('/./');
    if (pivotIdx > 0) {
      const base = pattern.slice(0, pivotIdx);
      const rest = pattern.slice(pivotIdx + 3);
      const flat = rest ? `${base}/${rest}` : base;
      const basePrefix = base + '/';
      const seen = new Set<string>();
      for await (const path of this._iglobWalk(flat.split('/'), null, this._treeOid)) {
        if (!seen.has(path)) {
          seen.add(path);
          yield path.startsWith(basePrefix)
            ? `${base}/./${path.slice(basePrefix.length)}`
            : `${base}/./${path}`;
        }
      }
      return;
    }

    const seen = new Set<string>();
    for await (const path of this._iglobWalk(pattern.split('/'), null, this._treeOid)) {
      if (!seen.has(path)) {
        seen.add(path);
        yield path;
      }
    }
  }

  /** @internal */
  private async _iglobEntries(
    treeOid: string,
  ): Promise<Array<[string, boolean, string]>> {
    try {
      const { tree } = await git.readTree({ fs: this._fsModule, gitdir: this._gitdir, oid: treeOid });
      return tree.map((e) => [e.path, e.mode === MODE_TREE, e.oid] as [string, boolean, string]);
    } catch {
      return [];
    }
  }

  /** @internal */
  private async *_iglobWalk(
    segments: string[],
    prefix: string | null,
    treeOid: string,
  ): AsyncGenerator<string> {
    if (segments.length === 0) return;
    const seg = segments[0];
    const rest = segments.slice(1);

    if (seg === '**') {
      const entries = await this._iglobEntries(treeOid);
      if (rest.length > 0) {
        yield* this._iglobMatchEntries(rest, prefix, entries);
      } else {
        for (const [name, , ] of entries) {
          if (name.startsWith('.')) continue;
          yield prefix ? `${prefix}/${name}` : name;
        }
      }
      for (const [name, isDir, oid] of entries) {
        if (name.startsWith('.')) continue;
        const full = prefix ? `${prefix}/${name}` : name;
        if (isDir) {
          yield* this._iglobWalk(segments, full, oid); // keep **
        }
      }
      return;
    }

    const hasWild = seg.includes('*') || seg.includes('?');

    if (hasWild) {
      const entries = await this._iglobEntries(treeOid);
      for (const [name, , oid] of entries) {
        if (!globMatch(seg, name)) continue;
        const full = prefix ? `${prefix}/${name}` : name;
        if (rest.length > 0) {
          yield* this._iglobWalk(rest, full, oid);
        } else {
          yield full;
        }
      }
    } else {
      // Literal segment — look up directly
      try {
        const { tree } = await git.readTree({ fs: this._fsModule, gitdir: this._gitdir, oid: treeOid });
        const entry = tree.find((e) => e.path === seg);
        if (!entry) return;
        const full = prefix ? `${prefix}/${seg}` : seg;
        if (rest.length > 0) {
          yield* this._iglobWalk(rest, full, entry.oid);
        } else {
          yield full;
        }
      } catch {
        return;
      }
    }
  }

  /** @internal */
  private async *_iglobMatchEntries(
    segments: string[],
    prefix: string | null,
    entries: Array<[string, boolean, string]>,
  ): AsyncGenerator<string> {
    const seg = segments[0];
    const rest = segments.slice(1);
    const hasWild = seg.includes('*') || seg.includes('?');

    if (hasWild) {
      for (const [name, , oid] of entries) {
        if (!globMatch(seg, name)) continue;
        const full = prefix ? `${prefix}/${name}` : name;
        if (rest.length > 0) {
          yield* this._iglobWalk(rest, full, oid);
        } else {
          yield full;
        }
      }
    } else {
      for (const [name, , oid] of entries) {
        if (name === seg) {
          const full = prefix ? `${prefix}/${seg}` : seg;
          if (rest.length > 0) {
            yield* this._iglobWalk(rest, full, oid);
          } else {
            yield full;
          }
          return;
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Write operations
  // ---------------------------------------------------------------------------

  /**
   * @internal Build ChangeReport from writes and removes with type detection.
   */
  async _buildChanges(
    writes: Map<string, TreeWrite>,
    removes: Set<string>,
  ): Promise<ChangeReport> {
    const changes = emptyChangeReport();

    for (const [path, write] of writes) {
      const existing = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, path);
      if (existing !== null) {
        // Compare OID + mode to skip unchanged
        const newOid = write.oid ?? (write.data
          ? await git.writeBlob({ fs: this._fsModule, gitdir: this._gitdir, blob: write.data })
          : null);
        if (newOid === existing.oid && write.mode === existing.mode) continue;
        changes.update.push(fileEntryFromMode(path, write.mode));
      } else {
        changes.add.push(fileEntryFromMode(path, write.mode));
      }
    }

    for (const path of removes) {
      const existing = await entryAtPath(this._fsModule, this._gitdir, this._treeOid, path);
      if (existing) {
        changes.delete.push(fileEntryFromMode(path, existing.mode));
      } else {
        changes.delete.push({ path, type: 'blob' });
      }
    }

    return changes;
  }

  /**
   * @internal Commit changes: rebuild tree, create commit, update ref atomically.
   */
  async _commitChanges(
    writes: Map<string, TreeWrite>,
    removes: Set<string>,
    message?: string | null,
    operation?: string | null,
  ): Promise<FS> {
    if (!this._writable) throw this._readonlyError('write to');

    const changes = await this._buildChanges(writes, removes);
    const finalMessage = formatCommitMessage(changes, message, operation);

    const newTreeOid = await rebuildTree(
      this._fsModule,
      this._gitdir,
      this._treeOid,
      writes,
      removes,
    );

    // Atomic check-and-update under lock
    const refName = `refs/heads/${this._refName}`;
    const sig = this._store._signature;
    const committerStr = `${sig.name} <${sig.email}>`;
    const commitOid = this._commitOid;
    const store = this._store;

    const newCommitOid = await withRepoLock(this._fsModule, this._gitdir, async () => {
      // Check for stale snapshot
      const currentOid = await git.resolveRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
      });
      if (currentOid !== commitOid) {
        throw new StaleSnapshotError(
          `Branch '${this._refName}' has advanced since this snapshot`,
        );
      }

      if (newTreeOid === this._treeOid) {
        return null; // nothing changed
      }

      // Create commit
      const now = Math.floor(Date.now() / 1000);
      const oid = await git.writeCommit({
        fs: this._fsModule,
        gitdir: this._gitdir,
        commit: {
          message: finalMessage + '\n',
          tree: newTreeOid,
          parent: [commitOid],
          author: { name: sig.name, email: sig.email, timestamp: now, timezoneOffset: 0 },
          committer: { name: sig.name, email: sig.email, timestamp: now, timezoneOffset: 0 },
        },
      });

      // Update ref
      await git.writeRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
        value: oid,
        force: true,
      });

      // Write reflog entry
      await writeReflogEntry(
        this._fsModule,
        this._gitdir,
        refName,
        commitOid,
        oid,
        committerStr,
        `commit: ${finalMessage}`,
      );

      return oid;
    });

    if (newCommitOid === null) return this; // nothing changed

    const newFs = new FS(store, newCommitOid, newTreeOid, this._refName, this._writable);
    newFs._changes = changes;
    return newFs;
  }

  async write(
    path: string,
    data: Uint8Array,
    opts?: { message?: string; mode?: FileType | string },
  ): Promise<FS> {
    const normalized = normalizePath(path);
    const mode = opts?.mode
      ? resolveMode(opts.mode)
      : MODE_BLOB;
    const writes = new Map<string, TreeWrite>([[normalized, { data, mode }]]);
    return this._commitChanges(writes, new Set(), opts?.message);
  }

  async writeText(
    path: string,
    text: string,
    opts?: { message?: string; mode?: FileType | string },
  ): Promise<FS> {
    const data = new TextEncoder().encode(text);
    return this.write(path, data, opts);
  }

  async writeFromFile(
    path: string,
    localPath: string,
    opts?: { message?: string; mode?: FileType | string },
  ): Promise<FS> {
    const normalized = normalizePath(path);
    const detectedMode = await modeFromDisk(this._fsModule, localPath);
    const mode = opts?.mode
      ? resolveMode(opts.mode)
      : detectedMode;
    const data = (await this._fsModule.promises.readFile(localPath)) as Uint8Array;
    const blobOid = await git.writeBlob({ fs: this._fsModule, gitdir: this._gitdir, blob: data });
    const writes = new Map<string, TreeWrite>([[normalized, { oid: blobOid, mode }]]);
    return this._commitChanges(writes, new Set(), opts?.message);
  }

  async writeSymlink(
    path: string,
    target: string,
    opts?: { message?: string },
  ): Promise<FS> {
    const normalized = normalizePath(path);
    const data = new TextEncoder().encode(target);
    const writes = new Map<string, TreeWrite>([[normalized, { data, mode: MODE_LINK }]]);
    return this._commitChanges(writes, new Set(), opts?.message);
  }

  async apply(
    writes?: Record<string, WriteEntry | Uint8Array | string> | null,
    removes?: string | string[] | Set<string> | null,
    opts?: { message?: string; operation?: string },
  ): Promise<FS> {
    const internalWrites = new Map<string, TreeWrite>();

    for (const [path, value] of Object.entries(writes ?? {})) {
      const normalized = normalizePath(path);

      // Normalize to WriteEntry
      let entry: WriteEntry;
      if (value instanceof Uint8Array) {
        entry = { data: value };
      } else if (typeof value === 'string') {
        entry = { data: value };
      } else if (typeof value === 'object' && value !== null) {
        entry = value as WriteEntry;
      } else {
        throw new TypeError(
          `Expected WriteEntry, Uint8Array, or string for '${path}', got ${typeof value}`
        );
      }

      if (entry.target != null) {
        // Symlink
        const data = new TextEncoder().encode(entry.target);
        const blobOid = await git.writeBlob({
          fs: this._fsModule,
          gitdir: this._gitdir,
          blob: data,
        });
        internalWrites.set(normalized, { oid: blobOid, mode: MODE_LINK });
      } else if (entry.data != null) {
        const data =
          typeof entry.data === 'string'
            ? new TextEncoder().encode(entry.data)
            : entry.data;
        const mode = entry.mode
          ? resolveMode(entry.mode)
          : MODE_BLOB;
        internalWrites.set(normalized, { data, mode });
      }
    }

    // Normalize removes
    let removeSet: Set<string>;
    if (removes == null) {
      removeSet = new Set();
    } else if (typeof removes === 'string') {
      removeSet = new Set([normalizePath(removes)]);
    } else if (removes instanceof Set) {
      removeSet = new Set([...removes].map(normalizePath));
    } else {
      removeSet = new Set(removes.map(normalizePath));
    }

    return this._commitChanges(internalWrites, removeSet, opts?.message, opts?.operation);
  }

  /**
   * Create a Batch for accumulating multiple writes before committing.
   */
  batch(opts?: { message?: string; operation?: string }): Batch {
    return new Batch(this, opts?.message, opts?.operation);
  }

  // ---------------------------------------------------------------------------
  // Copy / Sync / Remove / Move (delegates to copy module)
  // ---------------------------------------------------------------------------

  async copyIn(
    sources: string | string[],
    dest: string,
    opts: {
      dryRun?: boolean;
      followSymlinks?: boolean;
      message?: string;
      mode?: string;
      ignoreExisting?: boolean;
      delete?: boolean;
      ignoreErrors?: boolean;
      checksum?: boolean;
    } = {},
  ): Promise<FS> {
    const { copyIn } = await import('./copy.js');
    return copyIn(this, sources, dest, opts);
  }

  async copyOut(
    sources: string | string[],
    dest: string,
    opts: {
      dryRun?: boolean;
      ignoreExisting?: boolean;
      delete?: boolean;
      ignoreErrors?: boolean;
      checksum?: boolean;
    } = {},
  ): Promise<FS> {
    const { copyOut } = await import('./copy.js');
    return copyOut(this, sources, dest, opts);
  }

  async syncIn(
    localPath: string,
    repoPath: string,
    opts: {
      dryRun?: boolean;
      message?: string;
      ignoreErrors?: boolean;
      checksum?: boolean;
    } = {},
  ): Promise<FS> {
    const { syncIn } = await import('./copy.js');
    return syncIn(this, localPath, repoPath, opts);
  }

  async syncOut(
    repoPath: string,
    localPath: string,
    opts: {
      dryRun?: boolean;
      ignoreErrors?: boolean;
      checksum?: boolean;
    } = {},
  ): Promise<FS> {
    const { syncOut } = await import('./copy.js');
    return syncOut(this, repoPath, localPath, opts);
  }

  async remove(
    sources: string | string[],
    opts: { recursive?: boolean; dryRun?: boolean; message?: string } = {},
  ): Promise<FS> {
    const { remove } = await import('./copy.js');
    return remove(this, sources, opts);
  }

  async move(
    sources: string | string[],
    dest: string,
    opts: { recursive?: boolean; dryRun?: boolean; message?: string } = {},
  ): Promise<FS> {
    const { move } = await import('./copy.js');
    return move(this, sources, dest, opts);
  }

  async copyRef(
    source: FS,
    srcPath?: string,
    destPath?: string | null,
    opts?: { delete?: boolean; dryRun?: boolean; message?: string },
  ): Promise<FS> {
    if (!this._writable) throw this._readonlyError('write to');

    // Validate same repo
    const selfPath = this._fsModule.realpathSync(this._gitdir);
    const srcFsPath = this._fsModule.realpathSync(source._gitdir);
    if (selfPath !== srcFsPath) {
      throw new Error('source must belong to the same repo as self');
    }

    const src = srcPath ?? '';
    const dest = destPath !== undefined && destPath !== null ? destPath : src;

    const { walkRepo } = await import('./copy.js');
    const srcFiles = await walkRepo(source, src);
    const destFiles = await walkRepo(this, dest);

    const writes = new Map<string, TreeWrite>();
    const removes = new Set<string>();

    for (const [rel, srcEntry] of srcFiles) {
      const full = dest ? `${dest}/${rel}` : rel;
      const destEntry = destFiles.get(rel);
      if (!destEntry || destEntry.oid !== srcEntry.oid || destEntry.mode !== srcEntry.mode) {
        writes.set(full, { oid: srcEntry.oid, mode: srcEntry.mode });
      }
    }

    if (opts?.delete) {
      for (const rel of destFiles.keys()) {
        if (!srcFiles.has(rel)) {
          const full = dest ? `${dest}/${rel}` : rel;
          removes.add(full);
        }
      }
    }

    if (opts?.dryRun) {
      const changes = await this._buildChanges(writes, removes);
      this._changes = finalizeChanges(changes);
      return this;
    }

    return this._commitChanges(writes, removes, opts?.message, 'cp');
  }

  // ---------------------------------------------------------------------------
  // History
  // ---------------------------------------------------------------------------

  async getParent(): Promise<FS | null> {
    const { commit } = await git.readCommit({
      fs: this._fsModule,
      gitdir: this._gitdir,
      oid: this._commitOid,
    });
    if (!commit.parent || commit.parent.length === 0) return null;
    return FS._fromCommit(this._store, commit.parent[0], this._refName, this._writable);
  }

  async back(n = 1): Promise<FS> {
    if (n < 0) throw new Error(`back() requires n >= 0, got ${n}`);
    let fs: FS = this;
    for (let i = 0; i < n; i++) {
      const p = await fs.getParent();
      if (p === null) throw new Error(`Cannot go back ${n} commits - history too short`);
      fs = p;
    }
    return fs;
  }

  async undo(steps = 1): Promise<FS> {
    if (steps < 1) throw new Error(`steps must be >= 1, got ${steps}`);
    if (!this._writable) throw this._readonlyError('undo');

    let current: FS = this;
    for (let i = 0; i < steps; i++) {
      const parent = await current.getParent();
      if (parent === null) {
        throw new Error(`Cannot undo ${steps} steps - only ${i} commit(s) in history`);
      }
      current = parent;
    }

    const refName = `refs/heads/${this._refName}`;
    const sig = this._store._signature;
    const committerStr = `${sig.name} <${sig.email}>`;
    const myOid = this._commitOid;

    await withRepoLock(this._fsModule, this._gitdir, async () => {
      const currentOid = await git.resolveRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
      });
      if (currentOid !== myOid) {
        throw new StaleSnapshotError(
          `Branch '${this._refName}' has advanced since this snapshot`,
        );
      }
      await git.writeRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
        value: current._commitOid,
        force: true,
      });
      await writeReflogEntry(
        this._fsModule,
        this._gitdir,
        refName,
        myOid,
        current._commitOid,
        committerStr,
        'undo: move back',
      );
    });

    return current;
  }

  async redo(steps = 1): Promise<FS> {
    if (steps < 1) throw new Error(`steps must be >= 1, got ${steps}`);
    if (!this._writable) throw this._readonlyError('redo');

    const refName = `refs/heads/${this._refName}`;

    // Read reflog
    const entries = await readReflog(this._fsModule, this._gitdir, this._refName!);
    if (entries.length === 0) throw new Error('Reflog is empty');

    // Find current position in reflog
    let currentIndex: number | null = null;
    for (let i = entries.length - 1; i >= 0; i--) {
      if (entries[i].newSha === this._commitOid) {
        currentIndex = i;
        break;
      }
    }
    if (currentIndex === null) {
      throw new Error('Cannot redo - current commit not in reflog');
    }

    // Walk back through reflog entries to find target
    let targetSha = this._commitOid;
    let index = currentIndex;
    for (let step = 0; step < steps; step++) {
      if (index < 0) {
        throw new Error(`Cannot redo ${steps} steps - only ${step} step(s) available`);
      }
      targetSha = entries[index].oldSha;
      if (targetSha === ZERO_SHA) {
        throw new Error(
          `Cannot redo ${steps} step(s) - reaches branch creation point`,
        );
      }
      index--;
    }

    const targetFs = await FS._fromCommit(this._store, targetSha, this._refName, this._writable);
    const sig = this._store._signature;
    const committerStr = `${sig.name} <${sig.email}>`;
    const myOid = this._commitOid;

    await withRepoLock(this._fsModule, this._gitdir, async () => {
      const currentOid = await git.resolveRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
      });
      if (currentOid !== myOid) {
        throw new StaleSnapshotError(
          `Branch '${this._refName}' has advanced since this snapshot`,
        );
      }
      await git.writeRef({
        fs: this._fsModule,
        gitdir: this._gitdir,
        ref: refName,
        value: targetSha,
        force: true,
      });
      await writeReflogEntry(
        this._fsModule,
        this._gitdir,
        refName,
        myOid,
        targetSha,
        committerStr,
        'redo: move forward',
      );
    });

    return targetFs;
  }

  async *log(opts?: {
    path?: string;
    match?: string;
    before?: Date;
  }): AsyncGenerator<FS> {
    const filterPath = opts?.path ? normalizePath(opts.path) : null;
    const match = opts?.match ?? null;
    const before = opts?.before ?? null;
    let pastCutoff = false;
    let current: FS | null = this;

    while (current !== null) {
      if (!pastCutoff && before !== null) {
        const time = await current.getTime();
        if (time > before) {
          current = await current.getParent();
          continue;
        }
        pastCutoff = true;
      }

      if (filterPath !== null) {
        const currentEntry = await entryAtPath(
          this._fsModule,
          this._gitdir,
          current._treeOid,
          filterPath,
        );
        const parent = await current.getParent();
        const parentEntry = parent
          ? await entryAtPath(this._fsModule, this._gitdir, parent._treeOid, filterPath)
          : null;
        if (
          currentEntry?.oid === parentEntry?.oid &&
          currentEntry?.mode === parentEntry?.mode
        ) {
          current = parent;
          continue;
        }
      }

      if (match !== null) {
        const msg = await current.getMessage();
        if (!globMatch(match, msg)) {
          current = await current.getParent();
          continue;
        }
      }

      yield current;
      current = await current.getParent();
    }
  }
}

// ---------------------------------------------------------------------------
// Standalone helpers
// ---------------------------------------------------------------------------

import { modeFromDisk } from './tree.js';

/**
 * Resolve a mode that may be a FileType name ('blob', 'executable', 'link')
 * or a git mode string ('100644', '100755', '120000').
 */
function resolveMode(mode: FileType | string): string {
  // Git mode strings are 6-digit octal like '100644'
  if (typeof mode === 'string' && /^\d{6}$/.test(mode)) return mode;
  return fileModeFromType(mode as FileType);
}

/**
 * Write data to a branch with automatic retry on concurrent modification.
 */
export async function retryWrite(
  store: GitStore,
  branch: string,
  path: string,
  data: Uint8Array,
  opts?: { message?: string; mode?: FileType | string; retries?: number },
): Promise<FS> {
  const retries = opts?.retries ?? 5;
  for (let attempt = 0; attempt < retries; attempt++) {
    const fs = await store.branches.get(branch);
    try {
      return await fs.write(path, data, opts);
    } catch (err) {
      if (err instanceof StaleSnapshotError) {
        if (attempt === retries - 1) throw err;
        const delay = Math.min(10 * 2 ** attempt, 200);
        await new Promise((r) => setTimeout(r, Math.random() * delay));
        continue;
      }
      throw err;
    }
  }
  throw new Error('unreachable');
}
