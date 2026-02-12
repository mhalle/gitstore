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

# Pivot (/./): preserve partial repo path
gitstore cp ':data/./logs/app' ./backup          # → backup/logs/app/...
gitstore cp ':data/./logs/app/' ./backup         # → backup/logs/...
gitstore cp ':src/./lib/utils.py' ./dest         # → dest/lib/utils.py

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
| `--back N` | Walk back N commits from tip. |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `--mode` | `644` (default) or `755`. |
| `--follow-symlinks` | Dereference symlinks (disk→repo only). |
| `-n`, `--dry-run` | Preview without writing. |
| `--ignore-existing` | Skip existing destination files. |
| `--delete` | Delete dest files not in source (rsync `--delete`). |
| `--exclude PATTERN` | Exclude files matching pattern (gitignore syntax, repeatable; disk→repo only). |
| `--exclude-from FILE` | Read exclude patterns from file (disk→repo only). |
| `--ignore-errors` | Skip failed files and continue. |
| `-c`, `--checksum` | Compare files by checksum instead of mtime (slower, exact). |
| `--no-create` | Don't auto-create the repo. |
| `--tag` | Create a tag at the resulting commit (disk→repo only). |
| `--force-tag` | Overwrite tag if it already exists. |

#### Copy behavior

| Source | Result at `:dest` |
|--------|-------------------|
| `file.txt` | `dest/file.txt` |
| `dir` | `dest/dir/...` (name preserved) |
| `dir/` | `dest/...` (contents poured, including dotfiles) |
| `'dir/*'` | `dest/a.txt ...` (glob, no dotfiles) |
| `'**/*.py'` | `dest/matched...` (recursive glob) |
| `/base/./sub/dir` | `dest/sub/dir/...` (pivot) |
| `/base/./sub/dir/` | `dest/sub/...` (pivot + contents) |

#### /./  pivot

An embedded `/./` in a source path (rsync `-R` style) splits the path into a locator and a preserved suffix. Everything before `/./` locates the source (on disk or in the repo); everything after becomes the destination-relative path. Works in both disk→repo and repo→disk directions.

A leading `./` (e.g. `./mydir`) is a normal relative path and does **not** trigger pivot mode.

Glob patterns (`*`, `?`, `**`) in the segment after `/./` are not supported — use them before the pivot or as separate sources.

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
| `--back N` | Walk back N commits from tip. |
| `-m`, `--message` | Commit message (supports [placeholders](#message-placeholders)). |
| `-n`, `--dry-run` | Preview without writing. |
| `--exclude PATTERN` | Exclude files matching pattern (gitignore syntax, repeatable; disk→repo only). |
| `--exclude-from FILE` | Read exclude patterns from file (disk→repo only). |
| `--gitignore` | Read `.gitignore` files from source tree (disk→repo only). |
| `--ignore-errors` | Skip failed files. |
| `-c`, `--checksum` | Compare files by checksum instead of mtime (slower, exact). |
| `--no-create` | Don't auto-create the repo. |
| `--tag` | Create a tag at the resulting commit (disk→repo only). |
| `--force-tag` | Overwrite tag if it already exists. |
| `--watch` | Watch for changes and sync continuously (disk→repo only). |
| `--debounce MS` | Debounce delay in ms for `--watch` (default: 2000). |

#### Watch mode

With `--watch`, continuously watches the local directory and syncs on changes:

```bash
gitstore sync --watch ./dir :data
gitstore sync --watch --debounce 5000 ./dir
gitstore sync --watch -c ./src :code       # checksum mode
```

Requires: `pip install gitstore[watch]`

### ls

List files and directories. Accepts multiple paths and glob patterns — results are coalesced and deduplicated.

```bash
gitstore ls                                   # root
gitstore ls subdir                            # subdirectory
gitstore ls --ref v1.0                        # at a tag
gitstore ls '*.txt'                           # glob (quote to avoid shell expansion)
gitstore ls 'src/*.py'                        # glob in subdirectory
gitstore ls '**/*.py'                         # ** matches all depths
gitstore ls 'src/**/*.txt'                    # ** under a prefix
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
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

### cat

Print file contents to stdout.

```bash
gitstore cat file.txt
gitstore cat file.txt --ref v1.0
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

### rm

Remove files from the repo. Accepts multiple paths and glob patterns. Directories require `-R`.

```bash
gitstore rm old-file.txt
gitstore rm old-file.txt -m "Clean up"
gitstore rm ':*.txt'                     # glob (quote for shell)
gitstore rm -R :dir                      # directory
gitstore rm -n :file.txt                 # dry run
gitstore rm :a.txt :b.txt               # multiple
```

| Option | Description |
|--------|-------------|
| `-R`, `--recursive` | Remove directories recursively. |
| `-n`, `--dry-run` | Show what would change without writing. |
| `-b`, `--branch` | Branch (default: `main`). |
| `-m`, `--message` | Commit message. |
| `--tag` | Create a tag at the resulting commit. |
| `--force-tag` | Overwrite tag if it already exists. |

### write

Write stdin to a file in the repo.

```bash
echo "hello" | gitstore write file.txt
cat data.json | gitstore write :config.json
cat image.png | gitstore write :assets/logo.png -m "Add logo"

# Passthrough (tee mode) — data flows to stdout AND into the repo
cmd | gitstore write log.txt -p | grep error
tail -f /var/log/app.log | gitstore write log.txt --passthrough
```

| Option | Description |
|--------|-------------|
| `-p`, `--passthrough` | Echo stdin to stdout (tee mode for pipelines). |
| `-b`, `--branch` | Branch (default: `main`). |
| `-m`, `--message` | Commit message. |
| `--no-create` | Don't auto-create the repo. |
| `--tag` | Create a tag at the resulting commit. |
| `--force-tag` | Overwrite tag if it already exists. |

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
| `--back N` | Walk back N commits from tip. |
| `--format` | `text` (default), `json`, `jsonl`. |

Text format: `SHORT_HASH  ISO_TIMESTAMP  MESSAGE`

### diff

Compare current branch HEAD against another snapshot. Output uses git-style `--name-status` format (old → new by default):

```
A  new-file.txt          # Added since baseline
M  changed-file.txt      # Modified since baseline
D  removed-file.txt      # Deleted since baseline
```

```bash
gitstore diff --back 3                    # what changed in last 3 commits
gitstore diff --ref other-branch          # what's different vs another branch
gitstore diff --before 2025-01-01         # what changed since Jan 1
gitstore diff --ref feature --back 2      # vs feature~2
gitstore diff --back 3 --reverse          # swap direction (new → old)
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters (select baseline). |
| `--reverse` | Swap comparison direction (A↔D flipped, M stays M). |

### undo

```bash
gitstore undo                                 # back 1 commit
gitstore undo 3                               # back 3 commits
gitstore undo -b dev                          # undo on 'dev' branch
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |

### redo

```bash
gitstore redo                                 # forward 1 reflog step
gitstore redo 2                               # forward 2 steps
gitstore redo -b dev                          # redo on 'dev' branch
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |

### reflog

```bash
gitstore reflog
gitstore reflog -n 10                         # last 10 entries
gitstore reflog -b dev                        # entries for 'dev' branch
gitstore reflog --format json
```

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Branch (default: `main`). |
| `-n`, `--limit` | Limit number of entries shown. |
| `--format` | `text` (default), `json`, `jsonl`. |

---

## Refs

### branch

```bash
gitstore branch                               # list
gitstore branch list                          # same
gitstore branch create dev                    # empty orphan
gitstore branch fork dev                      # fork from default branch
gitstore branch fork dev --ref main           # fork from specific ref
gitstore branch fork dev --ref main --path config.json
gitstore branch fork dev -f                   # overwrite existing
gitstore branch set dev --ref main            # point at a ref (create or update)
gitstore branch default                       # show default branch
gitstore branch default -b dev                # set default branch
gitstore branch delete dev
gitstore branch hash main                     # tip commit SHA
gitstore branch hash main --back 3            # 3 commits before tip
gitstore branch hash main --path config.json  # last commit that changed file
```

#### branch create options

Creates an empty orphan branch. No additional options.

#### branch fork options

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Source branch (default: repo default). |
| `-f`, `--force` | Overwrite if branch already exists. |
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

#### branch set options

| Option | Description |
|--------|-------------|
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

#### branch hash options

| Option | Description |
|--------|-------------|
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

### tag

```bash
gitstore tag                                  # list
gitstore tag list                             # same
gitstore tag fork v1.0                        # tag from default branch
gitstore tag fork v1.0 --ref main             # tag from specific ref
gitstore tag fork v1.0 --before 2024-06-01    # tag a historical commit
gitstore tag set v1.0 --ref main              # create or update tag
gitstore tag hash v1.0                        # commit SHA
gitstore tag delete v1.0
```

#### tag fork options

| Option | Description |
|--------|-------------|
| `-b`, `--branch` | Source branch (default: repo default). |
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

#### tag set options

| Option | Description |
|--------|-------------|
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

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
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |

#### unarchive options

| Option | Description |
|--------|-------------|
| `--format` | `zip` or `tar` (overrides auto-detect; required for stdin). |
| `-b`, `--branch` | Branch (default: `main`). |
| `-m`, `--message` | Commit message. |
| `--no-create` | Don't auto-create the repo. |
| `--tag` | Create a tag at the resulting commit. |
| `--force-tag` | Overwrite tag if it already exists. |

### zip / unzip / tar / untar

Aliases with a fixed format. Same options as archive/unarchive (including `--tag` / `--force-tag` for import commands).

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

## Server

### serve

Serve repository files over HTTP with content negotiation. Browsers see HTML directory listings and raw file contents; API clients requesting `Accept: application/json` get JSON metadata.

```bash
gitstore serve                                   # serve HEAD branch at http://127.0.0.1:8000/
gitstore serve -b dev                            # serve a different branch
gitstore serve --ref v1.0                        # serve a tag snapshot
gitstore serve --back 3                          # serve 3 commits before tip
gitstore serve --all                             # multi-ref: /<branch-or-tag>/<path>
gitstore serve --all --cors                      # multi-ref with CORS headers
gitstore serve --base-path /data -p 9000         # mount under /data on port 9000
gitstore serve --open --no-cache                 # open browser, disable caching
gitstore serve -q                                # suppress per-request log output
```

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`). |
| `-p`, `--port` | Port to listen on (default: `8000`, use `0` for OS-assigned). |
| `-b`, `--branch` | Branch (default: `main`). |
| `--ref`, `--path`, `--match`, `--before`, `--back` | Snapshot filters. |
| `--all` | Multi-ref mode: expose all branches and tags via `/<ref>/<path>`. |
| `--cors` | Add `Access-Control-Allow-Origin: *` and related CORS headers. |
| `--no-cache` | Send `Cache-Control: no-store` on every response. |
| `--base-path PREFIX` | URL prefix to mount under (e.g. `/data`). |
| `--open` | Open the URL in the default browser on start. |
| `-q`, `--quiet` | Suppress per-request log output. |

**Modes:**

- **Single-ref** (default): serves one branch or snapshot. URLs are plain repo paths (`/file.txt`, `/dir/`).
- **Multi-ref** (`--all`): first URL segment selects the branch or tag (`/main/file.txt`, `/v1/dir/`). The root (`/`) lists all branches and tags.

**Content negotiation:**

- `Accept: application/json` returns JSON metadata (path, ref, size, type, entries).
- Otherwise: raw file bytes with MIME types, or HTML directory listings.

**Response headers:**

- `ETag` is set to the commit hash on all 200 responses.
- JSON, XML, GeoJSON, and YAML files are served as `text/plain` so browsers display them inline.

### gitserve

Serve the repository read-only over HTTP. Standard git clients can clone and fetch from the URL. Pushes are rejected.

```bash
gitstore gitserve                                # serve at 127.0.0.1:8000
gitstore gitserve -p 9000                        # custom port
gitstore gitserve --host 0.0.0.0 -p 8080         # bind all interfaces
git clone http://127.0.0.1:8000/                 # clone from another terminal
```

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`). |
| `-p`, `--port` | Port to listen on (default: `8000`, use `0` for OS-assigned). |

---

## Appendix

### The `:` prefix

For `cp` and `sync`, prefix repo-side paths with `:` to distinguish them from local paths. For other commands (`ls`, `cat`, `rm`, `write`) the `:` is optional.

### Snapshot filters

Several commands accept filters to select a specific commit:

| Option | Description |
|--------|-------------|
| `--ref REF` | Branch, tag, or commit hash. |
| `--path PATH` | Latest commit that changed this file. |
| `--match PATTERN` | Latest commit matching message pattern (`*`, `?`). |
| `--before DATE` | Latest commit on or before this date (ISO 8601). |
| `--back N` | Walk back N commits from tip. |

Filters combine with AND. Available on `cp`, `sync`, `ls`, `cat`, `log`, `diff`, `branch fork`, `branch set`, `branch hash`, `tag fork`, `tag set`, `archive`, `zip`, `tar`.

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

### Exclude patterns

The `--exclude` and `--exclude-from` options use gitignore syntax:

| Pattern | Matches |
|---------|---------|
| `*.pyc` | Any `.pyc` file at any depth |
| `build/` | Directories named `build` (not files) |
| `/build` | `build` at root only (anchored) |
| `!important.log` | Negation — un-excludes a previously excluded file |
| `__pycache__/` | `__pycache__` directories and all their contents |

Multiple `--exclude` flags combine. `--exclude-from` reads one pattern per line (blank lines and `#` comments are skipped).

The `--gitignore` flag (sync only) automatically reads `.gitignore` files from the source directory tree. Each `.gitignore` applies to files in its own directory and below. When active, `.gitignore` files themselves are excluded from the repo.

### Copy behavior table

| Source | Result at `:dest` |
|--------|-------------------|
| `file.txt` | `dest/file.txt` |
| `dir` | `dest/dir/...` (name preserved) |
| `dir/` | `dest/...` (contents, including dotfiles) |
| `'dir/*'` | `dest/matched...` (glob, no dotfiles) |
| `'**/*.py'` | `dest/matched...` (recursive glob) |
| `/base/./sub/dir` | `dest/sub/dir/...` (pivot) |
| `/base/./sub/dir/` | `dest/sub/...` (pivot + contents) |

---

See also: [Python API Reference](api.md) | [README](../README.md)
