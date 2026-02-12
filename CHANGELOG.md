# Changelog

All notable changes to gitstore are documented in this file.

## Unreleased

## v0.50.1 (2026-02-12)

**Bug fixes:**

- Fix single-file `cp` disk→repo silently dereferencing symlinks — now preserves symlinks unless `--follow-symlinks` is set
- Fix single-file `cp` repo→disk failing with `FileExistsError` when destination already exists (symlink or regular file)
- Fix `copy_from_repo(..., ignore_errors=True)` not raising `RuntimeError` when all write-phase operations fail, despite the documented contract
- Fix `undo()` / `redo()` accepting 0 and negative steps, which produced no-op reflog mutations

## v0.50.0 (2026-02-12)

**Breaking changes:**

- Rename public API for clarity and consistency:
  - `FS.hash` → `FS.commit_hash`
  - `FS.report` → `FS.changes` (returns `ChangeReport | None`)
  - `FS.dump()` → `FS.export_tree()`
  - `FS.write_from()` → `FS.write_from_file()`
  - `CopyReport` → `ChangeReport`, `CopyAction` → `ChangeAction`, `CopyError` → `ChangeError`
  - `SyncDiff` → `MirrorDiff`
  - `remove_from_repo()` → `remove_in_repo()` (param `patterns` → `sources`)
  - `move_from_repo()` → `move_in_repo()`
- CLI is now an optional dependency — `pip install gitstore` installs the core library only (`dulwich`); `pip install gitstore[cli]` adds `click` and `watchfiles`

**New features:**

- Add `read_text()` and `write_text()` convenience methods to `FS` and `Batch`
- Add `WalkEntry` named tuple with `name`, `oid`, `filemode` fields and `file_type` property — returned by `FS.walk()` file entries
- Add `ObjectSizer` for efficient blob size queries without full object reads
- Add `FileType` enum (`BLOB`, `EXECUTABLE`, `LINK`, `TREE`) — unifies file type representation across the API
- Add `branch exists` and `tag exists` CLI subcommands

**Improvements:**

- Consolidate `branch` and `tag` CLI into single `set` commands (replaces `fork`/`set` split)
- `FileEntry.file_type` now uses `FileType` enum instead of single-character strings

**Documentation:**

- Rewrite `docs/api.md` to match current v0.50 API (all names, signatures, data types)
- Rewrite `README.md` — updated API examples, trimmed CLI section, added new features
- Update `docs/cli.md` install instructions for `gitstore[cli]`

## v0.49.1 (2026-02-12)

**Internal:**

- Extract `_resolve_same_branch()` helper — shared by `rm` and `mv` for cross-branch validation
- Extract `_copy_blob_to_batch()` helper — shared by `mv` and repo-to-repo `cp`
- Fix bug in `rm` cross-branch detection that compared against the default branch instead of tracking the first explicit ref

## v0.49.0 (2026-02-12)

**Features:**

- `mv` command — move/rename files within a branch in one atomic commit
  - POSIX mv semantics: single-file rename, directory rename, multi-source move into directory
  - Supports globs, `-R` for directories, `-n` dry run, `ref:path` syntax
  - Same-branch only — cross-branch moves are rejected with a clear error

## v0.48.0 (2026-02-12)

**Features:**

- `ref:path` syntax for cross-branch CLI operations — `main:file.txt`, `dev:data/`, `v1.0:config.json`
- Ancestor syntax `ref~N:path` to read from historical commits (e.g., `main~3:file.txt`)
- Repo-to-repo `cp` and `sync` — copy files between branches without touching disk
- Per-path ref resolution in `ls` and `cat` — list/read from multiple branches in one command
- `write` and `rm` accept explicit `ref:path` to target a specific branch
- `log` and `diff` accept positional `ref:path` target (e.g., `gitstore log main~3:config.json`)
- Snapshot filters (`--back`, `--before`, `--path`, `--match`) work with explicit `ref:path`
- Ref name validation — branch/tag names containing `:`, space, tab, or newline are rejected

**Documentation:**

- New `docs/paths.md` — comprehensive path syntax reference covering parsing rules, per-command behavior, flag interaction, writability, and cross-branch workflows

## v0.47.8 (2026-02-11)

**Improvements:**

- Sync operations now use `Batch sync:` commit message prefix instead of `Batch cp:`

## v0.47.7 (2026-02-11)

**Documentation:**

- Document `gc` subcommand in README and CLI reference

## v0.47.6 (2026-02-11)

**Security:**

- Fix XSS in `serve` HTML output — escape display text and percent-encode/attribute-escape href values

**Bug fixes:**

- Reject scp-style SSH URLs (`git@host:path`, `host:path`) in mirror operations with a clear error suggesting `ssh://` format
- Guard `redo()` against zero-SHA reflog entries at branch creation point
- `glob()` now returns sorted results (was unordered); docstring updated to match

**New features:**

- Add `gc` subcommand — runs `git gc` to prune unreachable objects (orphaned blobs, etc.); requires git on PATH

## v0.47.5 (2026-02-11)

**Improvements:**

- Add `Cache-Control: no-cache` and 304 Not Modified support — browsers always revalidate via ETag and skip re-downloading unchanged content

## v0.47.4 (2026-02-11)

**Improvements:**

- `serve` now resolves snapshots live on each request — branches, `--back`, `--before`, `--path`, and `--match` all track the moving branch tip instead of pinning at startup

## v0.47.3 (2026-02-11)

**Improvements:**

- Add `--version` flag to CLI
- Document `serve` command in `docs/cli.md` and `README.md`

## v0.47.2 (2026-02-11)

**New features:**

- `--cors` flag adds permissive CORS headers (`Access-Control-Allow-Origin: *`) to all responses
- `--no-cache` flag sends `Cache-Control: no-store` on every response
- `--base-path` mounts the server under a URL prefix (e.g. `/data`)
- `--open` opens the URL in the default browser on start
- `--quiet` / `-q` suppresses per-request log output

**Tests:**

- Add 17 tests: CORS middleware (6), no-cache middleware (5), base-path middleware (7), CLI help assertions for new flags (4 new checks)

## v0.47.1 (2026-02-11)

**Bug fixes:**

- Fix HTML directory links in single-ref mode — no longer prefixed with the ref name
- Serve JSON, XML, GeoJSON, YAML as text so browsers display inline instead of downloading
- Register `.geojson` extension with Python's `mimetypes` module

**Improvements:**

- Add `ETag` header (commit hash) to all 200 responses

**Tests:**

- Add 14 tests: link correctness (single-ref and multi-ref), ETag presence/correctness, MIME overrides for JSON/XML/GeoJSON

## v0.47.0 (2026-02-11)

**New features:**

- Add `gitstore serve` command — HTTP file server for repo contents using stdlib `wsgiref`
- Content negotiation: `Accept: application/json` returns JSON metadata, otherwise raw bytes with MIME types or HTML directory listings
- Default: single-ref mode on HEAD branch, with shared `--branch`/`--ref`/`--back`/`--before`/`--match`/`--path` snapshot options
- `--all` flag enables multi-ref mode exposing all branches and tags via `/<ref>/<path>`

**Tests:**

- Add 27 tests for `serve` WSGI app covering single-ref mode, multi-ref mode, content negotiation, 404s, symlinks, MIME types, and CLI registration

## v0.46.0 (2026-02-11)

**New features:**

- Add `--exclude PATTERN` option to `cp` and `sync` — gitignore-style pattern matching, repeatable (disk→repo only)
- Add `--exclude-from FILE` option to `cp` and `sync` — read exclude patterns from a file (disk→repo only)
- Add `--gitignore` flag to `sync` — auto-reads `.gitignore` files from source tree with nested directory scoping; `.gitignore` files themselves are excluded (disk→repo only)
- New `ExcludeFilter` class in public API (`gitstore.copy.ExcludeFilter`) using `dulwich.ignore.IgnoreFilter`

**Tests:**

- Add 30 tests: 17 unit tests for `ExcludeFilter` and `_walk_local_paths` integration, 13 CLI tests for exclude/gitignore options

**Docs:**

- Document `--exclude`, `--exclude-from`, `--gitignore` options in CLI reference
- Add "Exclude patterns" section explaining gitignore syntax

## v0.45.0 (2026-02-11)

**New features:**

- Add `--watch` flag to `sync` command — continuously monitors a local directory for filesystem changes and auto-syncs to repo after a debounce delay (default 2s); uses `watchfiles` (Rust-based FSEvents/inotify); install via `pip install gitstore[watch]`
- Add `--debounce` option to `sync --watch` — configurable debounce delay in milliseconds (minimum 100ms)

**Tests:**

- Add 16 tests for watch mode: unit tests for import fallback, summary formatting, sync cycles, error recovery; CLI validation tests for incompatible flag combos

**Docs:**

- Document `--watch` and `--debounce` options in CLI reference

## v0.44.1 (2026-02-11)

**Bug fixes:**

- Fix inflated update counts in commit messages — `_build_report_from_changes` now compares new blob OID and filemode against the existing entry, so unchanged files are excluded from the report (e.g. re-importing 7 files with 1 changed now says `~ b.txt` instead of `~7`)

## v0.44.0 (2026-02-11)

**Bug fixes:**

- Fix TOCTOU race in `undo()`/`redo()` — stale check + ref update now run atomically under a single `repo_lock`, matching `_commit_changes`
- Fix `dump()` O(n^2) performance — filemodes are now read from tree entries during the walk instead of re-traversing from root per file
- Fix hardcoded reflog committer identity — reflog entries now use the actual `author`/`email` configured via `GitStore.open()` instead of `gitstore <gitstore@localhost>`
- Remove misleading `skipped` counter from zip import path (was always 0)
- Remove redundant local imports in `fs.py` and `repo.py`

**Tests:**

- Add 16 CLI tests: `TestUndo`, `TestRedo`, `TestReflogCLI`, `TestSnapshotFilterCombined`

**Docs:**

- Document `gitserve` command in CLI reference

## v0.43.1 (2026-02-11)

**Docs:**

- Document `diff` command in README and CLI reference
- Add `diff` to snapshot filters appendix

## v0.43.0 (2026-02-11)

**New features:**

- Add `diff` CLI command — compare HEAD against a baseline snapshot with git-style `A`/`M`/`D` output; supports all snapshot options (`--ref`, `--back`, `--before`, `--path`, `--match`) and `--reverse` to swap direction

## v0.42.0 (2026-02-11)

**New features:**

- Add `--passthrough`/`-p` flag to `write` CLI command — tee mode that echoes stdin to stdout for pipeline use (`cmd | gitstore write log.txt -p | grep error`)
- Add `retry_write()` library function — writes a single file to a branch with automatic retry on concurrent modification (exponential backoff + jitter, 5 attempts by default)
- `write` command now uses two-stage open: reads stdin before fetching the branch FS, minimizing the staleness window for long-running pipes

**Docs:**

- Fix `--hash` → `--ref` throughout README (matching actual CLI option name)
- Fix `branch` docs: document `fork`, `set`, `default` subcommands (replacing outdated `create --from` syntax)
- Fix `tag` docs: document `fork`, `set`, `hash` subcommands (replacing outdated `create` syntax)
- Add `--back` to all command option tables and Snapshot Filters appendix
- Add `-R/--recursive` and `-n/--dry-run` to `rm` options table
- Add `-b/--branch` to `undo`/`redo` docs; add options table for `reflog`
- Document `retry_write()` in API reference
- Document `--no-create` for `restore` in README

## v0.41.1 (2026-02-11)

**Internal:**

- Factor out all repeated CLI options into shared decorators in `_helpers.py`: `_branch_option`, `_message_option`, `_dry_run_option`, `_checksum_option`, `_ignore_errors_option`, `_format_option`, `_archive_format_option`
- Switch `branch set`, `tag set`, and `branch hash` to use `_snapshot_options` (adds `--back` support for free)
- No user-facing behavior changes

## v0.41.0 (2026-02-11)

**New features:**

- Add `branch default` subcommand — show or set the repo's default branch (`gitstore branch default`, `gitstore branch default -b dev`)
- HEAD is now set at repo creation to match the initial branch, fixing `git clone` and tools that read HEAD
- All CLI `--branch/-b` and `--ref` options now default to the repo's HEAD branch instead of hardcoded "main"

**Internal:**

- Add `get_head_branch()` / `set_head_branch()` helpers to `_compat.py` Repository
- Add `_default_branch()` CLI helper for HEAD-based branch resolution
- Simplify `_fix_head` in `_serve.py` to use new `_compat` helpers

## v0.40.1 (2026-02-11)

- `FS.back()` now defaults to `n=1`, matching `undo()`

## v0.40.0 (2026-02-11)

**New features:**

- Add `--back N` option to all read-oriented CLI commands (`ls`, `cat`, `log`, `cp`, `sync`, `zip`, `tar`, `archive`) — walk back N commits from HEAD before reading
- Add `FS.back(n)` API method — return the FS at the nth ancestor commit

**Internal:**

- Add `_resolve_fs()` CLI helper — consolidates branch/ref + snapshot filter + `--back` resolution into a single call
- Refactor `branch hash --back` to use `FS.back()` instead of inline loop
- Drop deprecated `--at` option from `zip` and `tar` commands

## v0.39.1 (2026-02-10)

**Enhancements:**

- `cat` now accepts multiple paths and concatenates their output

## v0.39.0 (2026-02-10)

**Breaking changes:**

- `branch create` no longer accepts `--from` or snapshot filters — it only creates empty branches
- `tag create` renamed to `tag fork`; `--from` renamed to `--ref` (defaults to `main`)

**New features:**

- Add `branch fork NAME` — create a new branch from an existing ref (`--ref` defaults to `main`, `-f`/`--force` to overwrite)
- Add `branch set NAME --ref REF` — point a branch at an existing ref (creates or updates)
- Add `tag fork NAME` — create a new tag from an existing ref (`--ref` defaults to `main`)
- Add `tag set NAME --ref REF` — point a tag at an existing ref (creates or updates)

## v0.38.1 (2026-02-10)

**Performance:**

- Pass tree OIDs down `_iglob_walk` recursion — each directory is now read directly via `repo[oid]` instead of re-walking from root
- Avoid double directory reads for `**` + rest patterns (e.g. `**/*.py`)
- Drop sorting from CLI `ls` output

**Cleanup:**

- Remove dead `_ls_typed` method (no longer called after iglob refactor)

## v0.38.0 (2026-02-10)

**New features:**

- Add `fs.iglob(pattern)` — streaming generator that yields unique matches without sorting or materializing the full list

**Performance:**

- Convert internal `_glob_walk` (list-builder) to `_iglob_walk` (generator) — eliminates intermediate list allocations at every recursion level
- `glob()` no longer sorts results; use `sorted(fs.glob(...))` if order matters
- CLI `ls` uses `iglob()` for streaming dedup

## v0.37.1 (2026-02-10)

**Bug fixes:**

- Pivot + trailing slash on file now raises `NotADirectoryError` — `base/./file.txt/` no longer silently treats a file as `mode="file"`, matching non-pivot behavior
- Normalize path separators for pivot detection on Windows — `base\.\sub\file` is now found correctly without mangling `\\?\` extended-length paths or literal backslashes in POSIX repo entries

**Performance:**

- Avoid quadratic `is_dir` calls in `**` glob — new `_ls_typed()` method reads the tree once per directory instead of N separate `_entry_at_path` lookups

**Documentation:**

- Document that glob patterns after `/./` pivot are unsupported (matches rsync behavior)

**Tests:**

- Add 6 tests for pivot edge cases: trailing-slash error, backslash normalization, glob-after-pivot (both disk→repo and repo→disk)

## v0.37.0 (2026-02-10)

**New features:**

- Add `**` glob support — `fs.glob("**/*.py")` matches files at any depth, skipping dot-named entries (consistent with `*`)
- Add `/./` pivot for repo→disk copies — `cp :src/./lib/utils.py ./dest` → `dest/lib/utils.py`; mirrors the existing disk→repo pivot

**Cleanup:**

- Remove dead `_parse_repo_path` helper from CLI

**Tests:**

- Add 9 tests for `**` glob: all, extension, prefix, middle, no-dotfiles, no-duplicates, empty-repo, at-root, sorted
- Add 6 tests for repo-side `/./` pivot: directory, contents, file, leading-dot-slash, dry-run, not-found
- Add 2 CLI tests for repo-side pivot

## v0.36.0 (2026-02-10)

**New features:**

- Add `--tag` and `--force-tag` options to all write commands (`write`, `rm`, `cp`, `sync`, `unzip`, `untar`, `unarchive`) — create a tag at the resulting commit without a separate `tag create` step
- `--tag` on repo→disk `cp`/`sync` is rejected with a clear error

**Tests:**

- Add 9 tests for `--tag`/`--force-tag`: write, rm, cp, sync, unzip, duplicate error, force overwrite, cp/sync repo→disk rejection

## v0.35.0 (2026-02-10)

**New features:**

- Default to mtime-based change detection for `cp --delete` and `sync` — skips hashing files whose mtime predates the commit timestamp (like rsync)
- Add `-c`/`--checksum` flag to `cp` and `sync` for exact SHA-1 comparison when needed (backdated mtime, archive extraction, etc.)

**Tests:**

- Add 6 tests for mtime vs checksum mode: unchanged skip, new mtime detection, cp --delete, backdated mtime tradeoff, dry-run/real-run agreement

## v0.34.0 (2026-02-10)

**New features:**

- Add rsync-style `/./` pivot marker for `cp` source paths — controls which part of the source path is preserved at the destination
  - `cp /data/./logs/app :backup` → `backup/logs/app/...`
  - `cp /data/./logs/app/ :backup` → `backup/logs/...` (contents mode)
  - Leading `./` (e.g. `./mydir`) does not trigger pivot mode

**Documentation:**

- Rewrite `docs/api.md` and `docs/cli.md` in terse, scannable man-page style
- Fix stale `create="main"` in `docs/index.md`

**Tests:**

- Add 6 tests for `/./` pivot: directory, contents, file, leading-dot-slash, not-found, dry-run

## v0.33.0 (2026-02-09)

**Breaking changes:**

- Simplify `GitStore.open()` API: `create` is now a plain `bool` (default `True`), `branch` defaults to `"main"`
  - Old: `GitStore.open(path, create="main")` / `GitStore.open(path, create=True, branch="main")`
  - New: `GitStore.open(path)` (creates with "main" branch if missing, opens if exists)
  - `create=False` raises `FileNotFoundError` when the repo is missing
  - `branch=None` creates a bare repo with no branches
  - `open()` is now idempotent — no more `FileExistsError`

## v0.32.0 (2026-02-09)

**Documentation:**

- Expand `gitstore --help` with quick-start examples, grouped command reference, and usage tips

## v0.31.0 (2026-02-09)

**New features:**

- Add `branch hash NAME` command — prints the 40-char commit SHA for a branch, with `--back`, `--path`, `--match`, `--before` filters
- Add `tag hash NAME` command — prints the 40-char commit SHA for a tag

**Tests:**

- Add 7 tests for `branch hash` and `tag hash` commands

## v0.30.0 (2026-02-09)

**New features:**

- Add message template placeholders for `--message` / `-m` flag
  - `{default}` — full auto-generated message
  - `{add_count}`, `{update_count}`, `{delete_count}`, `{total_count}` — file counts
  - `{op}` — operation name (`cp`, `ar`, or empty)
  - Example: `--message "Deploy v2: {default}"` → `Deploy v2: Batch cp: +3 ~1`
  - Messages without `{` are returned as-is (backward compatible)
- Add `--message` long flag (previously `-m` only) to `cp`, `sync`, `rm`, `unzip`, `untar`, `unarchive`

**Breaking changes:**

- `tag create` now uses `--from` option instead of positional `FROM` argument (consistent with `branch create`)
- Rename `--hash` to `--ref` on all read commands (`cp`, `sync`, `ls`, `cat`, `log`, `archive`, `zip`, `tar`)

**Documentation:**

- Document message placeholders in CLI and API docs

**Tests:**

- Add 13 tests for `format_commit_message` placeholder substitution

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
