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
