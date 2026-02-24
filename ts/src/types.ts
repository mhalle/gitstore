/**
 * Shared types, constants, enums, and error classes for gitstore.
 */

// ---------------------------------------------------------------------------
// Git file mode constants (octal → string for isomorphic-git)
// ---------------------------------------------------------------------------

export const MODE_TREE = '040000';
export const MODE_BLOB = '100644';
export const MODE_BLOB_EXEC = '100755';
export const MODE_LINK = '120000';

export function modeToInt(mode: string): number {
  return parseInt(mode, 8);
}

export function modeFromInt(mode: number): string {
  return mode.toString(8).padStart(6, '0');
}

export function typeForMode(mode: string): 'blob' | 'tree' | 'commit' {
  if (mode === MODE_TREE) return 'tree';
  if (mode === '160000') return 'commit';
  return 'blob';
}

// ---------------------------------------------------------------------------
// FileType enum
// ---------------------------------------------------------------------------

export const FileType = {
  BLOB: 'blob',
  EXECUTABLE: 'executable',
  LINK: 'link',
  TREE: 'tree',
} as const;

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

export function fileTypeFromMode(mode: string): FileType {
  const ft = MODE_TO_TYPE[mode];
  if (!ft) throw new Error(`Unknown git mode: ${mode}`);
  return ft;
}

export function fileModeFromType(ft: FileType): string {
  return TYPE_TO_MODE[ft];
}

// ---------------------------------------------------------------------------
// Error classes
// ---------------------------------------------------------------------------

export class GitStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GitStoreError';
  }
}

export class StaleSnapshotError extends GitStoreError {
  constructor(message: string) {
    super(message);
    this.name = 'StaleSnapshotError';
  }
}

export class FileNotFoundError extends GitStoreError {
  code = 'ENOENT';
  constructor(path: string) {
    super(`File not found: ${path}`);
    this.name = 'FileNotFoundError';
  }
}

export class IsADirectoryError extends GitStoreError {
  code = 'EISDIR';
  constructor(path: string) {
    super(`Is a directory: ${path}`);
    this.name = 'IsADirectoryError';
  }
}

export class NotADirectoryError extends GitStoreError {
  code = 'ENOTDIR';
  constructor(path: string) {
    super(`Not a directory: ${path}`);
    this.name = 'NotADirectoryError';
  }
}

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

export interface WalkEntry {
  name: string;
  oid: string;
  mode: string;
}

export function walkEntryFileType(entry: WalkEntry): FileType {
  return fileTypeFromMode(entry.mode);
}

export interface WriteEntry {
  /** Raw data (bytes), text (string), or local file path to read. */
  data?: Uint8Array | string;
  /** Git filemode override (e.g. FileType.EXECUTABLE). */
  mode?: FileType | string;
  /** Symlink target (mutually exclusive with data). */
  target?: string;
}

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

export interface FileEntry {
  path: string;
  type: FileType;
  src?: string;
}

export function fileEntryFromMode(path: string, mode: string, src?: string): FileEntry {
  return { path, type: fileTypeFromMode(mode), src };
}

export interface ChangeAction {
  path: string;
  action: 'add' | 'update' | 'delete';
}

export interface ChangeError {
  path: string;
  error: string;
}

export interface ChangeReport {
  add: FileEntry[];
  update: FileEntry[];
  delete: FileEntry[];
  errors: ChangeError[];
  warnings: ChangeError[];
}

export function emptyChangeReport(): ChangeReport {
  return { add: [], update: [], delete: [], errors: [], warnings: [] };
}

export function changeReportInSync(cr: ChangeReport): boolean {
  return cr.add.length === 0 && cr.update.length === 0 && cr.delete.length === 0;
}

export function changeReportTotal(cr: ChangeReport): number {
  return cr.add.length + cr.update.length + cr.delete.length;
}

export function changeReportActions(cr: ChangeReport): ChangeAction[] {
  const result: ChangeAction[] = [];
  for (const e of cr.add) result.push({ path: e.path, action: 'add' });
  for (const e of cr.update) result.push({ path: e.path, action: 'update' });
  for (const e of cr.delete) result.push({ path: e.path, action: 'delete' });
  result.sort((a, b) => a.path.localeCompare(b.path));
  return result;
}

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

export interface RefChange {
  ref: string;
  srcSha?: string;
  destSha?: string;
}

export interface MirrorDiff {
  create: RefChange[];
  update: RefChange[];
  delete: RefChange[];
}

export function mirrorDiffInSync(md: MirrorDiff): boolean {
  return md.create.length === 0 && md.update.length === 0 && md.delete.length === 0;
}

export function mirrorDiffTotal(md: MirrorDiff): number {
  return md.create.length + md.update.length + md.delete.length;
}

// ---------------------------------------------------------------------------
// Reflog
// ---------------------------------------------------------------------------

export interface ReflogEntry {
  oldSha: string;
  newSha: string;
  committer: string;
  timestamp: number;
  message: string;
}

// ---------------------------------------------------------------------------
// FS module interface (Node.js fs compatible)
// ---------------------------------------------------------------------------

/**
 * The filesystem interface expected by gitstore.
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

export interface HttpClient {
  request: Function;
}

/** Author/committer identity. */
export interface Signature {
  name: string;
  email: string;
}

export interface CommitInfo {
  message: string;
  time: Date;
  authorName: string;
  authorEmail: string;
}
