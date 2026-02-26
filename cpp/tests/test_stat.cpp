#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_stest_" + std::to_string(
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
// stat on files
// ---------------------------------------------------------------------------

TEST_CASE("stat: regular file", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("hello.txt", "world");

    auto st = snap.stat("hello.txt");
    CHECK(st.file_type == vost::FileType::Blob);
    CHECK(st.mode == vost::MODE_BLOB);
    CHECK(st.size == 5);  // "world"
    CHECK(st.hash.size() == 40);
    CHECK(st.nlink == 1);
    CHECK(st.mtime > 0);

    fs::remove_all(path);
}

TEST_CASE("stat: executable file", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    vost::WriteOptions wopts;
    wopts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("run.sh", "#!/bin/sh", wopts);

    auto st = snap.stat("run.sh");
    CHECK(st.file_type == vost::FileType::Executable);
    CHECK(st.mode == vost::MODE_BLOB_EXEC);
    CHECK(st.nlink == 1);

    fs::remove_all(path);
}

TEST_CASE("stat: symlink", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("target.txt", "data");
    snap = snap.write_symlink("link.txt", "target.txt");

    auto st = snap.stat("link.txt");
    CHECK(st.file_type == vost::FileType::Link);
    CHECK(st.mode == vost::MODE_LINK);
    CHECK(st.nlink == 1);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// stat on directories
// ---------------------------------------------------------------------------

TEST_CASE("stat: directory", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("dir/file.txt", "data");

    auto st = snap.stat("dir");
    CHECK(st.file_type == vost::FileType::Tree);
    CHECK(st.mode == vost::MODE_TREE);
    CHECK(st.nlink >= 2);  // at least 2 for a directory

    fs::remove_all(path);
}

TEST_CASE("stat: root directory", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto st = snap.stat();  // root
    CHECK(st.file_type == vost::FileType::Tree);
    CHECK(st.nlink >= 2);

    fs::remove_all(path);
}

TEST_CASE("stat: nlink counts subdirs", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("sub1/a.txt", "a");
    batch.write_text("sub2/b.txt", "b");
    batch.write_text("top.txt", "t");
    snap = batch.commit();

    auto st = snap.stat();
    // nlink = 2 + number of subdirectories (2)
    CHECK(st.nlink == 4);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// stat: error cases
// ---------------------------------------------------------------------------

TEST_CASE("stat: nonexistent path throws", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    REQUIRE_THROWS_AS(snap.stat("nope.txt"), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("stat: hash is consistent across calls", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto st1 = snap.stat("file.txt");
    auto st2 = snap.stat("file.txt");
    CHECK(st1.hash == st2.hash);

    fs::remove_all(path);
}
