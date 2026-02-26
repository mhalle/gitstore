#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_mtest_" + std::to_string(
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

// ---------------------------------------------------------------------------
// move: basic rename
// ---------------------------------------------------------------------------

TEST_CASE("move: simple rename", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("old.txt", "data");

    snap = snap.move({"old.txt"}, "new.txt");
    CHECK(snap.read_text("new.txt") == "data");
    CHECK_FALSE(snap.exists("old.txt"));
    fs::remove_all(path);
}

TEST_CASE("move: into directory", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");
    snap = snap.write_text("dir/existing.txt", "existing");

    snap = snap.move({"file.txt"}, "dir");
    CHECK(snap.read_text("dir/file.txt") == "data");
    CHECK(snap.read_text("dir/existing.txt") == "existing");
    CHECK_FALSE(snap.exists("file.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: multiple sources
// ---------------------------------------------------------------------------

TEST_CASE("move: multiple files into directory", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("a.txt", "aaa");
    batch.write_text("b.txt", "bbb");
    batch.write_text("dest/placeholder.txt", "p");
    snap = batch.commit();

    snap = snap.move({"a.txt", "b.txt"}, "dest");
    CHECK(snap.read_text("dest/a.txt") == "aaa");
    CHECK(snap.read_text("dest/b.txt") == "bbb");
    CHECK_FALSE(snap.exists("a.txt"));
    CHECK_FALSE(snap.exists("b.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: directory
// ---------------------------------------------------------------------------

TEST_CASE("move: rename file to nested path", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    snap = snap.move({"file.txt"}, "sub/renamed.txt");
    CHECK(snap.read_text("sub/renamed.txt") == "data");
    CHECK_FALSE(snap.exists("file.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: dry run
// ---------------------------------------------------------------------------

TEST_CASE("move: dry run does not modify original", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    vost::MoveOptions mopts;
    mopts.dry_run = true;
    snap.move({"file.txt"}, "renamed.txt", mopts);

    // dry_run: original file still exists
    CHECK(snap.exists("file.txt"));
    // Re-read from store to confirm no commit happened
    auto snap2 = store.branches().get("main");
    CHECK(snap2.exists("file.txt"));
    CHECK_FALSE(snap2.exists("renamed.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: read-only rejection
// ---------------------------------------------------------------------------

TEST_CASE("move: read-only Fs throws", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    store.tags().set("v1", snap);
    auto tag_snap = store.tags().get("v1");

    REQUIRE_THROWS_AS(tag_snap.move({"file.txt"}, "new.txt"), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: preserves other files
// ---------------------------------------------------------------------------

TEST_CASE("move: preserves other files", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "aaa");
    snap = snap.write_text("other.txt", "other");

    snap = snap.move({"a.txt"}, "b.txt");
    CHECK_FALSE(snap.exists("a.txt"));
    CHECK(snap.read_text("b.txt") == "aaa");
    CHECK(snap.read_text("other.txt") == "other");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: directory recursive
// ---------------------------------------------------------------------------

TEST_CASE("move: directory recursive", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("src/a.txt", "a");
    snap = snap.write_text("src/sub/b.txt", "b");

    vost::MoveOptions opts;
    opts.recursive = true;
    snap = snap.move({"src"}, "dst", opts);
    CHECK_FALSE(snap.exists("src"));
    CHECK(snap.read_text("dst/a.txt") == "a");
    CHECK(snap.read_text("dst/sub/b.txt") == "b");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: dry_run reports correct paths
// ---------------------------------------------------------------------------

TEST_CASE("move: dry_run reports correct paths", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");
    snap = snap.write_text("b.txt", "other");

    vost::MoveOptions mopts;
    mopts.dry_run = true;
    auto result = snap.move({"a.txt"}, "renamed.txt", mopts);

    // Original unchanged
    CHECK(snap.exists("a.txt"));
    // No commit happened
    auto snap2 = store.branches().get("main");
    CHECK(snap2.exists("a.txt"));
    CHECK_FALSE(snap2.exists("renamed.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: error cases
// ---------------------------------------------------------------------------

TEST_CASE("move: nonexistent source throws", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("exists.txt", "data");

    REQUIRE_THROWS_AS(snap.move({"ghost.txt"}, "dest.txt"), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("move: directory without recursive throws", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("dir/file.txt", "content");

    REQUIRE_THROWS_AS(snap.move({"dir"}, "other"), vost::IsADirectoryError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move: custom message
// ---------------------------------------------------------------------------

TEST_CASE("move: custom commit message", "[move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    vost::MoveOptions mopts;
    mopts.message = "custom move message";
    snap = snap.move({"a.txt"}, "b.txt", mopts);

    CHECK(snap.message() == "custom move message");
    fs::remove_all(path);
}
