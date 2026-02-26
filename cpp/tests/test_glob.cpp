#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <algorithm>
#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_gtest_" + std::to_string(
                    std::hash<std::thread::id>{}(std::this_thread::get_id())
                    ^ static_cast<size_t>(
                          std::chrono::steady_clock::now()
                              .time_since_epoch()
                              .count())));
    return tmp;
}

static vost::GitStore open_store(const fs::path& path,
                                  const std::string& branch = "main") {
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = branch;
    return vost::GitStore::open(path, opts);
}

/// Helper: create a store with some files for glob testing.
static vost::Fs make_glob_fixture(vost::GitStore& store) {
    auto snap = store.branches().get("main");
    // Create a file structure:
    // readme.txt
    // src/main.cpp
    // src/util.cpp
    // src/lib/helper.h
    // src/lib/helper.cpp
    // .hidden
    // .config/settings.json
    // docs/guide.md
    // docs/api.md
    auto mk = [](const std::string& s) -> vost::WriteEntry {
        return vost::WriteEntry::from_text(s);
    };
    std::vector<std::pair<std::string, vost::WriteEntry>> writes = {
        {"readme.txt",            mk("README")},
        {"src/main.cpp",          mk("main")},
        {"src/util.cpp",          mk("util")},
        {"src/lib/helper.h",      mk("h")},
        {"src/lib/helper.cpp",    mk("c")},
        {".hidden",               mk("h")},
        {".config/settings.json", mk("s")},
        {"docs/guide.md",         mk("g")},
        {"docs/api.md",           mk("a")},
    };
    return snap.apply(writes);
}

// ---------------------------------------------------------------------------
// Basic glob tests
// ---------------------------------------------------------------------------

TEST_CASE("Glob: *.txt matches top-level txt files", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("*.txt");
    REQUIRE(results.size() == 1);
    CHECK(results[0] == "readme.txt");

    fs::remove_all(path);
}

TEST_CASE("Glob: *.cpp matches nothing at top level", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("*.cpp");
    CHECK(results.empty());

    fs::remove_all(path);
}

TEST_CASE("Glob: src/*.cpp matches cpp files in src/", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("src/*.cpp");
    REQUIRE(results.size() == 2);
    CHECK(results[0] == "src/main.cpp");
    CHECK(results[1] == "src/util.cpp");

    fs::remove_all(path);
}

TEST_CASE("Glob: src/lib/* matches all files in src/lib/", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("src/lib/*");
    REQUIRE(results.size() == 2);
    CHECK(results[0] == "src/lib/helper.cpp");
    CHECK(results[1] == "src/lib/helper.h");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// ? wildcard
// ---------------------------------------------------------------------------

TEST_CASE("Glob: ? matches single character", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("docs/???.md");
    REQUIRE(results.size() == 1);
    CHECK(results[0] == "docs/api.md");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// ** recursive
// ---------------------------------------------------------------------------

TEST_CASE("Glob: **/*.cpp matches all cpp files recursively", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("**/*.cpp");
    REQUIRE(results.size() == 3);
    // sorted: src/lib/helper.cpp, src/main.cpp, src/util.cpp
    CHECK(results[0] == "src/lib/helper.cpp");
    CHECK(results[1] == "src/main.cpp");
    CHECK(results[2] == "src/util.cpp");

    fs::remove_all(path);
}

TEST_CASE("Glob: **/*.md matches all md files recursively", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("**/*.md");
    REQUIRE(results.size() == 2);
    CHECK(results[0] == "docs/api.md");
    CHECK(results[1] == "docs/guide.md");

    fs::remove_all(path);
}

TEST_CASE("Glob: ** matches all files recursively", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    // ** alone should match everything (except dotfiles)
    // But ** only matches directories — needs a trailing wildcard segment
    // Actually, per the Rust implementation, ** with no following segment
    // matches zero levels (no-op), so this should be empty.
    // Let me use **/* instead.
    auto results = snap.glob("**/*");
    // Should match all non-dotfile files: readme.txt, src/main.cpp,
    // src/util.cpp, src/lib/helper.h, src/lib/helper.cpp,
    // docs/guide.md, docs/api.md
    CHECK(results.size() == 7);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Dotfile handling
// ---------------------------------------------------------------------------

TEST_CASE("Glob: * does not match dotfiles", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("*");
    // Should match readme.txt only (not .hidden, not .config dir)
    CHECK(results.size() == 1);
    CHECK(results[0] == "readme.txt");

    fs::remove_all(path);
}

TEST_CASE("Glob: .* matches dotfiles explicitly", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob(".*");
    REQUIRE(results.size() == 1);
    CHECK(results[0] == ".hidden");

    fs::remove_all(path);
}

TEST_CASE("Glob: .config/* matches files in dotfile directory", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob(".config/*");
    REQUIRE(results.size() == 1);
    CHECK(results[0] == ".config/settings.json");

    fs::remove_all(path);
}

TEST_CASE("Glob: ** skips dotfile directories", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("**/*.json");
    // .config/settings.json should NOT be found because ** skips dotfile dirs
    CHECK(results.empty());

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// iglob returns unsorted
// ---------------------------------------------------------------------------

TEST_CASE("Glob: iglob returns same results as glob (possibly unsorted)", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto sorted = snap.glob("**/*.cpp");
    auto unsorted = snap.iglob("**/*.cpp");

    // Same elements
    auto sorted_copy = unsorted;
    std::sort(sorted_copy.begin(), sorted_copy.end());
    CHECK(sorted == sorted_copy);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

TEST_CASE("Glob: empty pattern returns nothing", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("");
    CHECK(results.empty());

    fs::remove_all(path);
}

TEST_CASE("Glob: literal path matches exact file", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("readme.txt");
    REQUIRE(results.size() == 1);
    CHECK(results[0] == "readme.txt");

    fs::remove_all(path);
}

TEST_CASE("Glob: no matches returns empty", "[glob]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = make_glob_fixture(store);

    auto results = snap.glob("*.xyz");
    CHECK(results.empty());

    fs::remove_all(path);
}
