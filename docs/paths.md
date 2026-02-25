# Path Syntax

vost paths identify files on disk, files in the repo, or files on a
specific branch/tag/commit.  This document describes the full syntax, how each
command interprets it, and how paths interact with flags.

---

## Quick reference

| Syntax | Meaning |
|--------|---------|
| `file.txt` | Local filesystem path |
| `:file.txt` | Repo path on the current branch |
| `:` | Repo root on the current branch |
| `main:file.txt` | Repo path on the `main` branch |
| `main:` | Repo root on the `main` branch |
| `v1.0:data/file` | Repo path on the `v1.0` tag |
| `main~3:file.txt` | `file.txt` three commits back on `main` |
| `~2:file.txt` | `file.txt` two commits back on the current branch |
| `~1:` | Repo root one commit back on the current branch |

---

## Anatomy of a path

A path argument is parsed into three components:

```
[ref[~N]]:path
```

| Component | Optional | Description |
|-----------|----------|-------------|
| **ref** | yes | Branch name, tag name, or commit hash. Empty string means "current branch" (determined by `-b` or repo default). Absent (no colon at all) means "local filesystem". |
| **~N** | yes | Ancestor suffix. Walk back N parent commits from the ref. N must be a positive integer. |
| **path** | yes | File or directory path. May be empty (meaning the repo root). |

### Parsing rules

The parser looks for the first `:` in the argument and applies these rules in
order:

1. **No colon** -- the entire argument is a local filesystem path.

2. **Colon at position 0** (`:path`) -- repo path on the current branch.  The
   ref is the empty string; the path is everything after the colon.

3. **Single letter before colon, followed by `/` or `\`** (e.g. `C:/Users`,
   `D:\data`) -- treated as a Windows drive letter.  The entire argument is a
   local path.

4. **`/` or `\` appears anywhere before the colon** (e.g. `./local:file`,
   `/tmp/my:data`) -- the colon is part of a filesystem path.  The entire
   argument is a local path.

5. **Otherwise** -- everything before the colon is the ref (possibly with a
   `~N` suffix); everything after is the repo path.

### Ancestor syntax

If the ref portion (the part before `:`) contains a tilde, the last `~` splits
it into a base ref and an integer suffix:

```
main~3:file.txt    ->  ref="main", back=3, path="file.txt"
v1.0~1:data/       ->  ref="v1.0", back=1, path="data/"
~2:file.txt        ->  ref="" (current branch), back=2, path="file.txt"
```

Constraints:

- The suffix after `~` must be a positive integer.  `main~abc:f` is an error.
- `~0` is invalid.  Use `main:f` instead.

### Path normalization

Once the repo path is extracted:

- A leading `/` is silently stripped: `:/foo` is equivalent to `:foo`.
- `..` components are rejected (to prevent traversal above the repo root).
- An empty path means the repo root.

---

## How each command uses paths

### Commands where the `:` prefix is optional

For `ls`, `cat`, `rm`, and `write`, arguments are always repo paths, so the
colon is optional.  `gitstore cat file.txt` and `gitstore cat :file.txt` are
equivalent.  However, the colon is **required** to use explicit ref syntax:
`gitstore cat main:file.txt` reads from the `main` branch, while
`gitstore cat main:file.txt` without the colon would look for a local file
named `main:file.txt` -- but since there's no `/` or `\` before the colon, the
parser treats it as a ref:path anyway.  In practice, the `:` matters only for
distinguishing `ref:path` from plain filenames that happen to contain colons
(rare on Unix, common on Windows -- handled by rule 3/4).

### Commands where `:` is required

For `cp`, `sync`, and `mv`, source and destination may be either local or repo
paths (for `cp`/`sync`) or must all be repo paths (for `mv`).
The colon prefix is what distinguishes them.

---

### ls

```
vost ls [PATH...]
```

Each PATH is parsed independently.  Different paths may reference different
branches, tags, or ancestors.  Results are coalesced and deduplicated.

```bash
vost ls                          # root of current branch
vost ls :src                     # subdirectory
vost ls main:src                 # subdirectory on main
vost ls main:src dev:docs        # from two branches at once
vost ls main: --back 2           # main, two commits back
vost ls -R main~3:src            # recursive listing, 3 back on main
vost ls '*.py'                   # glob expansion
```

Glob patterns (`*`, `?`, `**`) are expanded within the resolved repo tree.
Quote them to prevent shell expansion.

**Implicit root:** with no arguments, lists the root of the current branch.

---

### cat

```
vost cat PATH [PATH...]
```

Each PATH is parsed independently.  File contents are written to stdout in
argument order, concatenated with no separator (like UNIX `cat`).

```bash
vost cat :file.txt
vost cat main:config.json
vost cat v1.0:data/file.txt
vost cat main:file.txt --back 1       # one commit back on main
vost cat ~1:file.txt                  # one commit back on current branch
```

---

### rm

```
vost rm PATH [PATH...]
```

Each PATH is parsed.  All paths **must target the same branch** -- you cannot
remove files from different branches in a single command.  When a path has an
explicit ref, it determines the target branch.

```bash
vost rm :old.txt                     # remove from current branch
vost rm dev:old.txt                  # remove from dev
vost rm dev:a.txt dev:b.txt          # ok -- same branch
vost rm dev:a.txt main:b.txt         # ERROR -- different branches
```

Tags and commit hashes are not writable:

```bash
vost rm v1.0:file.txt               # ERROR -- cannot write to tag
```

Accepts glob patterns and `-R` for directories.

---

### mv

```
vost mv SOURCE... DEST
```

All arguments must be repo paths (colon prefix required). All paths **must
target the same branch** — cross-branch moves are not supported.

```bash
vost mv :old.txt :new.txt               # rename
vost mv ':*.txt' :archive/              # glob move
vost mv -R :data :backup                # rename directory
vost mv dev:old.txt dev:new.txt         # explicit branch
vost mv main:a.txt dev:b.txt            # ERROR — cross-branch
```

Tags and ancestors are not writable:

```bash
vost mv v1.0:a.txt v1.0:b.txt          # ERROR — cannot write to tag
vost mv :a.txt main~1:b.txt            # ERROR — can't write to history
```

Accepts glob patterns and `-R` for directories.

---

### write

```
vost write PATH
```

Reads stdin and writes it as a single file.  The PATH is parsed:

```bash
echo "data" | gitstore write :file.txt          # current branch
echo "data" | gitstore write dev:file.txt        # write to dev
echo "data" | gitstore write ~1:file.txt         # ERROR -- can't write to history
```

When the path has an explicit ref, it overrides `-b`:

```bash
echo "x" | gitstore write dev:f.txt -b main     # ERROR -- conflicting
echo "x" | gitstore write dev:f.txt              # writes to dev
```

---

### cp

```
vost cp SOURCE... DEST
```

The last argument is the destination.  Direction is determined by which
arguments are repo paths:

| Sources | Destination | Direction |
|---------|-------------|-----------|
| All local | repo (`:...`) | disk -> repo |
| All repo (`:...`) | local | repo -> disk |
| All repo (`:...`) | repo (`:...`) | repo -> repo |
| Mixed local+repo | any | ERROR |

```bash
# disk -> repo
vost cp file.txt :
vost cp file.txt :dest/file.txt
vost cp dir/ :dest

# repo -> disk
vost cp :file.txt ./local.txt
vost cp main:file.txt ./local.txt
vost cp main~1:file.txt ./out/

# repo -> repo (cross-branch copy)
vost cp session:/ :                          # overlay session onto current branch
vost cp main:a.txt :backup/                  # copy file from main to backup/ on current branch
vost cp main~1:a.txt dev:b.txt :dest/        # ERROR -- mixed local+repo (just kidding, all repo is fine)
```

**Per-source ref resolution:** each source can specify its own ref.  Sources
without an explicit ref use the default (set by `-b` / `--ref` / snapshot
filters, or the repo default branch).

```bash
vost cp main:a.txt :backup/a.txt             # source from main
vost cp main:a.txt dev:b.txt :merged/         # two sources, two branches
```

**Destination ref resolution:** the destination ref determines which branch
is written to.

```bash
vost cp file.txt :                            # write to current branch (from -b or default)
vost cp file.txt dev:                         # write to dev branch
vost cp file.txt dev~1:path                   # ERROR -- can't write to history
vost cp file.txt v1.0:path                    # ERROR -- can't write to tag
```

---

### sync

```
vost sync PATH                    # 1-arg: local dir -> repo root
vost sync SOURCE DEST            # 2-arg: direction from colon prefix
```

Sync makes the destination identical to the source (like rsync `--delete`).

**One argument:** always a local directory synced to the repo root.

**Two arguments:** direction is determined by the colon prefix:

| Source | Destination | Direction |
|--------|-------------|-----------|
| local | `:...` | disk -> repo |
| `:...` or `ref:...` | local | repo -> disk |
| `ref:...` | `:...` or `ref:...` | repo -> repo |

```bash
vost sync ./dir                              # dir -> repo root
vost sync ./local :data                      # disk -> repo
vost sync :data ./local                      # repo -> disk
vost sync main:data ./local                  # explicit source ref
vost sync main: dev:                         # repo -> repo (main overwrites dev)
vost sync main~1: dev:                       # from one commit back on main
vost sync main: dev: --back 2                # ERROR if -b is also given
```

---

### log

```
vost log [TARGET]
```

The optional TARGET is parsed with ref:path syntax.  It sets the starting ref,
ancestor depth, and/or path filter:

```bash
vost log                                      # all commits on current branch
vost log main:config.json                     # log of config.json on main
vost log ~3:                                  # starting 3 back on current branch
vost log main~3:                              # starting 3 back on main
vost log config.json                          # plain path (no colon) -> --path filter
```

The positional TARGET merges with flags.  If both specify the same thing, it's
an error:

```bash
vost log main: --ref main                    # ERROR -- ref specified twice
vost log main~3: --back 1                    # ERROR -- ancestor specified twice
vost log main:file.txt --path file.txt       # ERROR -- path specified twice
vost log main: -b dev                        # ERROR -- branch conflicts with ref
```

---

### diff

```
vost diff [BASELINE]
```

The optional BASELINE selects what to compare against HEAD.  Parsed with
ref:path syntax:

```bash
vost diff                                     # needs --back, --ref, etc.
vost diff ~3:                                 # HEAD vs 3 commits back
vost diff dev:                                # HEAD vs dev branch
vost diff main~2:                             # HEAD vs main, 2 back
```

Same conflict rules as `log`.

---

## Interaction with flags

### `-b` / `--branch`

Sets the default branch for the command.  When no explicit ref appears in any
path, `-b` determines which branch is used.

**Conflicts with explicit `ref:`.**  If any path argument contains an explicit
ref (non-empty string before `:`), `-b` is an error:

```bash
vost ls main: -b dev                         # ERROR
vost cat main:file.txt -b main               # ERROR
vost cp main:a.txt : -b dev                  # ERROR
vost sync main: dev: -b main                 # ERROR
```

Bare-colon paths (`:path`) do **not** conflict with `-b`:

```bash
vost ls :src -b dev                          # ok -- :src uses the -b branch
vost cp :file.txt ./out -b dev               # ok -- reads from dev
```

### `--ref`

Selects a branch, tag, or commit hash to read from.  It is another way to
specify the source ref.

**Conflicts with explicit `ref:`.**  If any path argument has an explicit ref,
`--ref` is an error:

```bash
vost ls main: --ref main                     # ERROR
vost cp main:a.txt ./out --ref v1.0          # ERROR
```

Bare-colon paths do not conflict -- `--ref` fills in the ref for `:` paths:

```bash
vost cp :a.txt ./out --ref v1.0              # ok -- reads a.txt from v1.0
```

### `--back N`

Walk back N parent commits from the resolved ref.

**Conflicts with `~N`.**  If any path argument uses the `~N` ancestor suffix,
`--back` is an error:

```bash
vost cat ~1:file.txt --back 1                # ERROR
vost cat main~2:file.txt --back 1            # ERROR
```

When there is no `~N` in any path, `--back` applies to the resolved ref
(whether from explicit `ref:` or from `-b`/`--ref`/default):

```bash
vost cat main:file.txt --back 2              # ok -- main, 2 commits back
vost ls main: --back 1                       # ok -- main, 1 commit back
```

### `--before`, `--path`, `--match`

These snapshot filters narrow the commit selection.  They always apply to the
resolved ref and work alongside `--back` and explicit `ref:`:

```bash
vost ls main: --before 2024-06-01            # main as of June 1
vost cat main:config.json --before 2024-01-01  # config.json on main before Jan 1
vost log main: --match "deploy*"             # deploy commits on main
```

### Multiple different refs with filters

When a command has multiple paths targeting different explicit refs, snapshot
filters (`--back`, `--before`, `--path`, `--match`) are ambiguous -- which ref
do they apply to?

```bash
vost ls main: dev: --back 1                  # ERROR -- different refs + filter
vost cp main:a.txt dev:b.txt : --back 1      # ERROR -- different source refs + filter
```

Paths targeting the **same** explicit ref are fine:

```bash
vost ls main:src main:docs --back 1          # ok -- both from main, 1 back
```

And bare-colon paths mixed with a single explicit ref are unambiguous:

```bash
vost ls main:src :docs --back 1              # ok -- main:src gets --back 1,
                                                 #        :docs uses default + --back 1
```

### Summary table

| Flag | Conflicts with | OK with |
|------|---------------|---------|
| `-b` | any explicit `ref:` in path | bare `:path`, no-colon paths |
| `--ref` | any explicit `ref:` in path | bare `:path`, no-colon paths |
| `--back` | any `~N` in path | explicit `ref:` (applied to that ref) |
| `--before` | multiple different explicit refs | single ref or same ref |
| `--path` | multiple different explicit refs | single ref or same ref |
| `--match` | multiple different explicit refs | single ref or same ref |

---

## Writability

Some commands modify the repo.  Only branches are writable -- tags and commit
hashes are read-only, and historical commits (via `~N`) are immutable.

| Path | Writable? |
|------|-----------|
| `:path` | Yes (current branch) |
| `dev:path` | Yes (if `dev` is a branch) |
| `v1.0:path` | No (tag) |
| `abc123:path` | No (commit hash) |
| `dev~1:path` | No (historical commit) |
| `~1:path` | No (historical commit) |

Commands that write (`rm`, `mv`, `write`, `cp` destination, `sync` destination)
validate this and produce a clear error:

```
Error: Cannot write to tag 'v1.0' -- use a branch
Error: Cannot write to a historical commit (remove ~N from destination)
```

---

## Direction detection in cp and sync

### cp

The parser examines all arguments:

1. Parse every argument with the ref:path rules.
2. All sources local + dest is repo -> **disk to repo**.
3. All sources repo + dest is local -> **repo to disk**.
4. All sources repo + dest is repo -> **repo to repo**.
5. Mixed local and repo sources -> **error**.
6. All local (including dest) -> **error** (no repo involvement).

### sync

1. **One argument** (no colon): always local directory -> repo root.
2. **Two arguments**: parse both.  If both are repo paths, it's repo-to-repo.
   Otherwise, the one with `:` is the repo side.

---

## Cross-branch workflows

The `ref:path` syntax enables cross-branch operations without a dedicated
transaction system.  A typical pattern:

```bash
# 1. Create a temporary working branch
vost branch set session

# 2. Make changes on the temporary branch
echo "data" | gitstore write session:file.txt
vost cp ./new-files/ session:data/

# 3. Copy results to the main branch
vost cp session:/ :

# 4. Clean up
vost branch delete session
```

Or sync an entire branch:

```bash
# Make dev identical to main
vost sync main: dev:

# Sync from a historical snapshot
vost sync main~5: dev:
```

---

## Ref name restrictions

Branch and tag names must not contain:

| Character | Reason |
|-----------|--------|
| `:` (colon) | Used as the ref:path delimiter |
| ` ` (space) | Ambiguous in shell arguments |
| `\t` (tab) | Whitespace |
| `\n` (newline) | Whitespace |

Attempting to create a branch or tag with these characters produces an error.
Names with `/`, `.`, `-`, and `_` are allowed (e.g. `feature/login`,
`release-1.0`).
