#!/usr/bin/env bash
# Cross-language interop test runner.
# Creates repos with one language, reads with the other.
set -euo pipefail
cd "$(dirname "$0")/.."

FIXTURES="interop/fixtures.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "=== Interop tests (workdir: $TMPDIR) ==="

# --- Python writes, TypeScript reads ---
echo ""
echo "--- Python writes ---"
uv run python interop/py_write.py "$FIXTURES" "$TMPDIR"

echo ""
echo "--- TypeScript reads Python repos ---"
cd ts && npx tsx ../interop/ts_read.test.ts "../$FIXTURES" "$TMPDIR" && cd ..

# --- TypeScript writes, Python reads ---
echo ""
echo "--- TypeScript writes ---"
cd ts && npx tsx ../interop/ts_write.ts "../$FIXTURES" "$TMPDIR" && cd ..

echo ""
echo "--- Python reads TypeScript repos ---"
uv run python interop/py_read_test.py "$FIXTURES" "$TMPDIR"

echo ""
echo "=== All interop tests passed ==="
