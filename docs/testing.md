# Testing

gitstore has two implementations — Python (primary) and TypeScript — with shared
test coverage and a cross-language interop suite.

## Quick reference

```bash
make test-py        # Python tests only
make test-ts        # TypeScript tests only
make test-interop   # cross-language interop tests
make test-all       # all of the above
```

## Python tests

- **Framework:** pytest
- **Location:** `tests/test_*.py` (29 files, ~1041 tests)
- **Run:** `uv run python -m pytest tests/ -v`
- **Run one file:** `uv run python -m pytest tests/test_sync.py -v`
- **Run one test:** `uv run python -m pytest tests/test_sync.py -k test_basic_sync -v`

Tests use temporary bare git repos created via fixtures. No external services
required.

## TypeScript tests

- **Framework:** vitest
- **Location:** `ts/tests/*.test.ts` (16 files, ~484 tests)
- **Run:** `cd ts && npm test`
- **Run one file:** `cd ts && npx vitest run tests/sync.test.ts`
- **Run one test:** `cd ts && npx vitest run tests/sync.test.ts -t "basic sync"`

Test helpers live in `ts/tests/helpers.ts` (`freshStore`, `toBytes`, `fromBytes`,
`rmTmpDir`). Each test creates a temporary bare repo via `freshStore()` and cleans
it up in `afterEach`.

## Interop tests

The interop suite (`interop/`) verifies that repos created by one language can be
read by the other:

1. Python writes repos → TypeScript reads them
2. TypeScript writes repos → Python reads them

Fixtures are defined in `interop/fixtures.json`. Run with `make test-interop` or
`bash interop/run.sh`.

## Test parity

The parity script compares Python and TypeScript test counts side-by-side:

```bash
bash scripts/test-parity.sh
```

Some Python modules have no TypeScript counterpart by design:

| Module | Reason |
|--------|--------|
| `auto_create` | CLI auto-create repo feature |
| `backup_restore` | requires local HTTP transport |
| `exclude` | `ExcludeFilter` not implemented in TS |
| `fileobj` | `.open()` file objects (sync context manager) |
| `objsize` | dulwich-specific `ObjectSizer` |
| `ref_path` | CLI `ref:path` parsing |

## File naming convention

Python and TypeScript test files correspond by name:

| Python | TypeScript |
|--------|-----------|
| `tests/test_fs_read.py` | `ts/tests/fs-read.test.ts` |
| `tests/test_copy.py` | `ts/tests/copy.test.ts` |
| `tests/test_sync.py` | `ts/tests/sync.test.ts` |

The pattern is: `test_{module}.py` → `{module-with-hyphens}.test.ts`.

## Writing new tests

- **Python:** add `def test_*` methods inside test classes in the appropriate
  `tests/test_*.py` file.
- **TypeScript:** add `it('...')` calls inside `describe` blocks in the
  appropriate `ts/tests/*.test.ts` file. Use `freshStore()` from helpers for
  a clean repo, and `rmTmpDir()` in `afterEach` for cleanup.
- After adding tests to either side, run `bash scripts/test-parity.sh` to check
  coverage alignment.
