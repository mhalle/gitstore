#!/usr/bin/env bash
# Test parity checker — compares Python and TypeScript test counts.
# Flags Python test files with no TS counterpart (excludes CLI/serve/watch).
set -euo pipefail
cd "$(dirname "$0")/.."

# Modules to skip entirely (CLI-only, no TS equivalent expected)
SKIP_PATTERN="test_cli|test_serve|test_watch"

# Python-only modules — TS counterpart intentionally absent.
# auto_create: CLI auto-create repo feature
# backup_restore: requires HTTP transport (TS API is HTTP-only, no local tests)
# exclude: ExcludeFilter not implemented in TS
# fileobj: .open() file objects — different paradigm (sync vs async)
# objsize: dulwich-specific ObjectSizer, no isomorphic-git equivalent
# ref_path: CLI ref:path parsing (portable parts in ts/tests/validation.test.ts)
PY_ONLY="auto_create|backup_restore|exclude|fileobj|objsize|ref_path"

printf "%-30s %6s %6s\n" "Module" "Python" "TS"
printf "%-30s %6s %6s\n" "------" "------" "------"

total_py=0
total_ts=0
missing=()
py_only=()

for pyfile in tests/test_*.py; do
    base=$(basename "$pyfile" .py)       # test_fs_read
    module=${base#test_}                 # fs_read

    # Skip excluded patterns
    if echo "$base" | grep -qE "$SKIP_PATTERN"; then
        continue
    fi

    py_count=$(grep -c '^\s*def test_' "$pyfile" 2>/dev/null || echo 0)

    # Map Python naming to TS naming: test_fs_read -> fs-read.test.ts
    ts_name=$(echo "$module" | tr '_' '-')
    tsfile="ts/tests/${ts_name}.test.ts"

    if [[ -f "$tsfile" ]]; then
        ts_count=$(grep -c "^\s*it(" "$tsfile" 2>/dev/null || echo 0)
    elif echo "$module" | grep -qE "^($PY_ONLY)$"; then
        ts_count="n/a"
        py_only+=("$module")
    else
        ts_count="-"
        missing+=("$module")
    fi

    printf "%-30s %6s %6s\n" "$module" "$py_count" "$ts_count"
    total_py=$((total_py + py_count))
    if [[ "$ts_count" != "-" && "$ts_count" != "n/a" ]]; then
        total_ts=$((total_ts + ts_count))
    fi
done

printf "%-30s %6s %6s\n" "------" "------" "------"
printf "%-30s %6d %6d\n" "TOTAL" "$total_py" "$total_ts"

if [[ ${#missing[@]} -gt 0 ]]; then
    echo ""
    echo "Missing TS counterparts:"
    for m in "${missing[@]}"; do
        echo "  - $m"
    done
fi

if [[ ${#py_only[@]} -gt 0 ]]; then
    echo ""
    echo "Python-only (no TS port expected):"
    for m in "${py_only[@]}"; do
        echo "  - $m"
    done
fi
