/**
 * Shared types, constants, enums, and error classes for vost.
 */

// ---------------------------------------------------------------------------
// Git file mode constants (octal → string for isomorphic-git)
// ---------------------------------------------------------------------------

/** Git filemode for tree (directory) entries. */
export const MODE_TREE = '040000';
/** Git filemode for regular blob (file) entries. */
export const MODE_BLOB = '100644';
/** Git filemode for executable blob entries. */
export const MODE_BLOB_EXEC = '100755';
/** Git filemode for symbolic link entries. */
export const MODE_LINK = '120000';

/** Convert an octal mode string (e.g. '100644') to an integer. */
export function modeToInt(mode: string): number {
  return parseInt(mode, 8);
}

/** Convert an integer filemode to a zero-padded octal string. */
export function modeFromInt(mode: number): string {
  return mode.toString(8).padStart(6, '0');
}

/** Return the isomorphic-git object type for a given mode string. */
export function typeForMode(mode: string): 'blob' | 'tree' | 'commit' {
  if (mode === MODE_TREE) return 'tree';
  if (mode === '160000') return 'commit';
  return 'blob';
}

// ---------------------------------------------------------------------------
// FileType enum
// ---------------------------------------------------------------------------

/**
 * File type classification for git tree entries.
 *
 * - `BLOB` - Regular file (mode 100644).
 * - `EXECUTABLE` - Executable file (mode 100755).
 * - `LINK` - Symbolic link (mode 120000).
 * - `TREE` - Directory (mode 040000).
 */
export const FileType = {
  /** Regular file (mode 100644). */
  BLOB: 'blob',
  /** Executable file (mode 100755). */
  EXECUTABLE: 'executable',
  /** Symbolic link (mode 120000). */
  LINK: 'link',
  /** Directory (mode 040000). */
  TREE: 'tree',
} as const;

/** Union type of all FileType values. */
export type FileType = (typeof FileType)[keyof typeof FileType];

const MODE_TO_TYPE: Record<string, FileType> = {
  [MODE_BLOB]: FileType.BLOB,
  [MODE_BLOB_EXEC]: FileType.EXECUTABLE,
  [MODE_LINK]: FileType.LINK,
  [MODE_TREE]: FileType.TREE,
};

const TYPE_TO_MODE: Record<FileType, string> = {
  [FileType.BLOB]: MODE_BLOB,
  [FileType.EXECUTABLE]: MODE_BLOB_EXEC,
  [FileType.LINK]: MODE_LINK,
  [FileType.TREE]: MODE_TREE,
};

/**
 * Convert a git filemode string to a FileType enum value.
 *
 * @param mode - Octal mode string (e.g. '100644').
 * @returns The corresponding FileType.
 * @throws {Error} If the mode is not recognized.
 */
export function fileTypeFromMode(mode: string): FileType {
  const ft = MODE_TO_TYPE[mode];
  if (!ft) throw new Error(`Unknown git mode: ${mode}`);
  return ft;
}

/**
 * Convert a FileType enum value to a git filemode string.
 *
 * @param ft - FileType value.
 * @returns The corresponding octal mode string.
 */
export function fileModeFromType(ft: FileType): string {
  return TYPE_TO_MODE[ft];
}

// ---------------------------------------------------------------------------
// Error classes
// ---------------------------------------------------------------------------

/** Base error class for all vost errors. */
export class GitStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GitStoreError';
  }
}

/**
 * Raised when a branch has advanced since the FS snapshot was taken,
 * causing a compare-and-swap (CAS) failure on commit.
 */
export class StaleSnapshotError extends GitStoreError {
  constructor(message: string) {
    super(message);
    this.name = 'StaleSnapshotError';
  }
}

/** Raised when a path does not exist in the repository tree. */
export class FileNotFoundError extends GitStoreError {
  code = 'ENOENT';
  constructor(path: string) {
    super(`File not found: ${path}`);
    this.name = 'FileNotFoundError';
  }
}

/** Raised when an operation expected a file but found a directory. */
export class IsADirectoryError extends GitStoreError {
  code = 'EISDIR';
  constructor(path: string) {
    super(`Is a directory: ${path}`);
    this.name = 'IsADirectoryError';
  }
}

/** Raised when an operation expected a directory but found a file. */
export class NotADirectoryError extends GitStoreError {
  code = 'ENOTDIR';
  constructor(path: string) {
    super(`Not a directory: ${path}`);
    this.name = 'NotADirectoryError';
  }
}

/** Raised when a write is attempted on a read-only snapshot (e.g. a tag). */
export class PermissionError extends GitStoreError {
  code = 'EPERM';
  constructor(message: string) {
    super(message);
    this.name = 'PermissionError';
  }
}

// ---------------------------------------------------------------------------
// Data structures
// ---------------------------------------------------------------------------

/**
 * A file or directory entry yielded by `FS.walk()` and `FS.listdir()`.
 */
export interface WalkEntry {
  /** Entry name (file or directory basename). */
  name: string;
  /** 40-char hex object ID (SHA). */
  oid: string;
  /** Git filemode string (e.g. '100644', '040000'). */
  mode: string;
}

/**
 * POSIX-like stat result for a vost path.
 *
 * Combines file type, size, OID, nlink, and mtime in a single structure,
 * optimized for the FUSE `getattr` hot path.
 */
export interface StatResult {
  /** Raw git filemode as integer (e.g. 0o100644, 0o040000). */
  mode: number;
  /** File type classification. */
  fileType: FileType;
  /** Object size in bytes (0 for directories). */
  size: number;
  /** 40-char hex SHA of the object (inode proxy). */
  hash: string;
  /** 1 for files/symlinks, 2 + subdirectory count for directories. */
  nlink: number;
  /** Commit timestamp as POSIX epoch seconds. */
  mtime: number;
}

/**
 * Return the FileType for a WalkEntry.
 *
 * @param entry - A walk entry from `FS.walk()` or `FS.listdir()`.
 * @returns The FileType corresponding to the entry's mode.
 */
export function walkEntryFileType(entry: WalkEntry): FileType {
  return fileTypeFromMode(entry.mode);
}

/**
 * Describes a single file write for `FS.apply()`.
 *
 * Exactly one of `data` or `target` must be provided.
 * `target` creates a symbolic link entry; `mode` is not allowed with it.
 */
export interface WriteEntry {
  /** Raw data (bytes) or text (string). Mutually exclusive with `target`. */
  data?: Uint8Array | string;
  /** Git filemode override (e.g. FileType.EXECUTABLE). */
  mode?: FileType | string;
  /** Symlink target string. Mutually exclusive with `data`. */
  target?: string;
}

/**
 * Validate a WriteEntry, throwing if both `data` and `target` are set,
 * neither is set, or `mode` is combined with `target`.
 */
export function validateWriteEntry(entry: WriteEntry): void {
  if (entry.data != null && entry.target != null) {
    throw new Error('Cannot specify both data and target');
  }
  if (entry.data == null && entry.target == null) {
    throw new Error('Must specify either data or target');
  }
  if (entry.target != null && entry.mode != null) {
    throw new Error('Cannot specify mode for symlinks');
  }
}

// ---------------------------------------------------------------------------
// Change tracking
// ---------------------------------------------------------------------------

/**
 * A file entry in a change report, with path and type information.
 */
export interface FileEntry {
  /** Repo-relative path. */
  path: string;
  /** File type (blob, executable, link, or tree). */
  type: FileType;
  /** Optional source path (for copy operations). */
  src?: string;
}

/**
 * Create a FileEntry from a path and git filemode string.
 *
 * @param path - Repo-relative path.
 * @param mode - Git filemode string.
 * @param src - Optional source path.
 */
export function fileEntryFromMode(path: string, mode: string, src?: string): FileEntry {
  return { path, type: fileTypeFromMode(mode), src };
}

/** A single action entry (add, update, or delete) for a path. */
export interface ChangeAction {
  /** Repo-relative path. */
  path: string;
  /** The kind of change. */
  action: 'add' | 'update' | 'delete';
}

/** An error or warning associated with a path during a copy/sync operation. */
export interface ChangeError {
  /** Repo-relative path that caused the error. */
  path: string;
  /** Human-readable error description. */
  error: string;
}

/**
 * Report of changes from a write, copy, sync, remove, or move operation.
 *
 * Available on the resulting FS via `fs.changes`.
 */
export interface ChangeReport {
  /** Files that were added. */
  add: FileEntry[];
  /** Files that were updated. */
  update: FileEntry[];
  /** Files that were deleted. */
  delete: FileEntry[];
  /** Errors encountered during the operation. */
  errors: ChangeError[];
  /** Warnings encountered during the operation. */
  warnings: ChangeError[];
}

/** Create an empty ChangeReport with no actions or errors. */
export function emptyChangeReport(): ChangeReport {
  return { add: [], update: [], delete: [], errors: [], warnings: [] };
}

/** Return true if the report contains no adds, updates, or deletes. */
export function changeReportInSync(cr: ChangeReport): boolean {
  return cr.add.length === 0 && cr.update.length === 0 && cr.delete.length === 0;
}

/** Return the total number of adds, updates, and deletes. */
export function changeReportTotal(cr: ChangeReport): number {
  return cr.add.length + cr.update.length + cr.delete.length;
}

/** Flatten a ChangeReport into a sorted list of ChangeAction entries. */
export function changeReportActions(cr: ChangeReport): ChangeAction[] {
  const result: ChangeAction[] = [];
  for (const e of cr.add) result.push({ path: e.path, action: 'add' });
  for (const e of cr.update) result.push({ path: e.path, action: 'update' });
  for (const e of cr.delete) result.push({ path: e.path, action: 'delete' });
  result.sort((a, b) => a.path.localeCompare(b.path));
  return result;
}

/** Return null if the report is completely empty, otherwise return it as-is. */
export function finalizeChanges(cr: ChangeReport): ChangeReport | null {
  if (
    cr.add.length === 0 &&
    cr.update.length === 0 &&
    cr.delete.length === 0 &&
    cr.errors.length === 0 &&
    cr.warnings.length === 0
  ) {
    return null;
  }
  return cr;
}

/**
 * Generate a commit message from a ChangeReport.
 *
 * If `customMessage` is provided and contains `{` placeholders, they are
 * expanded (e.g. `{add_count}`, `{total_count}`, `{default}`).
 * Otherwise, an auto-generated summary is used.
 *
 * @param changes - The change report to summarize.
 * @param customMessage - Optional user-provided message template.
 * @param operation - Optional operation name for auto messages (e.g. 'cp').
 */
export function formatCommitMessage(
  changes: ChangeReport,
  customMessage?: string | null,
  operation?: string | null,
): string {
  if (customMessage) {
    if (customMessage.includes('{')) {
      const def = autoMessage(changes, operation ?? null);
      return customMessage
        .replace('{default}', def)
        .replace('{add_count}', String(changes.add.length))
        .replace('{update_count}', String(changes.update.length))
        .replace('{delete_count}', String(changes.delete.length))
        .replace('{total_count}', String(changeReportTotal(changes)))
        .replace('{op}', operation ?? '');
    }
    return customMessage;
  }
  return autoMessage(changes, operation ?? null);
}

function autoMessage(changes: ChangeReport, operation: string | null): string {
  const total = changeReportTotal(changes);
  if (total === 0) return 'No changes';

  if (total === 1) {
    if (changes.add.length) {
      const e = changes.add[0];
      return `+ ${e.path}` + (e.type !== FileType.BLOB ? ` (${e.type})` : '');
    }
    if (changes.update.length) {
      const e = changes.update[0];
      return `~ ${e.path}` + (e.type !== FileType.BLOB ? ` (${e.type})` : '');
    }
    return `- ${changes.delete[0].path}`;
  }

  const parts: string[] = [];
  if (changes.add.length) parts.push(`+${changes.add.length}`);
  if (changes.update.length) parts.push(`~${changes.update.length}`);
  if (changes.delete.length) parts.push(`-${changes.delete.length}`);

  const prefix = operation ? `Batch ${operation}:` : 'Batch:';
  return `${prefix} ${parts.join(' ')}`;
}

// ---------------------------------------------------------------------------
// Mirror data structures
// ---------------------------------------------------------------------------

/** A single ref change in a mirror operation (backup or restore). */
export interface RefChange {
  /** Full ref name (e.g. 'refs/heads/main'). */
  ref: string;
  /** Previous target SHA, or undefined for newly created refs. */
  oldTarget?: string;
  /** New target SHA, or undefined for deleted refs. */
  newTarget?: string;
}

/**
 * Report of ref changes from a `backup()` or `restore()` mirror operation.
 */
export interface MirrorDiff {
  /** Refs that were created. */
  add: RefChange[];
  /** Refs whose target changed. */
  update: RefChange[];
  /** Refs that were deleted. */
  delete: RefChange[];
}

/** Return true if the mirror diff contains no changes. */
export function mirrorDiffInSync(md: MirrorDiff): boolean {
  return md.add.length === 0 && md.update.length === 0 && md.delete.length === 0;
}

/** Return the total number of ref changes. */
export function mirrorDiffTotal(md: MirrorDiff): number {
  return md.add.length + md.update.length + md.delete.length;
}

// ---------------------------------------------------------------------------
// Reflog
// ---------------------------------------------------------------------------

/**
 * A single reflog entry recording a branch movement.
 */
export interface ReflogEntry {
  /** Previous 40-char hex commit SHA. */
  oldSha: string;
  /** New 40-char hex commit SHA. */
  newSha: string;
  /** Identity string of the committer. */
  committer: string;
  /** POSIX epoch seconds of the entry. */
  timestamp: number;
  /** Reflog message (e.g. 'commit: + file.txt'). */
  message: string;
}

// ---------------------------------------------------------------------------
// FS module interface (Node.js fs compatible)
// ---------------------------------------------------------------------------

/**
 * The filesystem interface expected by vost.
 * Compatible with Node.js `fs` module and isomorphic-git's FsClient.
 */
export interface FsModule {
  promises: {
    readFile(path: string, options?: { encoding?: string }): Promise<Uint8Array | string>;
    writeFile(path: string, data: Uint8Array | string, options?: { mode?: number }): Promise<void>;
    unlink(path: string): Promise<void>;
    readdir(path: string): Promise<string[]>;
    mkdir(path: string, options?: { recursive?: boolean }): Promise<string | undefined>;
    rmdir(path: string): Promise<void>;
    stat(path: string): Promise<{ mode: number; size: number; isDirectory(): boolean; isFile(): boolean; isSymbolicLink(): boolean; mtimeMs: number }>;
    lstat(path: string): Promise<{ mode: number; size: number; isDirectory(): boolean; isFile(): boolean; isSymbolicLink(): boolean; mtimeMs: number }>;
    readlink(path: string): Promise<string>;
    symlink(target: string, path: string): Promise<void>;
    chmod(path: string, mode: number): Promise<void>;
    access(path: string, mode?: number): Promise<void>;
    appendFile(path: string, data: Uint8Array | string): Promise<void>;
    rename(path: string, newPath: string): Promise<void>;
    open(path: string, flags: string | number, mode?: number): Promise<{ close(): Promise<void> }>;
    rm?(path: string, options?: { recursive?: boolean; force?: boolean }): Promise<void>;
  };

  // Sync methods
  realpathSync(path: string): string;

  // Callback-based methods required by isomorphic-git
  readFile: Function;
  writeFile: Function;
  unlink: Function;
  readdir: Function;
  mkdir: Function;
  rmdir: Function;
  stat: Function;
  lstat: Function;
  readlink: Function;
  symlink: Function;
  chmod: Function;
}

/** HTTP client interface for mirror operations (compatible with isomorphic-git). */
export interface HttpClient {
  request: Function;
}

/** Author/committer identity used for commits. */
export interface Signature {
  /** Author name (e.g. 'vost'). */
  name: string;
  /** Author email (e.g. 'vost@localhost'). */
  email: string;
}

/** Metadata extracted from a git commit object. */
export interface CommitInfo {
  /** Commit message (trailing newline stripped). */
  message: string;
  /** Timezone-aware commit timestamp. */
  time: Date;
  /** Commit author's name. */
  authorName: string;
  /** Commit author's email address. */
  authorEmail: string;
}
