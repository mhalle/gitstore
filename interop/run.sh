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

HAS_CPP=false
if [[ -x cpp/build/cpp_write && -x cpp/build/cpp_read ]]; then
    HAS_CPP=true
fi

HAS_KOTLIN=false
KT_JAR="kotlin/build/libs/vost-interop.jar"
if [[ -f "$KT_JAR" ]]; then
    HAS_KOTLIN=true
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

if $HAS_CPP; then
    echo ""
    echo "--- C++ writes ---"
    cpp/build/cpp_write "$FIXTURES" "$TMPDIR"
fi

if $HAS_KOTLIN; then
    echo ""
    echo "--- Kotlin writes ---"
    java -jar "$KT_JAR" write "$FIXTURES" "$TMPDIR"
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

if $HAS_CPP; then
    echo ""
    echo "--- C++ reads Python repos ---"
    cpp/build/cpp_read "$FIXTURES" "$TMPDIR" py

    echo ""
    echo "--- C++ reads TypeScript repos ---"
    cpp/build/cpp_read "$FIXTURES" "$TMPDIR" ts

    echo ""
    echo "--- Python reads C++ repos ---"
    uv run python interop/py_read_test.py "$FIXTURES" "$TMPDIR" cpp

    echo ""
    echo "--- TypeScript reads C++ repos ---"
    cd ts && npx tsx ../interop/ts_read.test.ts "../$FIXTURES" "$TMPDIR" cpp && cd ..

    if $HAS_RUST; then
        echo ""
        echo "--- Rust reads C++ repos ---"
        cargo run --manifest-path rs/Cargo.toml --example rs_read -- "$FIXTURES" "$TMPDIR" cpp

        echo ""
        echo "--- C++ reads Rust repos ---"
        cpp/build/cpp_read "$FIXTURES" "$TMPDIR" rs
    fi
fi

if $HAS_KOTLIN; then
    echo ""
    echo "--- Kotlin reads Python repos ---"
    java -jar "$KT_JAR" read "$FIXTURES" "$TMPDIR" py

    echo ""
    echo "--- Kotlin reads TypeScript repos ---"
    java -jar "$KT_JAR" read "$FIXTURES" "$TMPDIR" ts

    echo ""
    echo "--- Python reads Kotlin repos ---"
    uv run python interop/py_read_test.py "$FIXTURES" "$TMPDIR" kt

    echo ""
    echo "--- TypeScript reads Kotlin repos ---"
    cd ts && npx tsx ../interop/ts_read.test.ts "../$FIXTURES" "$TMPDIR" kt && cd ..

    if $HAS_RUST; then
        echo ""
        echo "--- Rust reads Kotlin repos ---"
        cargo run --manifest-path rs/Cargo.toml --example rs_read -- "$FIXTURES" "$TMPDIR" kt

        echo ""
        echo "--- Kotlin reads Rust repos ---"
        java -jar "$KT_JAR" read "$FIXTURES" "$TMPDIR" rs
    fi

    if $HAS_CPP; then
        echo ""
        echo "--- C++ reads Kotlin repos ---"
        cpp/build/cpp_read "$FIXTURES" "$TMPDIR" kt

        echo ""
        echo "--- Kotlin reads C++ repos ---"
        java -jar "$KT_JAR" read "$FIXTURES" "$TMPDIR" cpp
    fi
fi

echo ""
echo "=== All interop tests passed ==="
