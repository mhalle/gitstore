/**
 * Git notes support: per-namespace mapping of commit hashes to note text.
 *
 * Notes live at `refs/notes/<namespace>`, mapping commit hashes to UTF-8
 * text blobs. Reads handle both flat (40-char filename) and 2/38 fanout
 * layouts. Writes always use flat. Each mutation creates a commit on the
 * namespace's notes ref chain, or batch() defers to a single commit.
 */

import git from 'isomorphic-git';
import { MODE_BLOB, MODE_TREE, GitStoreError, type FsModule } from './types.js';
import { withRepoLock } from './lock.js';
import type { GitStore } from './gitstore.js';

const HEX40_RE = /^[0-9a-f]{40}$/;

function validateHash(h: string): void {
  if (typeof h !== 'string' || !HEX40_RE.test(h)) {
    throw new GitStoreError(
      `Invalid commit hash: '${h}' (must be 40-char lowercase hex)`,
    );
  }
}

// -----------------------------------------------------------------------
// NoteNamespace
// -----------------------------------------------------------------------

export class NoteNamespace {
  /** @internal */ _store: GitStore;
  /** @internal */ _namespace: string;
  /** @internal */ _ref: string;

  constructor(store: GitStore, namespace: string) {
    this._store = store;
    this._namespace = namespace;
    this._ref = `refs/notes/${namespace}`;
  }

  toString(): string {
    return `NoteNamespace('${this._namespace}')`;
  }

  // -- internal helpers --------------------------------------------------

  private get _fs(): FsModule {
    return this._store._fsModule;
  }

  private get _gitdir(): string {
    return this._store._gitdir;
  }

  /** Resolve the notes ref to a commit OID, or null. */
  private async _tipOid(): Promise<string | null> {
    try {
      return await git.resolveRef({
        fs: this._fs,
        gitdir: this._gitdir,
        ref: this._ref,
      });
    } catch {
      return null;
    }
  }

  /** Read the tree OID from the tip commit, or null. */
  private async _treeOid(): Promise<string | null> {
    const tip = await this._tipOid();
    if (tip === null) return null;
    const { commit } = await git.readCommit({
      fs: this._fs,
      gitdir: this._gitdir,
      oid: tip,
    });
    return commit.tree;
  }

  /** Find the blob OID for `hash` in a tree, handling flat and fanout. */
  private async _findNoteInTree(
    treeOid: string,
    hash: string,
  ): Promise<string | null> {
    const entries = await git.readTree({
      fs: this._fs,
      gitdir: this._gitdir,
      oid: treeOid,
    });

    // Try flat: entry named by full 40-char hash
    for (const e of entries.tree) {
      if (e.path === hash && e.mode !== MODE_TREE) {
        return e.oid;
      }
    }

    // Try 2/38 fanout
    const prefix = hash.slice(0, 2);
    const suffix = hash.slice(2);
    for (const e of entries.tree) {
      if (e.path === prefix && e.mode === MODE_TREE) {
        const sub = await git.readTree({
          fs: this._fs,
          gitdir: this._gitdir,
          oid: e.oid,
        });
        for (const se of sub.tree) {
          if (se.path === suffix) {
            return se.oid;
          }
        }
      }
    }

    return null;
  }

  /** Yield all [hash, blobOid] pairs from the tree. */
  private async _iterNotes(
    treeOid: string,
  ): Promise<Array<[string, string]>> {
    const result: Array<[string, string]> = [];
    const entries = await git.readTree({
      fs: this._fs,
      gitdir: this._gitdir,
      oid: treeOid,
    });

    for (const e of entries.tree) {
      if (e.mode === MODE_TREE && e.path.length === 2) {
        // Fanout subtree
        const sub = await git.readTree({
          fs: this._fs,
          gitdir: this._gitdir,
          oid: e.oid,
        });
        for (const se of sub.tree) {
          const full = e.path + se.path;
          if (HEX40_RE.test(full)) {
            result.push([full, se.oid]);
          }
        }
      } else if (HEX40_RE.test(e.path)) {
        result.push([e.path, e.oid]);
      }
    }
    return result;
  }

  /** Build a new note tree from a base tree + writes + deletes. */
  private async _buildNoteTree(
    baseTreeOid: string | null,
    writes: Map<string, string>,  // hash → text
    deletes: Set<string>,
  ): Promise<string> {
    // Load existing tree entries
    const treeEntries = new Map<string, { mode: string; oid: string }>();

    if (baseTreeOid !== null) {
      const { tree } = await git.readTree({
        fs: this._fs,
        gitdir: this._gitdir,
        oid: baseTreeOid,
      });
      for (const e of tree) {
        treeEntries.set(e.path, { mode: e.mode, oid: e.oid });
      }
    }

    // Process deletes
    for (const h of deletes) {
      let removed = false;

      // Try flat removal
      if (treeEntries.has(h)) {
        const entry = treeEntries.get(h)!;
        if (entry.mode !== MODE_TREE) {
          treeEntries.delete(h);
          removed = true;
        }
      }

      // Try fanout removal
      if (!removed) {
        const prefix = h.slice(0, 2);
        const suffix = h.slice(2);
        const prefixEntry = treeEntries.get(prefix);
        if (prefixEntry && prefixEntry.mode === MODE_TREE) {
          const sub = await git.readTree({
            fs: this._fs,
            gitdir: this._gitdir,
            oid: prefixEntry.oid,
          });
          const subEntry = sub.tree.find((e) => e.path === suffix);
          if (subEntry) {
            const newSubEntries = sub.tree.filter((e) => e.path !== suffix);
            if (newSubEntries.length === 0) {
              treeEntries.delete(prefix);
            } else {
              const newSubOid = await git.writeTree({
                fs: this._fs,
                gitdir: this._gitdir,
                tree: newSubEntries.map((e) => ({
                  mode: e.mode,
                  path: e.path,
                  oid: e.oid,
                  type: 'blob',
                })),
              });
              treeEntries.set(prefix, { mode: MODE_TREE, oid: newSubOid });
            }
            removed = true;
          }
        }
      }

      if (!removed) {
        throw new GitStoreError(`key not found: ${h}`);
      }
    }

    // Process writes (flat, clearing fanout if present)
    for (const [h, text] of writes) {
      const blobOid = await git.writeBlob({
        fs: this._fs,
        gitdir: this._gitdir,
        blob: new TextEncoder().encode(text),
      });

      // Remove fanout entry if present
      if (baseTreeOid !== null) {
        const prefix = h.slice(0, 2);
        const suffix = h.slice(2);
        const prefixEntry = treeEntries.get(prefix);
        if (prefixEntry && prefixEntry.mode === MODE_TREE) {
          const sub = await git.readTree({
            fs: this._fs,
            gitdir: this._gitdir,
            oid: prefixEntry.oid,
          });
          if (sub.tree.some((e) => e.path === suffix)) {
            const newSubEntries = sub.tree.filter((e) => e.path !== suffix);
            if (newSubEntries.length === 0) {
              treeEntries.delete(prefix);
            } else {
              const newSubOid = await git.writeTree({
                fs: this._fs,
                gitdir: this._gitdir,
                tree: newSubEntries.map((e) => ({
                  mode: e.mode,
                  path: e.path,
                  oid: e.oid,
                  type: 'blob',
                })),
              });
              treeEntries.set(prefix, { mode: MODE_TREE, oid: newSubOid });
            }
          }
        }
      }

      // Write flat entry
      treeEntries.set(h, { mode: MODE_BLOB, oid: blobOid });
    }

    // Write final tree
    const entries = Array.from(treeEntries.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([path, { mode, oid }]) => ({
        mode,
        path,
        oid,
        type: mode === MODE_TREE ? ('tree' as const) : ('blob' as const),
      }));

    return await git.writeTree({
      fs: this._fs,
      gitdir: this._gitdir,
      tree: entries,
    });
  }

  /** Commit a new tree to the notes ref under repo lock. */
  private async _commitNoteTree(
    newTreeOid: string,
    message: string,
  ): Promise<void> {
    await withRepoLock(this._fs, this._gitdir, async () => {
      // Re-read tip inside lock
      let parents: string[];
      try {
        const tip = await git.resolveRef({
          fs: this._fs,
          gitdir: this._gitdir,
          ref: this._ref,
        });
        parents = [tip];
      } catch {
        parents = [];
      }

      const now = Math.floor(Date.now() / 1000);
      const sig = this._store._signature;

      const commitOid = await git.writeCommit({
        fs: this._fs,
        gitdir: this._gitdir,
        commit: {
          message: `${message}\n`,
          tree: newTreeOid,
          parent: parents,
          author: { name: sig.name, email: sig.email, timestamp: now, timezoneOffset: 0 },
          committer: { name: sig.name, email: sig.email, timestamp: now, timezoneOffset: 0 },
        },
      });

      await git.writeRef({
        fs: this._fs,
        gitdir: this._gitdir,
        ref: this._ref,
        value: commitOid,
        force: true,
      });
    });
  }

  // -- public API --------------------------------------------------------

  async get(hash: string): Promise<string> {
    validateHash(hash);
    const treeOid = await this._treeOid();
    if (treeOid === null) {
      throw new GitStoreError(`key not found: ${hash}`);
    }
    const blobOid = await this._findNoteInTree(treeOid, hash);
    if (blobOid === null) {
      throw new GitStoreError(`key not found: ${hash}`);
    }
    const { blob } = await git.readBlob({
      fs: this._fs,
      gitdir: this._gitdir,
      oid: blobOid,
    });
    return new TextDecoder().decode(blob);
  }

  async set(hash: string, text: string): Promise<void> {
    validateHash(hash);
    const writes = new Map<string, string>();
    writes.set(hash, text);
    const treeOid = await this._treeOid();
    const newTreeOid = await this._buildNoteTree(treeOid, writes, new Set());
    await this._commitNoteTree(newTreeOid, `Notes added by 'git notes' on ${hash.slice(0, 7)}`);
  }

  async delete(hash: string): Promise<void> {
    validateHash(hash);
    const treeOid = await this._treeOid();
    if (treeOid === null) {
      throw new GitStoreError(`key not found: ${hash}`);
    }
    const deletes = new Set<string>();
    deletes.add(hash);
    const newTreeOid = await this._buildNoteTree(treeOid, new Map(), deletes);
    await this._commitNoteTree(newTreeOid, `Notes removed by 'git notes' on ${hash.slice(0, 7)}`);
  }

  async has(hash: string): Promise<boolean> {
    validateHash(hash);
    const treeOid = await this._treeOid();
    if (treeOid === null) return false;
    return (await this._findNoteInTree(treeOid, hash)) !== null;
  }

  async list(): Promise<string[]> {
    const treeOid = await this._treeOid();
    if (treeOid === null) return [];
    const notes = await this._iterNotes(treeOid);
    return notes.map(([h]) => h);
  }

  async size(): Promise<number> {
    const treeOid = await this._treeOid();
    if (treeOid === null) return 0;
    const notes = await this._iterNotes(treeOid);
    return notes.length;
  }

  async getForCurrentBranch(): Promise<string> {
    const current = await this._store.branches.getCurrent();
    if (current === null) {
      throw new GitStoreError('HEAD is dangling — no current branch');
    }
    return this.get(current.commitHash);
  }

  async setForCurrentBranch(text: string): Promise<void> {
    const current = await this._store.branches.getCurrent();
    if (current === null) {
      throw new GitStoreError('HEAD is dangling — no current branch');
    }
    return this.set(current.commitHash, text);
  }

  batch(): NotesBatch {
    return new NotesBatch(this);
  }
}

// -----------------------------------------------------------------------
// NotesBatch
// -----------------------------------------------------------------------

export class NotesBatch {
  private _ns: NoteNamespace;
  private _writes = new Map<string, string>();
  private _deletes = new Set<string>();
  private _closed = false;

  constructor(ns: NoteNamespace) {
    this._ns = ns;
  }

  async set(hash: string, text: string): Promise<void> {
    if (this._closed) throw new GitStoreError('Batch is closed');
    validateHash(hash);
    this._deletes.delete(hash);
    this._writes.set(hash, text);
  }

  delete(hash: string): void {
    if (this._closed) throw new GitStoreError('Batch is closed');
    validateHash(hash);
    this._writes.delete(hash);
    this._deletes.add(hash);
  }

  async commit(): Promise<void> {
    if (this._closed) throw new GitStoreError('Batch is already committed');
    this._closed = true;

    if (this._writes.size === 0 && this._deletes.size === 0) {
      return;
    }

    const treeOid = await this._ns._treeOid();
    const newTreeOid = await this._ns._buildNoteTree(
      treeOid,
      this._writes,
      this._deletes,
    );
    const count = this._writes.size + this._deletes.size;
    await this._ns._commitNoteTree(
      newTreeOid,
      `Notes batch update (${count} changes)`,
    );
  }
}

// -----------------------------------------------------------------------
// NoteDict
// -----------------------------------------------------------------------

export class NoteDict {
  private _store: GitStore;

  constructor(store: GitStore) {
    this._store = store;
  }

  toString(): string {
    return `NoteDict(${this._store.toString()})`;
  }

  get commits(): NoteNamespace {
    return new NoteNamespace(this._store, 'commits');
  }

  namespace(name: string): NoteNamespace {
    return new NoteNamespace(this._store, name);
  }
}
