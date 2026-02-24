/**
 * gitstore — A versioned filesystem backed by a bare git repository.
 *
 * TypeScript port using isomorphic-git.
 *
 * @example
 * ```ts
 * import * as fs from 'node:fs';
 * import { GitStore } from 'gitstore';
 *
 * const store = await GitStore.open('/tmp/myrepo.git', { fs });
 * const snapshot = await store.branches.get('main');
 *
 * // Read
 * const text = await snapshot.readText('hello.txt');
 *
 * // Write (returns new immutable snapshot)
 * const next = await snapshot.writeText('hello.txt', 'Hello, world!');
 *
 * // Batch writes
 * const batch = next.batch();
 * await batch.write('a.txt', new TextEncoder().encode('aaa'));
 * await batch.write('b.txt', new TextEncoder().encode('bbb'));
 * const result = await batch.commit();
 * ```
 */

// Core classes
export { GitStore } from './gitstore.js';
export { FS, retryWrite } from './fs.js';
export { Batch } from './batch.js';
export { RefDict } from './refdict.js';
export { NoteDict, NoteNamespace, NotesBatch } from './notes.js';

// Types and data structures
export {
  // File types & modes
  FileType,
  fileTypeFromMode,
  fileModeFromType,
  MODE_BLOB,
  MODE_BLOB_EXEC,
  MODE_LINK,
  MODE_TREE,

  // Errors
  GitStoreError,
  StaleSnapshotError,
  FileNotFoundError,
  IsADirectoryError,
  NotADirectoryError,
  PermissionError,

  // Data structures
  type WalkEntry,
  type WriteEntry,
  type StatResult,
  type FileEntry,
  type ChangeAction,
  type ChangeError,
  type ChangeReport,
  type RefChange,
  type MirrorDiff,
  type CommitInfo,
  type ReflogEntry,
  type Signature,
  type FsModule,
  type HttpClient,

  // ChangeReport helpers
  emptyChangeReport,
  changeReportInSync,
  changeReportTotal,
  changeReportActions,

  // MirrorDiff helpers
  mirrorDiffInSync,
  mirrorDiffTotal,
} from './types.js';

// Copy operations (usable standalone)
export { diskGlob } from './copy.js';

// Path utilities
export { normalizePath, validateRefName } from './paths.js';
