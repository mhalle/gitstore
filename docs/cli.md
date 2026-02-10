# CLI Reference

## Setup

Set the repository once per shell session:

```bash
export GITSTORE_REPO=/path/to/repo.git
```

Or pass `--repo`/`-r` per command. Use `--branch`/`-b` to target a branch (default: `main`).

Pass `-v` before any command for status messages on stderr.

### init

Create a new bare git repository.

```bash
gitstore init                    # or --repo <path>
gitstore init --branch dev
gitstore init -f                 # destroy and recreate
```

| Option | Description |
|--------|-------------|
| `--branch`, `-b` | Initial branch (default: `main`). |
| `-f`, `--force` | Destroy existing repo and recreate. |

### destroy

Remove a bare git repository.

```bash
gitstore destroy                 # fails if repo has data
gitstore destroy -f              # force
```

---

## Everyday Commands

### cp

Copy files and directories between disk and repo. The last argument is the destination; all preceding arguments are sources. Prefix repo-side paths with `:`.

```bash
# Disk to repo
gitstore cp file.txt :                        # keep name at repo root
gitstore cp file.txt :dest/file.txt           # explicit dest
gitstore cp f1.txt f2.txt :dir                # multiple files
gitstore cp ./mydir :dest                     # directory (name preserved)
gitstore cp ./mydir/ :dest                    # contents mode (trailing /)
gitstore cp './src/*.py' :backup              # glob

# Pivot (/./): preserve partial source path
gitstore cp /data/./logs/app :backup          # → backup/logs/app/...
gitstore cp /data/./logs/app/ :backup         # → backup/logs/...
gitstore cp /home/user/./projects/f.txt :bak  # → bak/projects/f.txt

# Repo to disk
gitstore cp :file.txt ./local.txt
gitstore cp ':docs/*.md' ./local-docs

# Options
gitstore cp -n ./mydir :dest                  # dry run
gitstore cp --delete ./src/ :code             # remove extra repo files
gitstore cp --ref v1.0 :data ./local          # from tag/branch/hash
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref` | Branch, tag, or commit hash to read from. |
| `--path` | Latest commit that changed this path. |
| `--match` | Latest commit matching message pattern (`*`, `?`). |
| `--before` | Latest commit on or before this date (ISO 8601). |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `--mode` | `644` (default) or `755`. |
| `--follow-symlinks` | Dereference symlinks (disk→repo only). |
| `-n`, `--dry-run` | Preview without writing. |
| `--ignore-existing` | Skip existing destination files. |
| `--delete` | Delete dest files not in source (rsync `--delete`). |
| `--ignore-errors` | Skip failed files and continue. |
| `--no-create` | Don't auto-create the repo. |

#### Copy behavior

| Source | Result at `:dest` |
|--------|-------------------|
| `file.txt` | `dest/file.txt` |
| `dir` | `dest/dir/...` (name preserved) |
| `dir/` | `dest/...` (contents poured, including dotfiles) |
| `'dir/*'` | `dest/a.txt ...` (glob, no dotfiles) |
| `/base/./sub/dir` | `dest/sub/dir/...` (pivot) |
| `/base/./sub/dir/` | `dest/sub/...` (pivot + contents) |

#### /./  pivot

An embedded `/./` in a source path (rsync `-R` style) splits the path into a locator and a preserved suffix. Everything before `/./` locates files on disk; everything after becomes the destination-relative path.

A leading `./` (e.g. `./mydir`) is a normal relative path and does **not** trigger pivot mode.

### sync

Make one path identical to another (like rsync `--delete`).

```bash
gitstore sync ./dir                           # sync dir to repo root
gitstore sync ./local :repo_path              # disk → repo
gitstore sync :repo_path ./local              # repo → disk
gitstore sync -n ./local :repo_path           # dry run
gitstore sync :data ./local --ref v1.0        # from tag
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref` | Branch, tag, or commit hash. |
| `--path` | Latest commit that changed this path. |
| `--match` | Latest commit matching message pattern. |
| `--before` | Latest commit on or before this date. |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `-n`, `--dry-run` | Preview without writing. |
| `--ignore-errors` | Skip failed files. |
| `--no-create` | Don't auto-create the repo. |

### ls

List files and directories. Accepts multiple paths and glob patterns — results are coalesced and deduplicated.

```bash
gitstore ls                                   # root
gitstore ls subdir                            # subdirectory
gitstore ls --ref v1.0                        # at a tag
gitstore ls '*.txt'                           # glob (quote to avoid shell expansion)
gitstore ls 'src/*.py'                        # glob in subdirectory
gitstore ls '*.txt' '*.py'                    # multiple globs
gitstore ls :src :docs                        # multiple directories
gitstore ls -R                                # all files recursively
gitstore ls -R :src :docs                     # recursive under multiple dirs
gitstore ls -R 'src/*'                        # glob + recursive expansion
```

| Option | Description |
|--------|-------------|
| `-R`, `--recursive` | List all files recursively with full paths. |
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before` | Snapshot filters. |

### cat

Print file contents to stdout.

```bash
gitstore cat file.txt
gitstore cat file.txt --ref v1.0
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before` | Snapshot filters. |

### rm

Remove a file from the repo.

```bash
gitstore rm old-file.txt
gitstore rm old-file.txt -m "Clean up"
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `-m`, `--message` | Commit message. |

---

## History

### log

Show commit history.

```bash
gitstore log
gitstore log --path file.txt
gitstore log --match "deploy*"
gitstore log --before 2024-06-01
gitstore log --format json                    # or jsonl
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref` | Start from branch, tag, or hash. |
| `--path` | Commits that changed this path. |
| `--match` | Commits matching message pattern. |
| `--before` | Commits on or before this date. |
| `--format` | `text` (default), `json`, `jsonl`. |

Text format: `SHORT_HASH  ISO_TIMESTAMP  MESSAGE`

### undo

```bash
gitstore undo                                 # back 1 commit
gitstore undo 3                               # back 3 commits
```

### redo

```bash
gitstore redo                                 # forward 1 reflog step
gitstore redo 2                               # forward 2 steps
```

### reflog

```bash
gitstore reflog
gitstore reflog --format json
```

---

## Refs

### branch

```bash
gitstore branch                               # list
gitstore branch list                          # same
gitstore branch create dev                    # empty orphan
gitstore branch create dev --from main        # fork
gitstore branch create dev --from main --path config.json
gitstore branch delete dev
gitstore branch hash main                     # tip commit SHA
gitstore branch hash main --back 3            # 3 commits before tip
gitstore branch hash main --path config.json  # last commit that changed file
```

#### branch create options

| Option | Description |
|--------|-------------|
| `--from` | Ref to fork from. Without it, creates empty orphan. |
| `--path`, `--match`, `--before` | Snapshot filters (require `--from`). |

#### branch hash options

| Option | Description |
|--------|-------------|
| `--back N` | Walk back N parents (default: 0 = tip). |
| `--path`, `--match`, `--before` | Snapshot filters. |

### tag

```bash
gitstore tag                                  # list
gitstore tag list                             # same
gitstore tag create v1.0 --from main          # required --from
gitstore tag create v1.0 --from main --before 2024-06-01
gitstore tag delete v1.0
gitstore tag hash v1.0                        # commit SHA
```

#### tag create options

| Option | Description |
|--------|-------------|
| `--from` | Ref to tag (required). |
| `--path`, `--match`, `--before` | Snapshot filters. |

---

## Archives

### archive / unarchive

Format auto-detected from extension (`.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`).

```bash
gitstore archive out.zip
gitstore archive out.tar.gz
gitstore archive - --format tar | gzip > a.tar.gz   # stdout
gitstore unarchive data.zip
gitstore unarchive data.tar.gz
gitstore unarchive --format tar < archive.tar        # stdin
```

#### archive options

| Option | Description |
|--------|-------------|
| `--format` | `zip` or `tar` (overrides auto-detect; required for stdout). |
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before` | Snapshot filters. |

#### unarchive options

| Option | Description |
|--------|-------------|
| `--format` | `zip` or `tar` (overrides auto-detect; required for stdin). |
| `-b`, `--branch` | Branch (default: `main`). |
| `-m`, `--message` | Commit message. |
| `--no-create` | Don't auto-create the repo. |

### zip / unzip / tar / untar

Aliases with a fixed format. Same options as archive/unarchive.

```bash
gitstore zip out.zip                          # = archive --format zip
gitstore unzip data.zip                       # = unarchive --format zip
gitstore tar out.tar.gz                       # = archive --format tar
gitstore untar data.tar.gz                    # = unarchive --format tar
```

---

## Mirror

### backup

Push all refs to a remote URL, creating an exact mirror. Remote-only refs are deleted.

```bash
gitstore backup https://github.com/user/repo.git
gitstore backup /path/to/other.git
gitstore backup -n https://github.com/user/repo.git   # dry run
```

### restore

Fetch all refs from a remote URL, overwriting local state. Local-only refs are deleted.

```bash
gitstore restore https://github.com/user/repo.git
gitstore restore -n https://github.com/user/repo.git  # dry run
```

| Option | Description |
|--------|-------------|
| `-n`, `--dry-run` | Preview without transferring data. |
| `--no-create` | Don't auto-create the repo (restore only). |

---

## Appendix

### The `:` prefix

For `cp` and `sync`, prefix repo-side paths with `:` to distinguish them from local paths. For other commands (`ls`, `cat`, `rm`) the `:` is optional.

### Snapshot filters

Several commands accept filters to select a specific commit:

| Option | Description |
|--------|-------------|
| `--ref REF` | Branch, tag, or commit hash. |
| `--path PATH` | Latest commit that changed this file. |
| `--match PATTERN` | Latest commit matching message pattern (`*`, `?`). |
| `--before DATE` | Latest commit on or before this date (ISO 8601). |

Filters combine with AND. Available on `cp`, `sync`, `ls`, `cat`, `log`, `branch create`, `branch hash`, `tag create`, `archive`, `zip`, `tar`.

### Dry-run output format

```
+ :path/to/new-file       (add)
~ :path/to/changed-file   (update)
- :path/to/removed-file   (delete)
```

### Message placeholders

The `-m` option accepts placeholders that expand at commit time:

| Placeholder | Expands to |
|-------------|------------|
| `{default}` | Full auto-generated message. |
| `{add_count}` | Number of additions. |
| `{update_count}` | Number of updates. |
| `{delete_count}` | Number of deletions. |
| `{total_count}` | Total changed files. |
| `{op}` | Operation name (`cp`, `ar`, or empty). |

```bash
gitstore cp dir/ :dest -m "Deploy: {default}"
gitstore sync ./src :code -m "Sync {total_count} files"
```

A message without `{` is used as-is. Unknown placeholders raise an error.

### Copy behavior table

| Source | Result at `:dest` |
|--------|-------------------|
| `file.txt` | `dest/file.txt` |
| `dir` | `dest/dir/...` (name preserved) |
| `dir/` | `dest/...` (contents, including dotfiles) |
| `'dir/*'` | `dest/matched...` (glob, no dotfiles) |
| `/base/./sub/dir` | `dest/sub/dir/...` (pivot) |
| `/base/./sub/dir/` | `dest/sub/...` (pivot + contents) |

---

See also: [Python API Reference](api.md) | [README](../README.md)
