# CLI Reference

gitstore includes a command-line interface for working with bare repos without writing Python. Install the package to get the `gitstore` command.

## Shared concepts

### Repository selection

Specify the repository with `--repo`/`-r` or the `GITSTORE_REPO` environment variable:

```bash
export GITSTORE_REPO=/path/to/repo.git
gitstore ls

# Or per-command
gitstore -r /path/to/repo.git ls
```

### Branch selection

Use `--branch`/`-b` to target a branch (defaults to `main`).

### The `:` prefix

For `cp` and `sync`, prefix repo-side paths with `:` to distinguish them from local paths. For other commands (`ls`, `cat`, `rm`) the `:` prefix is optional.

### Snapshot filters

Read commands support `--hash` to read from any branch, tag, or full commit hash. Several commands also support these filters to select a specific commit:

| Option | Description |
|--------|-------------|
| `--hash REF` | Branch, tag, or commit hash to read from. |
| `--path PATH` | Use the latest commit that changed this file. |
| `--match PATTERN` | Use the latest commit matching this message pattern (`*` and `?`). |
| `--before DATE` | Use the latest commit on or before this date (ISO 8601). |

Filters combine with AND. `--path`, `--match`, and `--before` are available on `cp`, `ls`, `cat`, `sync`, `log`, `branch create`, `tag create`, `archive`, `zip`, and `tar`.

### Dry-run output format

Commands that support `-n`/`--dry-run` show planned actions with prefixes:

```
+ :path/to/new-file       (add)
~ :path/to/changed-file   (update)
- :path/to/removed-file   (delete)
```

### Verbose mode

Pass `-v` before the command for status messages on stderr:

```bash
gitstore -v cp file.txt :file.txt
```

---

## Commands

### init

Create a new bare git repository.

```bash
gitstore init
gitstore init --branch dev
gitstore init -f              # destroy existing and recreate
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Initial branch name (default: `main`). |
| `-f`, `--force` | Destroy existing repo and recreate. |

### destroy

Remove a bare git repository.

```bash
gitstore destroy              # fails if repo has data
gitstore destroy -f           # force-remove non-empty repo
```

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Required to destroy a non-empty repo. |

### cp

Copy files and directories between disk and repo.

The last argument is the destination; all preceding arguments are sources. Sources must all be the same type (all repo or all local), and the destination must be the opposite type.

```bash
# Disk to repo
gitstore cp local-file.txt :remote-file.txt
gitstore cp file.txt :                        # keep original name at root
gitstore cp file1.txt file2.txt :dir          # multiple sources
gitstore cp ./mydir :dest                     # directory (name preserved)
gitstore cp ./mydir/ :dest                    # contents of directory
gitstore cp './src/*.py' :backup              # glob pattern

# Repo to disk
gitstore cp :remote-file.txt local-copy.txt
gitstore cp :a.txt :b.txt ./local-dir
gitstore cp ':docs/*.md' ./local-docs         # repo-side glob

# Dry run
gitstore cp -n ./mydir :dest

# With snapshot filters
gitstore cp :file.txt local.txt --hash v1.0
gitstore cp :file.txt local.txt --path file.txt --before 2024-06-01
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to operate on (default: `main`). |
| `--hash` | Branch, tag, or commit hash to read from. |
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `--mode` | File mode: `644` (default) or `755`. |
| `--follow-symlinks` | Dereference symlinks (disk to repo only). |
| `-n`, `--dry-run` | Show what would be copied without writing. |
| `--ignore-existing` | Skip files that already exist at the destination. |
| `--delete` | Delete destination files not in source (like rsync `--delete`). |
| `--ignore-errors` | Skip failed files and continue. |
| `--no-create` | Do not auto-create the repository. |

#### Copy behavior

| Command | Result |
|---------|--------|
| `cp file.txt :dest` | `:dest` is the file (or `:dest/file.txt` if `:dest` is an existing directory) |
| `cp dir :dest` | `:dest/dir/...` (directory name preserved) |
| `cp dir/ :dest` | `:dest/...` (contents poured into dest, including dotfiles) |
| `cp 'dir/*' :dest` | `:dest/a.txt` etc. (glob-matched children, no dotfiles) |
| `cp f1 dir1 :dest` | `:dest/f1`, `:dest/dir1/...` (mixed sources) |

Glob patterns (`*`, `?`) do not match files or directories whose names start with `.`. Trailing `/` on a source means "contents of" and includes dotfiles.

### sync

Make one path identical to another (like rsync `--delete`).

```bash
# One argument: sync local directory to repo root
gitstore sync ./dir

# Two arguments: direction determined by ':'
gitstore sync ./local :repo_path     # disk to repo
gitstore sync :repo_path ./local     # repo to disk

# Dry run
gitstore sync -n ./local :repo_path

# With snapshot filters (repo to disk only)
gitstore sync :data ./local --hash v1.0
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to operate on (default: `main`). |
| `--hash` | Branch, tag, or commit hash to read from. |
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `-n`, `--dry-run` | Show what would change without writing. |
| `--ignore-errors` | Skip failed files and continue. |
| `--no-create` | Do not auto-create the repository. |

### ls

List files and directories.

```bash
gitstore ls                    # root listing
gitstore ls subdir             # subdirectory
gitstore ls --hash v1.0        # at a specific ref
gitstore ls --path file.txt    # at commit that last changed file.txt
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to list (default: `main`). |
| `--hash` | Branch, tag, or commit hash. |
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |

### cat

Print file contents to stdout.

```bash
gitstore cat file.txt
gitstore cat file.txt --hash v1.0
gitstore cat file.txt --path file.txt --before 2024-06-01
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to read from (default: `main`). |
| `--hash` | Branch, tag, or commit hash. |
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |

### rm

Remove a file from the repo.

```bash
gitstore rm old-file.txt
gitstore rm old-file.txt -m "Clean up"
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to remove from (default: `main`). |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |

### log

Show commit history.

```bash
gitstore log
gitstore log --path file.txt
gitstore log --match "deploy*"
gitstore log --path file.txt --match "fix*"
gitstore log --before 2024-06-01
gitstore log --before 2024-06-01T14:30:00
gitstore log --format json
gitstore log --format jsonl
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Branch to show log for (default: `main`). |
| `--hash` | Branch, tag, or commit hash to start from. |
| `--path` | Show only commits that changed this path. |
| `--match` | Show only commits matching this message pattern. |
| `--before` | Show only commits on or before this date. |
| `--format` | Output format: `text` (default), `json`, or `jsonl`. |

Text output format: `SHORT_HASH  ISO_TIMESTAMP  MESSAGE`

### branch

Manage branches.

```bash
# List
gitstore branch
gitstore branch list

# Create
gitstore branch create dev
gitstore branch create dev --from main
gitstore branch create dev --from main --path config.json
gitstore branch create dev --from main --match "deploy*"
gitstore branch create dev --from main --before 2024-06-01

# Delete
gitstore branch delete dev
```

#### branch create

| Argument | Description |
|----------|-------------|
| `NAME` | Name of the new branch. |

| Option | Description |
|--------|-------------|
| `--from` | Ref to fork from. Without this, creates an empty orphan branch. |
| `--path` | Use latest commit that changed this path (requires `--from`). |
| `--match` | Use latest commit matching this message pattern (requires `--from`). |
| `--before` | Use latest commit on or before this date (requires `--from`). |

### tag

Manage tags.

```bash
# List
gitstore tag
gitstore tag list

# Create
gitstore tag create v1.0 main
gitstore tag create v1.0 main --path bugfix.py
gitstore tag create v1.0 main --match "deploy*"
gitstore tag create v1.0 main --before 2024-06-01

# Delete
gitstore tag delete v1.0
```

#### tag create

| Argument | Description |
|----------|-------------|
| `NAME` | Tag name. |
| `FROM` | Ref to tag (branch, tag, or commit hash). |

| Option | Description |
|--------|-------------|
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |

### archive / unarchive

Export or import an archive file. Format is auto-detected from the filename extension (`.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`).

```bash
# Export
gitstore archive archive.zip
gitstore archive archive.tar.gz
gitstore archive archive.tar --path file.txt
gitstore archive out.dat --format zip
gitstore archive - --format tar | gzip > a.tar.gz   # stdout

# Import
gitstore unarchive archive.zip
gitstore unarchive archive.tar.gz
gitstore unarchive data.bin --format tar
gitstore unarchive --format tar < archive.tar        # stdin
gitstore unarchive archive.zip -m "Import data" -b dev
```

#### archive options

| Option | Description |
|--------|-------------|
| `--format` | `zip` or `tar` (overrides auto-detection; required for stdout). |
| `--branch`, `-b` | Branch to export from (default: `main`). |
| `--hash` | Branch, tag, or commit hash. |
| `--path` | Use latest commit that changed this path. |
| `--match` | Use latest commit matching this message pattern. |
| `--before` | Use latest commit on or before this date. |

#### unarchive options

| Option | Description |
|--------|-------------|
| `--format` | `zip` or `tar` (overrides auto-detection; required for stdin). |
| `--branch`, `-b` | Branch to import into (default: `main`). |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `--no-create` | Do not auto-create the repository. |

### zip / unzip / tar / untar

Aliases for `archive` and `unarchive` with a fixed format:

```bash
gitstore zip archive.zip            # = archive archive.zip --format zip
gitstore unzip archive.zip          # = unarchive archive.zip --format zip
gitstore tar archive.tar.gz         # = archive archive.tar.gz --format tar
gitstore untar archive.tar.gz       # = unarchive archive.tar.gz --format tar
```

These accept the same options as `archive`/`unarchive`.

### backup

Push all refs to a remote URL, creating an exact mirror.

```bash
gitstore backup https://github.com/user/repo.git
gitstore backup git@github.com:user/repo.git
gitstore backup /path/to/other-bare-repo.git
gitstore backup -n https://github.com/user/repo.git   # preview
```

| Option | Description |
|--------|-------------|
| `-n`, `--dry-run` | Show what would change without transferring data. |

### restore

Fetch all refs from a remote URL, overwriting local state.

```bash
gitstore restore https://github.com/user/repo.git
gitstore restore -n https://github.com/user/repo.git   # preview
```

| Option | Description |
|--------|-------------|
| `-n`, `--dry-run` | Show what would change without transferring data. |
| `--no-create` | Do not auto-create the repository. |

### Message placeholders

The `-m` option accepts placeholders that expand at commit time:

| Placeholder | Expands to | Example |
|-------------|------------|---------|
| `{default}` | Full auto-generated message | `Batch cp: +3 ~1` |
| `{add_count}` | Number of added files | `3` |
| `{update_count}` | Number of updated files | `1` |
| `{delete_count}` | Number of deleted files | `0` |
| `{total_count}` | Total changed files | `4` |
| `{op}` | Operation name (`cp`, `ar`, or empty) | `cp` |

```bash
gitstore cp dir/ :dest -m "Deploy v2: {default}"       # Deploy v2: Batch cp: +3 ~1
gitstore sync ./src :code -m "Sync {total_count} files" # Sync 4 files
gitstore cp file.txt : -m "Release build"               # Release build (no placeholders)
```

A message without `{` is returned as-is (backward compatible). Unknown placeholders raise an error.

---

## See also

- [Python API Reference](api.md)
- [README](../README.md) -- concepts, concurrency, error handling
