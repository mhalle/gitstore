#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_atest_" + std::to_string(
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
// apply: writes
// ---------------------------------------------------------------------------

TEST_CASE("apply: single write", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"hello.txt", vost::WriteEntry::from_text("world")});
    snap = snap.apply(writes);

    CHECK(snap.read_text("hello.txt") == "world");
    fs::remove_all(path);
}

TEST_CASE("apply: multiple writes", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"a.txt", vost::WriteEntry::from_text("aaa")});
    writes.push_back({"b.txt", vost::WriteEntry::from_text("bbb")});
    writes.push_back({"dir/c.txt", vost::WriteEntry::from_text("ccc")});
    snap = snap.apply(writes);

    CHECK(snap.read_text("a.txt") == "aaa");
    CHECK(snap.read_text("b.txt") == "bbb");
    CHECK(snap.read_text("dir/c.txt") == "ccc");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: writes + removes
// ---------------------------------------------------------------------------

TEST_CASE("apply: writes and removes combined", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    snap = snap.write_text("old.txt", "old");
    snap = snap.write_text("keep.txt", "keep");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"new.txt", vost::WriteEntry::from_text("new")});

    std::vector<std::string> removes = {"old.txt"};
    snap = snap.apply(writes, removes);

    CHECK(snap.read_text("new.txt") == "new");
    CHECK(snap.read_text("keep.txt") == "keep");
    CHECK_FALSE(snap.exists("old.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: changes report
// ---------------------------------------------------------------------------

TEST_CASE("apply: write new and overwrite existing", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    snap = snap.write_text("existing.txt", "v1");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"existing.txt", vost::WriteEntry::from_text("v2")});
    writes.push_back({"brand_new.txt", vost::WriteEntry::from_text("new")});
    snap = snap.apply(writes);

    CHECK(snap.read_text("existing.txt") == "v2");
    CHECK(snap.read_text("brand_new.txt") == "new");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: custom message
// ---------------------------------------------------------------------------

TEST_CASE("apply: custom message", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"file.txt", vost::WriteEntry::from_text("data")});

    vost::ApplyOptions opts;
    opts.message = "Custom apply message";
    snap = snap.apply(writes, {}, opts);

    CHECK(snap.message() == "Custom apply message");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: read-only rejection
// ---------------------------------------------------------------------------

TEST_CASE("apply: read-only Fs throws", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    store.tags().set("v1", snap);
    auto tag_snap = store.tags().get("v1");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"new.txt", vost::WriteEntry::from_text("nope")});
    REQUIRE_THROWS_AS(tag_snap.apply(writes), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: symlink
// ---------------------------------------------------------------------------

TEST_CASE("apply: symlink entry", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("target.txt", "data");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"link.txt", vost::WriteEntry::symlink("target.txt")});
    snap = snap.apply(writes);

    auto ft = snap.file_type("link.txt");
    CHECK(ft == vost::FileType::Link);
    CHECK(snap.readlink("link.txt") == "target.txt");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: executable mode via WriteEntry
// ---------------------------------------------------------------------------

TEST_CASE("apply: executable mode via WriteEntry", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    std::string text = "#!/bin/sh";
    std::vector<uint8_t> data(text.begin(), text.end());
    writes.push_back({"script.sh", vost::WriteEntry{std::move(data), std::nullopt, vost::MODE_BLOB_EXEC}});
    snap = snap.apply(writes);

    CHECK(snap.file_type("script.sh") == vost::FileType::Executable);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: removes
// ---------------------------------------------------------------------------

TEST_CASE("apply: remove single file", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");

    snap = snap.apply({}, {"a.txt"});
    CHECK_FALSE(snap.exists("a.txt"));
    CHECK(snap.exists("b.txt"));
    fs::remove_all(path);
}

TEST_CASE("apply: remove multiple files", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");
    snap = snap.write_text("c.txt", "c");

    snap = snap.apply({}, {"a.txt", "b.txt"});
    CHECK_FALSE(snap.exists("a.txt"));
    CHECK_FALSE(snap.exists("b.txt"));
    CHECK(snap.exists("c.txt"));
    fs::remove_all(path);
}

TEST_CASE("apply: null removes are noop", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    // Apply with empty writes and empty removes
    snap = snap.apply({}, {});
    CHECK(snap.exists("file.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: StaleSnapshotError
// ---------------------------------------------------------------------------

TEST_CASE("apply: stale snapshot throws", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");
    auto snap2 = store.branches().get("main");

    // Advance branch via snap1
    snap1.write_text("x.txt", "advance");

    // snap2 is now stale
    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"y.txt", vost::WriteEntry::from_text("data")});
    REQUIRE_THROWS_AS(snap2.apply(writes), vost::StaleSnapshotError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: verifies content after add, update, delete
// ---------------------------------------------------------------------------

TEST_CASE("apply: add new file is readable", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"new.txt", vost::WriteEntry::from_text("new")});
    snap = snap.apply(writes);

    CHECK(snap.exists("new.txt"));
    CHECK(snap.read_text("new.txt") == "new");
    fs::remove_all(path);
}

TEST_CASE("apply: update existing file changes content", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "v1");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"file.txt", vost::WriteEntry::from_text("v2")});
    snap = snap.apply(writes);

    CHECK(snap.read_text("file.txt") == "v2");
    fs::remove_all(path);
}

TEST_CASE("apply: delete removes file", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    snap = snap.apply({}, {"file.txt"});

    CHECK_FALSE(snap.exists("file.txt"));
    fs::remove_all(path);
}

TEST_CASE("apply: combined add update delete", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("existing.txt", "old");
    snap = snap.write_text("remove_me.txt", "gone");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"existing.txt", vost::WriteEntry::from_text("updated")});
    writes.push_back({"brand_new.txt", vost::WriteEntry::from_text("new")});
    snap = snap.apply(writes, {"remove_me.txt"});

    CHECK(snap.read_text("existing.txt") == "updated");
    CHECK(snap.read_text("brand_new.txt") == "new");
    CHECK_FALSE(snap.exists("remove_me.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: identical write is noop
// ---------------------------------------------------------------------------

TEST_CASE("apply: identical write preserves tree hash", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");
    auto tree_before = snap.tree_hash();

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"file.txt", vost::WriteEntry::from_text("data")});
    snap = snap.apply(writes);

    CHECK(snap.tree_hash() == tree_before);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// apply: operation keyword
// ---------------------------------------------------------------------------

TEST_CASE("apply: operation keyword in message", "[apply]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    std::vector<std::pair<std::string, vost::WriteEntry>> writes;
    writes.push_back({"file.txt", vost::WriteEntry::from_text("data")});

    vost::ApplyOptions opts;
    opts.operation = "import";
    snap = snap.apply(writes, {}, opts);

    auto msg = snap.message();
    // format_message returns just the operation when no custom message
    CHECK(msg.substr(0, 6) == "import");
    fs::remove_all(path);
}
