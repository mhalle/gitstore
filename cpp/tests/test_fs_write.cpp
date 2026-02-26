#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_wtest_" + std::to_string(
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
// write_text / write (bytes)
// ---------------------------------------------------------------------------

TEST_CASE("Fs: write_text creates a new commit", "[fs][write]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");
    auto snap2 = snap1.write_text("hello.txt", "world");

    CHECK(snap2.commit_hash() != snap1.commit_hash());
    CHECK(snap2.read_text("hello.txt") == "world");
    fs::remove_all(path);
}

TEST_CASE("Fs: write with raw bytes", "[fs][write]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    std::vector<uint8_t> data = {0x00, 0xFF, 0x42};
    snap = snap.write("bin.dat", data);

    auto back = snap.read("bin.dat");
    CHECK(back == data);
    fs::remove_all(path);
}

TEST_CASE("Fs: write with custom message", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions opts;
    opts.message = "custom commit message";
    snap = snap.write_text("f.txt", "content", opts);

    CHECK(snap.message() == "custom commit message");
    fs::remove_all(path);
}

TEST_CASE("Fs: write with executable mode", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions opts;
    opts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("script.sh", "#!/bin/bash\n", opts);

    CHECK(snap.file_type("script.sh") == vost::FileType::Executable);
    fs::remove_all(path);
}

TEST_CASE("Fs: write creates nested directories", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    snap = snap.write_text("a/b/c/file.txt", "deep");

    CHECK(snap.exists("a"));
    CHECK(snap.is_dir("a"));
    CHECK(snap.exists("a/b"));
    CHECK(snap.exists("a/b/c/file.txt"));
    CHECK(snap.read_text("a/b/c/file.txt") == "deep");
    fs::remove_all(path);
}

TEST_CASE("Fs: write updates branch HEAD", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    // Re-read from branch — should get latest
    auto latest = store.branches().get("main");
    CHECK(latest.read_text("f.txt") == "v2");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// write_symlink
// ---------------------------------------------------------------------------

TEST_CASE("Fs: write_symlink stores link target", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_symlink("link", "target.txt");

    CHECK(snap.file_type("link") == vost::FileType::Link);
    CHECK(snap.readlink("link") == "target.txt");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply
// ---------------------------------------------------------------------------

TEST_CASE("Fs: apply writes multiple files atomically", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes = {
        {"a.txt", vost::WriteEntry::from_text("hello")},
        {"b.txt", vost::WriteEntry::from_text("world")},
    };
    snap = snap.apply(writes);

    CHECK(snap.read_text("a.txt") == "hello");
    CHECK(snap.read_text("b.txt") == "world");
    fs::remove_all(path);
}

TEST_CASE("Fs: apply removes files atomically", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("todelete.txt", "gone");

    snap = snap.apply({}, {"todelete.txt"});
    CHECK_FALSE(snap.exists("todelete.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// remove
// ---------------------------------------------------------------------------

TEST_CASE("Fs: remove deletes a file", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("to_remove.txt", "bye");
    snap = snap.remove({"to_remove.txt"});

    CHECK_FALSE(snap.exists("to_remove.txt"));
    fs::remove_all(path);
}

TEST_CASE("Fs: remove multiple files", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");
    snap = snap.remove({"a.txt", "b.txt"});

    CHECK_FALSE(snap.exists("a.txt"));
    CHECK_FALSE(snap.exists("b.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// StaleSnapshotError
// ---------------------------------------------------------------------------

TEST_CASE("Fs: write throws StaleSnapshotError after concurrent write", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");

    // Advance the branch from another snapshot
    auto snap2 = snap1.write_text("x.txt", "from snap2");

    // snap1 is now stale — writing should fail
    REQUIRE_THROWS_AS(snap1.write_text("y.txt", "from snap1"),
                      vost::StaleSnapshotError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// PermissionError on read-only snapshots
// ---------------------------------------------------------------------------

TEST_CASE("Fs: write throws PermissionError on tag snapshot", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    // Create a tag
    store.tags().set("v1.0", snap);
    auto tag_snap = store.tags().get("v1.0");

    REQUIRE_THROWS_AS(tag_snap.write_text("g.txt", "illegal"),
                      vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Overwrite existing file
// ---------------------------------------------------------------------------

TEST_CASE("Fs: writing to existing path overwrites content", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("doc.txt", "v1");
    snap = snap.write_text("doc.txt", "v2");

    CHECK(snap.read_text("doc.txt") == "v2");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------------

TEST_CASE("Tags: set and get a tag", "[fs][write][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("release.txt", "1.0");

    store.tags().set("v1.0", snap);
    auto tag_snap = store.tags().get("v1.0");
    CHECK(tag_snap.read_text("release.txt") == "1.0");
    CHECK_FALSE(tag_snap.writable());
    fs::remove_all(path);
}

TEST_CASE("Tags: overwriting a tag throws KeyExistsError", "[fs][write][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    store.tags().set("v1.0", snap);

    snap = snap.write_text("f.txt", "v2");
    REQUIRE_THROWS_AS(store.tags().set("v1.0", snap), vost::KeyExistsError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// store.fs() — detached hash snapshot
// ---------------------------------------------------------------------------

TEST_CASE("GitStore::fs returns read-only snapshot for commit hash", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "hello");

    auto hash = *snap.commit_hash();
    auto detached = store.fs(hash);
    CHECK_FALSE(detached.writable());
    CHECK(detached.read_text("f.txt") == "hello");
    fs::remove_all(path);
}

TEST_CASE("GitStore::fs throws InvalidHashError for bad hash", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    REQUIRE_THROWS_AS(store.fs("notahex"), vost::InvalidHashError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Immutability of Fs snapshots
// ---------------------------------------------------------------------------

TEST_CASE("Fs: old snapshot is not modified by a later write", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");
    snap1 = snap1.write_text("data.txt", "v1");

    // snap1 still has "v1"; snap2 gets "v2"
    auto snap2 = snap1.write_text("data.txt", "v2");

    CHECK(snap1.read_text("data.txt") == "v1");
    CHECK(snap2.read_text("data.txt") == "v2");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict::set — create a branch
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: set creates a new branch pointing at a commit", "[fs][write][refdict]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "hello");

    store.branches().set("feature", snap);

    REQUIRE(store.branches().contains("feature"));
    auto feature = store.branches().get("feature");
    CHECK(feature.read_text("f.txt") == "hello");
    CHECK(*feature.commit_hash() == *snap.commit_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict::values
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: values returns all branch snapshots", "[fs][write][refdict]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("x.txt", "x");
    store.branches().set("dev", snap);

    auto vals = store.branches().values();
    REQUIRE(vals.size() == 2);
    std::vector<std::string> names;
    for (auto& v : vals) {
        REQUIRE(v.ref_name().has_value());
        names.push_back(*v.ref_name());
    }
    std::sort(names.begin(), names.end());
    CHECK(names[0] == "dev");
    CHECK(names[1] == "main");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Multiple branches hold independent data
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: two branches hold independent data", "[fs][write][refdict]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("shared.txt", "from main");

    // Create dev branch from main, then advance it independently
    store.branches().set("dev", main_snap);
    auto dev_snap = store.branches().get("dev");
    dev_snap = dev_snap.write_text("shared.txt", "from dev");

    // main is unchanged
    auto main_now = store.branches().get("main");
    CHECK(main_now.read_text("shared.txt") == "from main");
    CHECK(dev_snap.read_text("shared.txt") == "from dev");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Tags: keys / values
// ---------------------------------------------------------------------------

TEST_CASE("Tags: keys returns all tag names", "[fs][write][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    store.tags().set("v1.0", snap);
    snap = snap.write_text("f.txt", "v2");  // stale now but we just need another snap
    // Use store.branches().get() to avoid stale
    snap = store.branches().get("main");
    store.tags().set("v2.0", snap);

    auto tag_keys = store.tags().keys();
    REQUIRE(tag_keys.size() == 2);
    std::sort(tag_keys.begin(), tag_keys.end());
    CHECK(tag_keys[0] == "v1.0");
    CHECK(tag_keys[1] == "v2.0");
    fs::remove_all(path);
}

TEST_CASE("Tags: values returns read-only Fs snapshots", "[fs][write][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("r.txt", "release");
    store.tags().set("r1.0", snap);

    auto vals = store.tags().values();
    REQUIRE(vals.size() == 1);
    CHECK_FALSE(vals[0].writable());
    CHECK(vals[0].read_text("r.txt") == "release");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Detached Fs ref_name
// ---------------------------------------------------------------------------

TEST_CASE("Detached Fs: ref_name is nullopt", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    auto detached = store.fs(*snap.commit_hash());
    CHECK_FALSE(detached.ref_name().has_value());
    CHECK_FALSE(detached.writable());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Overwriting symlink with regular file
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// apply with combined writes AND removes
// ---------------------------------------------------------------------------

TEST_CASE("Fs: apply with combined writes and removes in single call", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("keep.txt", "kept");
    snap = snap.write_text("old.txt", "to remove");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes = {
        {"new.txt", vost::WriteEntry::from_text("added")},
    };
    snap = snap.apply(writes, {"old.txt"});

    CHECK(snap.read_text("keep.txt") == "kept");
    CHECK(snap.read_text("new.txt") == "added");
    CHECK_FALSE(snap.exists("old.txt"));
    fs::remove_all(path);
}

TEST_CASE("Fs: apply empty (no writes, no removes)", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    auto snap2 = snap.apply({}, {});
    // A new commit is created even though nothing changed
    CHECK(snap2.exists("f.txt"));
    CHECK(snap2.read_text("f.txt") == "data");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// remove edge cases
// ---------------------------------------------------------------------------

TEST_CASE("Fs: remove nonexistent path throws NotFoundError", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("exists.txt", "here");

    REQUIRE_THROWS_AS(snap.remove({"ghost.txt"}), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("Fs: remove directory non-recursive throws IsADirectoryError", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("dir/a.txt", "a");
    snap = snap.write_text("dir/b.txt", "b");

    REQUIRE_THROWS_AS(snap.remove({"dir"}), vost::IsADirectoryError);
    fs::remove_all(path);
}

TEST_CASE("Fs: remove directory with recursive=true", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("dir/a.txt", "a");
    snap = snap.write_text("dir/sub/b.txt", "b");
    snap = snap.write_text("keep.txt", "kept");

    vost::RemoveOptions opts;
    opts.recursive = true;
    snap = snap.remove({"dir"}, opts);

    CHECK_FALSE(snap.exists("dir"));
    CHECK_FALSE(snap.exists("dir/a.txt"));
    CHECK_FALSE(snap.exists("dir/sub/b.txt"));
    CHECK(snap.read_text("keep.txt") == "kept");
    fs::remove_all(path);
}

TEST_CASE("Fs: remove custom message via RemoveOptions", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    vost::RemoveOptions opts;
    opts.message = "custom remove message";
    snap = snap.remove({"f.txt"}, opts);

    CHECK(snap.message() == "custom remove message");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Path validation
// ---------------------------------------------------------------------------

TEST_CASE("Fs: path '..' throws InvalidPathError", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    REQUIRE_THROWS_AS(snap.write_text("..", "data"), vost::InvalidPathError);
    fs::remove_all(path);
}

TEST_CASE("Fs: path '.' throws InvalidPathError", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    REQUIRE_THROWS_AS(snap.write_text(".", "data"), vost::InvalidPathError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// rename
// ---------------------------------------------------------------------------

TEST_CASE("Fs: rename a file", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("old.txt", "data");

    snap = snap.rename("old.txt", "new.txt");
    CHECK_FALSE(snap.exists("old.txt"));
    CHECK(snap.read_text("new.txt") == "data");
    fs::remove_all(path);
}

TEST_CASE("Fs: rename a directory", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("src/a.txt", "a");
    snap = snap.write_text("src/b.txt", "b");

    snap = snap.rename("src", "dest");
    CHECK_FALSE(snap.exists("src/a.txt"));
    CHECK_FALSE(snap.exists("src/b.txt"));
    CHECK(snap.read_text("dest/a.txt") == "a");
    CHECK(snap.read_text("dest/b.txt") == "b");
    fs::remove_all(path);
}

TEST_CASE("Fs: rename nested directory", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a/b/c.txt", "deep");

    snap = snap.rename("a/b", "x/y");
    CHECK_FALSE(snap.exists("a/b/c.txt"));
    CHECK(snap.read_text("x/y/c.txt") == "deep");
    fs::remove_all(path);
}

TEST_CASE("Fs: rename missing source throws NotFoundError", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    REQUIRE_THROWS_AS(snap.rename("ghost.txt", "new.txt"), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("Fs: rename with custom message", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    vost::WriteOptions opts;
    opts.message = "custom rename msg";
    snap = snap.rename("f.txt", "g.txt", opts);
    CHECK(snap.message() == "custom rename msg");
    fs::remove_all(path);
}

TEST_CASE("Fs: rename preserves file mode", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions wopts;
    wopts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("script.sh", "#!/bin/sh", wopts);

    snap = snap.rename("script.sh", "run.sh");
    CHECK(snap.file_type("run.sh") == vost::FileType::Executable);
    fs::remove_all(path);
}

TEST_CASE("Fs: rename symlink preserves link", "[fs][write][rename]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_symlink("link", "target");

    snap = snap.rename("link", "alias");
    CHECK(snap.file_type("alias") == vost::FileType::Link);
    CHECK(snap.readlink("alias") == "target");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// retry_write
// ---------------------------------------------------------------------------

TEST_CASE("retry_write: succeeds on first try", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto result = vost::retry_write([&]() {
        return snap.write_text("f.txt", "data");
    });
    CHECK(result.read_text("f.txt") == "data");
    fs::remove_all(path);
}

TEST_CASE("retry_write: retries on StaleSnapshotError", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    int attempt = 0;

    auto result = vost::retry_write([&]() {
        auto snap = store.branches().get("main");
        ++attempt;
        if (attempt == 1) {
            // Advance the branch to make this attempt stale
            snap.write_text("advance.txt", "from concurrent");
        }
        return snap.write_text("f.txt", "attempt " + std::to_string(attempt));
    });
    CHECK(attempt >= 2);
    CHECK(result.read_text("f.txt").substr(0, 7) == "attempt");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

TEST_CASE("Fs: overwriting a symlink with a regular file changes file_type", "[fs][write]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_symlink("target", "somewhere");
    CHECK(snap.file_type("target") == vost::FileType::Link);

    snap = snap.write_text("target", "now a regular file");
    CHECK(snap.file_type("target") == vost::FileType::Blob);
    CHECK(snap.read_text("target") == "now a regular file");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// write_from_file
// ---------------------------------------------------------------------------

static void write_local_file(const fs::path& p, const std::string& content) {
    fs::create_directories(p.parent_path());
    std::ofstream ofs(p, std::ios::binary);
    ofs << content;
}

TEST_CASE("Fs: write_from_file reads local file into store", "[fs][write]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto tmp = fs::temp_directory_path() / "vost_wff_test";
    fs::create_directories(tmp);
    write_local_file(tmp / "hello.txt", "file content");

    snap = snap.write_from_file("hello.txt", tmp / "hello.txt");
    CHECK(snap.read_text("hello.txt") == "file content");

    fs::remove_all(path);
    fs::remove_all(tmp);
}

TEST_CASE("Fs: write_from_file with executable mode", "[fs][write]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto tmp = fs::temp_directory_path() / "vost_wff_exec_test";
    fs::create_directories(tmp);
    write_local_file(tmp / "run.sh", "#!/bin/bash\n");

    vost::WriteOptions opts;
    opts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_from_file("run.sh", tmp / "run.sh", opts);
    CHECK(snap.file_type("run.sh") == vost::FileType::Executable);
    CHECK(snap.read_text("run.sh") == "#!/bin/bash\n");

    fs::remove_all(path);
    fs::remove_all(tmp);
}

TEST_CASE("Fs: write_from_file throws IoError for missing file", "[fs][write]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(
        snap.write_from_file("f.txt", "/nonexistent/path/file.txt"),
        vost::IoError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// move
// ---------------------------------------------------------------------------

TEST_CASE("Fs: move single file rename", "[fs][write][move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("old.txt", "data");

    snap = snap.move({"old.txt"}, "new.txt");
    CHECK_FALSE(snap.exists("old.txt"));
    CHECK(snap.read_text("new.txt") == "data");
    fs::remove_all(path);
}

TEST_CASE("Fs: move multiple sources into directory", "[fs][write][move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "alpha");
    snap = snap.write_text("b.txt", "beta");
    snap = snap.write_text("dest/existing.txt", "exists");

    snap = snap.move({"a.txt", "b.txt"}, "dest");
    CHECK_FALSE(snap.exists("a.txt"));
    CHECK_FALSE(snap.exists("b.txt"));
    CHECK(snap.read_text("dest/a.txt") == "alpha");
    CHECK(snap.read_text("dest/b.txt") == "beta");
    CHECK(snap.read_text("dest/existing.txt") == "exists");
    fs::remove_all(path);
}

TEST_CASE("Fs: move directory recursive", "[fs][write][move]") {
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

TEST_CASE("Fs: move non-recursive directory throws", "[fs][write][move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("dir/file.txt", "content");

    REQUIRE_THROWS_AS(snap.move({"dir"}, "other"),
                      vost::IsADirectoryError);
    fs::remove_all(path);
}

TEST_CASE("Fs: move dry_run does not commit", "[fs][write][move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");
    auto hash_before = snap.commit_hash();

    vost::MoveOptions opts;
    opts.dry_run = true;
    auto result = snap.move({"f.txt"}, "g.txt", opts);
    CHECK(result.commit_hash() == hash_before);
    CHECK(snap.exists("f.txt")); // original unchanged
    fs::remove_all(path);
}

TEST_CASE("Fs: move non-existent source throws", "[fs][write][move]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("exists.txt", "data");

    REQUIRE_THROWS_AS(snap.move({"ghost.txt"}, "dest.txt"),
                      vost::NotFoundError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// FsWriter
// ---------------------------------------------------------------------------

TEST_CASE("FsWriter: accumulates writes and commits on close", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    vost::FsWriter w(snap, "data.txt");
    w.write("hello ");
    w.write("world");
    snap = w.close();

    CHECK(snap.read_text("data.txt") == "hello world");
    fs::remove_all(path);
}

TEST_CASE("FsWriter: binary data", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<uint8_t> chunk1 = {0x00, 0xFF};
    std::vector<uint8_t> chunk2 = {0x42, 0x43};
    vost::FsWriter w(snap, "bin.dat");
    w.write(chunk1);
    w.write(chunk2);
    snap = w.close();

    auto data = snap.read("bin.dat");
    REQUIRE(data.size() == 4);
    CHECK(data[0] == 0x00);
    CHECK(data[1] == 0xFF);
    CHECK(data[2] == 0x42);
    CHECK(data[3] == 0x43);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// FsWriter: text mode
// ---------------------------------------------------------------------------

TEST_CASE("FsWriter: text mode string writes", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    vost::FsWriter w(snap, "log.txt");
    w.write("line1\n");
    w.write("line2\n");
    snap = w.close();

    CHECK(snap.read_text("log.txt") == "line1\nline2\n");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// FsWriter: write after close throws
// ---------------------------------------------------------------------------

TEST_CASE("FsWriter: write after close throws", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    vost::FsWriter w(snap, "file.txt");
    w.write("data");
    w.close();

    REQUIRE_THROWS_AS(w.write("more"), vost::BatchClosedError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// FsWriter: readonly throws
// ---------------------------------------------------------------------------

TEST_CASE("FsWriter: readonly Fs throws PermissionError on close", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    store.tags().set("v1", snap);
    auto tag_snap = store.tags().get("v1");

    vost::FsWriter w(tag_snap, "file.txt");
    w.write("data");
    REQUIRE_THROWS_AS(w.close(), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// FsWriter: result is new commit
// ---------------------------------------------------------------------------

TEST_CASE("FsWriter: result is new commit with written data", "[fs][write][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    auto hash_before = snap.commit_hash();

    vost::FsWriter w(snap, "output.txt");
    w.write("hello");
    auto result = w.close();

    CHECK(result.commit_hash() != hash_before);
    CHECK(result.read_text("output.txt") == "hello");
    fs::remove_all(path);
}
