#!/usr/bin/env bash
# Cross-language interop test runner.
# Creates repos with one language, reads with the others.
set -euo pipefail
cd "$(dirname "$0")/.."

FIXTURES="interop/fixtures.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

HAS_RUST=false
if command -v cargo &>/dev/null && [[ -f rs/Cargo.toml ]]; then
    HAS_RUST=true
fi

echo "=== Interop tests (workdir: $TMPDIR) ==="

# --- Write phase ---

echo ""
echo "--- Python writes ---"
uv run python interop/py_write.py "$FIXTURES" "$TMPDIR"

echo ""
echo "--- TypeScript writes ---"
cd ts && npx tsx ../interop/ts_write.ts "../$FIXTURES" "$TMPDIR" && cd ..

if $HAS_RUST; then
    echo ""
    echo "--- Rust writes ---"
    cargo run --manifest-path rs/Cargo.toml --example rs_write -- "$FIXTURES" "$TMPDIR"
fi

# --- Cross-read phase ---

echo ""
echo "--- TypeScript reads Python repos ---"
cd ts && npx tsx ../interop/ts_read.test.ts "../$FIXTURES" "$TMPDIR" py && cd ..

echo ""
echo "--- Python reads TypeScript repos ---"
uv run python interop/py_read_test.py "$FIXTURES" "$TMPDIR" ts

if $HAS_RUST; then
    echo ""
    echo "--- Rust reads Python repos ---"
    cargo run --manifest-path rs/Cargo.toml --example rs_read -- "$FIXTURES" "$TMPDIR" py

    echo ""
    echo "--- Rust reads TypeScript repos ---"
    cargo run --manifest-path rs/Cargo.toml --example rs_read -- "$FIXTURES" "$TMPDIR" ts

    echo ""
    echo "--- Python reads Rust repos ---"
    uv run python interop/py_read_test.py "$FIXTURES" "$TMPDIR" rs

    echo ""
    echo "--- TypeScript reads Rust repos ---"
    cd ts && npx tsx ../interop/ts_read.test.ts "../$FIXTURES" "$TMPDIR" rs && cd ..
fi

echo ""
echo "=== All interop tests passed ==="
