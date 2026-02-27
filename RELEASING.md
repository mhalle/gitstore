# Releasing

How to cut a new vost release.

## 1. Decide the scope

Each port has its own version number. Bump only the ports that changed:

| Port | Version file | Field |
|------|-------------|-------|
| Python | `pyproject.toml` | `version = "0.68.4"` |
| TypeScript | `ts/package.json` | `"version": "0.9.4"` |
| Rust | `rs/Cargo.toml` | `version = "0.9.2"` |
| C++ | `cpp/CMakeLists.txt` | `project(vost VERSION 0.8.4 ...)` |
| Kotlin | `kotlin/build.gradle.kts` | `version = "0.9.6"` |

The git tag (`v0.68.4`) tracks the Python version since that's the primary package.

## 2. Update files

1. **Bump version** in the relevant file(s) above.
2. **Update `CHANGELOG.md`** — move items from `## Unreleased` into a new section:
   ```
   ## v0.66.2 / TS v0.8.1 / Rust v0.9.0 (2026-02-26)
   ```
   Include port-specific versions only for ports that changed. Python-only releases use just `v0.66.2`.
3. **Lock files** — these update automatically but should be committed:
   - `uv.lock` (Python — updates when `pyproject.toml` version changes)
   - `ts/package-lock.json` (TypeScript — run `cd ts && npm install`)
   - `rs/Cargo.lock` (Rust — run `cd rs && cargo check`)
4. **Update `TESTING.md`** test counts if they changed.

## 3. Commit, tag, push

```bash
git add -u
git commit -m "v0.66.2: <short description>"
git tag v0.66.2
git push && git push origin v0.66.2
```

The tag triggers automated publishing (see below).

## 4. Publishing

### Python (PyPI) — automated

Pushing a `v*` tag triggers `.github/workflows/publish.yml`, which builds and publishes to PyPI via trusted publishing (OIDC, no secrets needed).

Manual fallback:
```bash
uv build
uvx twine upload dist/*   # reads ~/.pypirc
```

### TypeScript (npm) — manual

Published as `@mhalle/vost` (scoped — npm rejects `vost` as too similar to existing short names).

```bash
cd ts && npm publish --otp=<code>
```

The `prepack` script runs `tsc` automatically. Requires 2FA OTP.

To automate: add a GitHub Actions workflow triggered on `v*` tags, using `NPM_TOKEN` secret or npm provenance (OIDC).

### Rust (crates.io) — TODO

Not yet configured. When ready:

```bash
cd rs
cargo publish
```

Requires: `cargo login` with a crates.io API token.

To automate: add a GitHub Actions workflow with `CARGO_REGISTRY_TOKEN` secret.

### C++ — no registry

C++ is distributed as source. Users can:
- Clone the repo and build with CMake
- Use vcpkg with the `vcpkg.json` manifest

No publishing step needed.

### Kotlin (Maven Central) — TODO

Not yet configured. When ready, publishing to Maven Central requires:

1. Sonatype OSSRH account (via https://central.sonatype.com/)
2. GPG signing key
3. Gradle `maven-publish` + `signing` plugins in `build.gradle.kts`
4. Publish: `cd kotlin && ./gradlew publishToMavenCentral`

To automate: add a GitHub Actions workflow with signing key + Sonatype credentials as secrets.

## Version history

The `CHANGELOG.md` is the canonical record. Git tags mark Python releases:

```bash
git tag --sort=-v:refname | head -10
```
