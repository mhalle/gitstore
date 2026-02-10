# Changelog

All notable changes to gitstore are documented in this file.

## Unreleased

## v0.29.0 (2026-02-09)

**Bug fixes:**

- Preserve executable bit (0o755) when extracting files from repo via `copy_from_repo` and `fs.dump`
- Fix stale-snapshot check bypass when `_commit_changes` produces an identical tree (no-op write on a moved branch now raises `StaleSnapshotError`)
- Add stale-snapshot check to `fs.undo()` and `fs.redo()` to prevent overwriting concurrent branch updates
- Fix `sync_to_repo` delete-file path: report now shows the actual file path instead of `""`
- Fix file-to-directory conflicts in non-delete `copy_from_repo` (clear blocking parent files before `mkdir`)
- Detect mode-only changes (e.g. exec-bit flip) in delete-mode sync/copy, both directions
- Fix symlink mode regression: symlinks already in sync no longer reported as false updates
- Fix `follow_symlinks=True` in delete-mode copy: hash file content instead of link target to avoid perpetual updates
- Add base guard to path-clearing in `_write_files_to_disk` to prevent deleting files above the destination root

**Documentation:**

- Fix README comment claiming `write_from` avoids loading files into memory (dulwich requires full data for SHA-1)
- Add docstring to `create_blob_fromdisk` documenting memory limitation

**Tests:**

- Add 6 tests: symlink in-sync (4), follow_symlinks delete-mode (2)

## v0.28.0 (2026-02-09)

**New features:**

- Add undo/redo functionality with reflog support
  - `fs.undo(steps=1)` - Move branch back N commits
  - `fs.redo(steps=1)` - Move branch forward using reflog
  - `repo.branches.reflog(name)` - Read branch movement history
  - CLI commands: `gitstore undo`, `gitstore redo`, `gitstore reflog`
  - Reflog supports text, JSON, and JSONL output formats
- Add `repo.branches.set(name, fs)` method to solve chained assignment footgun
  - Returns writable FS bound to the branch (unlike bracket assignment)
  - Avoids confusion where `fs2 = repo.branches['x'] = fs1` leaves fs2 bound to old branch
- Document old snapshot semantics: readable bookmarks that can reset/create branches but cannot write

**Tests:**
- Add 22 comprehensive tests for undo/redo/reflog including edge cases
- Add 5 tests for `branches.set()` method

## v0.27.0 (2026-02-09)

**Breaking API change:** `copy_to_repo()` and `sync_to_repo()` now return just `FS` instead of `tuple[FS, CopyReport | None]`. Access the report via `fs.report` property.

- Add `FileEntry` dataclass with `path`, `type` (B/E/L), and `src` (source location) tracking
- `CopyReport` now uses `list[FileEntry]` instead of `list[str]` for add/update/delete operations
- Centralize commit message generation with `+/-/~` notation and operation prefixes (Batch cp:, Batch ar:)
- Add `FS.report` property to access operation report without tuple unpacking
- Fix `fs.report` to match tuple return value (both now reference same object with source tracking)
- **API simplification:** `copy_to_repo()` and `sync_to_repo()` return `FS` only; report via `fs.report`
- Export `FileEntry` from `gitstore` package
- Update documentation for new API

## v0.26.2 (2026-02-09)

- Allow `--repo` option at both main group level and subcommand level for flexibility

## v0.26.1 (2026-02-09)

- Auto-create destination repository when backing up to non-existent local path
- Fix help text for `cp` and `sync` commands to clarify `--repo` requirement
- Add test for backup auto-create behavior

## v0.26.0 (2026-02-09)

- Extract shared `_glob_match` into `_glob.py` (deduplicate from `fs.py` and `copy.py`)
- Split `copy.py` (1093 lines) into `copy/` subpackage: `_types`, `_resolve`, `_io`, `_ops`
- Split `cli.py` (1361 lines) into `cli/` subpackage: `_helpers`, `_basic`, `_cp`, `_sync`, `_refs`, `_archive`, `_mirror`
- Zero public API changes; all backward-compatible imports preserved

## v0.25.0 (2026-02-09)

- Unify `CopyPlan` and `list[CopyError]` into `CopyReport` dataclass with `add`, `update`, `delete`, `errors`, and `warnings` fields
- All copy/sync functions now return `CopyReport | None` (`None` when nothing to report)
- Overlap collisions reported as warnings instead of errors (CLI exits 0 for warnings-only)
- Fix `sync_to_repo_dry_run` file-at-dest producing wrong plan path
- Fix `copy_from_repo` delete mode using wrong source for hash comparison on overlapping destinations
- Fix contents-mode (`"symlink_dir/"`) silently producing zero pairs for symlinked directories
- Fix `copy_from_repo_dry_run` delete mode not deduplicating overlapping sources
- Update `docs/api.md` for new `CopyReport` API
- Backward-compatible aliases: `CopyPlan = CopyReport`, `SyncPlan = CopyReport`

## v0.24.0 (2026-02-09)

- Add `docs/` directory with API and CLI reference documentation
- Fix stale pygit2 references in README

## v0.23.0 (2026-02-09)

- Add `sync` CLI command for syncing files between disk and repo
- Add `--path`, `--match`, and `--before` filters to `ls`, `cat`, `cp`, and `sync`
- Add `ignore_errors` option to copy/sync operations
- Factor out backup/restore into dedicated `mirror.py` module
- Remove standalone `sync.py`; update `cptree` references to `cp`

## v0.22.0 (2026-02-09)

- Add `sync` module with optimized content-hash-based file synchronization
- Enhance `cp` with directory targets, trailing-slash semantics, glob patterns, and `--dry-run`

## v0.21.0 (2026-02-09)

- Auto-create repositories on write commands (no separate `init` step needed)

## v0.20.0 (2026-02-09)

- Move backup/restore logic from CLI into the GitStore API

## v0.19.0 (2026-02-08)

- Version bump only (consolidation release after v0.18.0)

## v0.18.0 (2026-02-08)

- Add `backup` and `restore` CLI commands for pushing/pulling to remote repos
- Add HTTPS credential support for remote operations

## v0.17.0 (2026-02-08)

- Migrate git backend from pygit2 to dulwich via a compatibility layer (`_compat.py`)
- Skip no-op commits when the tree is unchanged

## v0.16.0 (2026-02-08)

- Add `write_symlink()` and `readlink()` to FS and Batch APIs

## v0.15.0 (2026-02-08)

- Add `archive` and `unarchive` CLI commands
- Fix bug where `unzip` silently skipped files

## v0.14.0 (2026-02-08)

- Handle symlinks in `cp` and `cptree`
- Harden zip/tar import against malformed archives
- Document `write_from` in FS reference

## v0.13.0 (2026-02-08)

- Add `write_from()` for writing disk files directly into the store
- Add eager blob creation in Batch for `write_from()`
- CLI now uses the batch API for disk writes with normalized error handling
- Document `--match`/`--before` for branch/tag create and `git gc` maintenance

## v0.12.0 (2026-02-08)

- Unify snapshot resolution: remove internal `_resolve_with_at`
- Add `--match` and `--before` options to `branch create` and `tag create`

## v0.11.0 (2026-02-08)

- Add `--before` date filter to `log`, `zip`, and `tar` commands

## v0.10.0 (2026-02-08)

- Add `tar` and `untar` CLI commands
- Rename `--at` to `--path` (keep `--at` as hidden alias)
- Add `--hash` option to read commands for content-addressable lookups
- Extract shared CLI helpers (`_normalize_at_path`, `_resolve_snapshot`, `_commit_writes`)

## v0.9.0 (2026-02-08)

- Make `:` prefix optional for `ls`, `cat`, `rm`, and `--at` arguments

## v0.8.0 (2026-02-08)

- Change CLI from positional `REPO` argument to `--repo`/`-r` option
- Add `message` parameter to `batch()` for custom commit messages

## v0.7.0 (2026-02-08)

- Add `message` and `mode` keyword arguments to `fs.write()`

## v0.6.0 (2026-02-08)

- Keep CLI as a core dependency (reverted experiment with optional `gitstore[cli]` extra)

## v0.5.0 (2026-02-08)

- `branch create` now supports empty branches and `--from` to fork from an existing ref

## v0.4.0 (2026-02-08)

- Add `zip` and `unzip` CLI commands; preserve file permissions in round-trips
- Add `--at` and `--match` filters to `log` command
- Peel annotated tags to commits; validate `--at` paths
- Harden `rm` semantics across FS, Batch, and CLI
- Make CLI quiet by default

## v0.3.0 (2026-02-07)

- Support multiple sources in `cp` command
- Make bare `:` destination mean repo root (keep original filename)
- Add `--format json/jsonl` to `log` command
- Add `--mode 644/755` flag to `cp` command
- Drop auto-generated commit messages from write commands
- Default `init` to create a `main` branch

## v0.2.0 (2026-02-07)

- Add CLI with `cp`, `cptree`, `ls`, `cat`, `rm`, `log`, `branch`, and `tag` commands
- Add Apache 2.0 license
- Add commit metadata properties and path-filtered log
- Harden CLI input handling and exception reporting

## v0.1.0 (2026-02-07)

- Initial implementation of gitstore: git-backed file store with FS, Batch, and GitStore APIs
- Stale-snapshot detection, tag safety, binary mode strings
- Cross-repo refs, locking, `close()`, batch finality, Windows path normalization
- `src/` package layout with comprehensive README and test suite
