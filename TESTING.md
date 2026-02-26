# Testing

This document covers how to build, test, and run cross-language interop tests for all five vost ports.

## Prerequisites

| Port | Requirements |
|------|-------------|
| Python | Python 3.10+, [uv](https://docs.astral.sh/uv/) |
| TypeScript | Node.js 18+, npm |
| Rust | Rust 1.75+ (via rustup) |
| C++ | CMake 3.20+, C++17 compiler, libgit2, Catch2 |
| Kotlin | Java 21 (via [sdkman](https://sdkman.io/)), Gradle (bundled wrapper) |
| Deno (optional) | Deno runtime |

### macOS setup

```bash
# Python
brew install uv

# C++ dependencies
brew install libgit2 catch2

# Kotlin (Java 21 via sdkman)
curl -s "https://get.sdkman.io" | bash
source ~/.sdkman/bin/sdkman-init.sh
sdk install java 21-tem
```

### Linux (Ubuntu/Debian) setup

```bash
# Python
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node.js (via NodeSource)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs

# C++ dependencies
sudo apt install -y cmake g++ libgit2-dev catch2

# Kotlin (Java 21 via sdkman)
curl -s "https://get.sdkman.io" | bash
source ~/.sdkman/bin/sdkman-init.sh
sdk install java 21-tem

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Linux (Fedora/RHEL) setup

```bash
# Python
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node.js
sudo dnf install -y nodejs npm

# C++ dependencies
sudo dnf install -y cmake gcc-c++ libgit2-devel catch2-devel

# Kotlin (Java 21 via sdkman)
curl -s "https://get.sdkman.io" | bash
source ~/.sdkman/bin/sdkman-init.sh
sdk install java 21-tem

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Rust, Node.js, and Deno are assumed to be installed via their standard installers on macOS.

## Running tests per port

### Python (1,362 tests)

```bash
uv run python -m pytest tests/ -v
```

### TypeScript (631 tests)

```bash
cd ts && npm test
```

### TypeScript — Deno compat (33 tests)

```bash
cd ts && npm run build && npm run test:deno
```

### Rust (549 tests)

```bash
cd rs && cargo test --all-targets
```

### C++ (345 tests)

Build first, then run:

```bash
# Configure — macOS with Homebrew
cmake -B cpp/build -S cpp/ \
      -DCMAKE_PREFIX_PATH="$(brew --prefix libgit2);$(brew --prefix catch2)"

# Configure — Linux (system packages are found automatically)
cmake -B cpp/build -S cpp/

# Build
cmake --build cpp/build

# Test
ctest --test-dir cpp/build --output-on-failure
```

With vcpkg instead of system packages:

```bash
cmake -B cpp/build -S cpp/ \
      -DCMAKE_TOOLCHAIN_FILE=/path/to/vcpkg/scripts/buildsystems/vcpkg.cmake
cmake --build cpp/build
ctest --test-dir cpp/build --output-on-failure
```

### Kotlin (270 tests)

```bash
source ~/.sdkman/bin/sdkman-init.sh   # ensure Java is in PATH
cd kotlin && ./gradlew test
```

## Cross-language interop tests

The interop suite verifies that repos written by one port can be read by all others. Each port writes a set of fixtures (basic tree, symlinks, binary data, executables, history, notes), then every other port reads and validates them.

### Pre-build steps

The interop script auto-detects which ports are available. Python and TypeScript always run. Rust, C++, and Kotlin are included only if their binaries/JARs are present.

**C++ interop binaries** — build with the `-DVOST_BUILD_INTEROP=ON` flag:

```bash
# macOS with Homebrew
cmake -B cpp/build -S cpp/ \
      -DCMAKE_PREFIX_PATH="$(brew --prefix libgit2);$(brew --prefix catch2)" \
      -DVOST_BUILD_INTEROP=ON

# Linux (system packages)
cmake -B cpp/build -S cpp/ -DVOST_BUILD_INTEROP=ON

cmake --build cpp/build
```

This produces `cpp/build/cpp_write` and `cpp/build/cpp_read`.

**Kotlin interop JAR** — build the shadow (fat) JAR:

```bash
source ~/.sdkman/bin/sdkman-init.sh
cd kotlin && ./gradlew shadowJar
```

This produces `kotlin/build/libs/vost-interop.jar`.

### Running interop

```bash
# Ensure Java is in PATH for Kotlin
source ~/.sdkman/bin/sdkman-init.sh

bash interop/run.sh
```

The script creates a temp directory, runs the write phase for each available port, then cross-reads every combination. It prints `=== All interop tests passed ===` on success.

### What the interop tests cover

- **basic_tree** — text files in flat and nested directories
- **symlinks** — symbolic links including nested ones
- **binary** — binary blob data of various sizes
- **executable** — files with the executable bit set
- **history** — multi-commit branch with parent traversal
- **notes** — git notes across multiple namespaces

## Running everything

To run all port tests plus interop in one go:

```bash
# Python
uv run python -m pytest tests/ -v

# TypeScript
cd ts && npm test && cd ..

# Rust
cd rs && cargo test --all-targets && cd ..

# C++ (configure + build + test; includes interop binaries)
# macOS with Homebrew:
cmake -B cpp/build -S cpp/ \
      -DCMAKE_PREFIX_PATH="$(brew --prefix libgit2);$(brew --prefix catch2)" \
      -DVOST_BUILD_INTEROP=ON
# Linux: cmake -B cpp/build -S cpp/ -DVOST_BUILD_INTEROP=ON
cmake --build cpp/build
ctest --test-dir cpp/build --output-on-failure

# Kotlin (270 tests)
source ~/.sdkman/bin/sdkman-init.sh
cd kotlin && ./gradlew test && cd ..
# Detailed report: kotlin/build/reports/tests/test/index.html

# Interop (all 5 ports cross-read)
source ~/.sdkman/bin/sdkman-init.sh
bash interop/run.sh
```

## Test counts (v0.66.1)

| Port | Tests |
|------|------:|
| Python | 1,362 |
| TypeScript | 631 |
| Deno | 33 |
| Rust | 549 |
| C++ | 345 |
| Kotlin | 270 |
| **Total** | **3,190** |
