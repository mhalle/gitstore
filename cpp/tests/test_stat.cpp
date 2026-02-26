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

// ---------------------------------------------------------------------------
// stat: size matches content length
// ---------------------------------------------------------------------------

TEST_CASE("stat: size matches content length", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    std::string content = "Hello, World! This is a longer string.";
    snap = snap.write_text("file.txt", content);

    auto st = snap.stat("file.txt");
    CHECK(st.size == static_cast<uint64_t>(content.size()));

    fs::remove_all(path);
}

TEST_CASE("stat: symlink size is target path length", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_symlink("link", "target.txt");

    auto st = snap.stat("link");
    CHECK(st.size == static_cast<uint64_t>(std::string("target.txt").size()));

    fs::remove_all(path);
}

TEST_CASE("stat: nlink for leaf directory (no subdirs)", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("dir/a.txt", "a");
    snap = snap.write_text("dir/b.txt", "b");

    auto st = snap.stat("dir");
    // Leaf dir: nlink = 2 (self + parent)
    CHECK(st.nlink == 2);

    fs::remove_all(path);
}

TEST_CASE("stat: mtime consistency across calls", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto st1 = snap.stat("file.txt");
    auto st2 = snap.stat("file.txt");
    CHECK(st1.mtime == st2.mtime);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// listdir
// ---------------------------------------------------------------------------

TEST_CASE("stat: listdir names match ls", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");
    snap = snap.write_text("dir/c.txt", "c");

    auto ls_names = snap.ls();
    auto listdir_entries = snap.listdir();

    std::vector<std::string> listdir_names;
    for (auto& e : listdir_entries) {
        listdir_names.push_back(e.name);
    }
    std::sort(ls_names.begin(), ls_names.end());
    std::sort(listdir_names.begin(), listdir_names.end());
    CHECK(ls_names == listdir_names);

    fs::remove_all(path);
}

TEST_CASE("stat: listdir returns WalkEntry with correct types", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");
    snap = snap.write_text("dir/inner.txt", "inner");

    auto entries = snap.listdir();
    bool found_file = false;
    bool found_dir = false;
    for (auto& e : entries) {
        if (e.name == "file.txt") {
            CHECK(e.mode == vost::MODE_BLOB);
            found_file = true;
        }
        if (e.name == "dir") {
            CHECK(e.mode == vost::MODE_TREE);
            found_dir = true;
        }
    }
    CHECK(found_file);
    CHECK(found_dir);

    fs::remove_all(path);
}

TEST_CASE("stat: listdir on file throws", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    REQUIRE_THROWS_AS(snap.listdir("file.txt"), vost::NotADirectoryError);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// tree_hash
// ---------------------------------------------------------------------------

TEST_CASE("stat: tree_hash is 40-char hex", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto th = snap.tree_hash();
    REQUIRE(th.has_value());
    CHECK(th->size() == 40);

    fs::remove_all(path);
}

TEST_CASE("stat: tree_hash changes on write", "[stat]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "v1");
    auto hash1 = snap.tree_hash();

    snap = snap.write_text("file.txt", "v2");
    auto hash2 = snap.tree_hash();

    CHECK(hash1 != hash2);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read range
// ---------------------------------------------------------------------------

TEST_CASE("stat: read_range with offset only", "[stat][read_range]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "Hello World");

    auto data = snap.read_range("file.txt", 6);
    std::string result(data.begin(), data.end());
    CHECK(result == "World");

    fs::remove_all(path);
}

TEST_CASE("stat: read_range with offset and size", "[stat][read_range]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "abcdefghij");

    auto data = snap.read_range("file.txt", 3, 4);
    std::string result(data.begin(), data.end());
    CHECK(result == "defg");

    fs::remove_all(path);
}

TEST_CASE("stat: read_range beyond end is clamped", "[stat][read_range]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "short");

    auto data = snap.read_range("file.txt", 2, 100);
    std::string result(data.begin(), data.end());
    CHECK(result == "ort");

    fs::remove_all(path);
}

TEST_CASE("stat: read_range zero size returns empty", "[stat][read_range]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto data = snap.read_range("file.txt", 0, 0);
    CHECK(data.empty());

    fs::remove_all(path);
}

TEST_CASE("stat: read_range with offset at end returns empty", "[stat][read_range]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto data = snap.read_range("file.txt", 100);
    CHECK(data.empty());

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read_by_hash
// ---------------------------------------------------------------------------

TEST_CASE("stat: read_by_hash roundtrip", "[stat][read_by_hash]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "content");

    auto hash = snap.stat("file.txt").hash;
    auto data = snap.read_by_hash(hash);
    std::string result(data.begin(), data.end());
    CHECK(result == "content");

    fs::remove_all(path);
}

TEST_CASE("stat: read_by_hash with range", "[stat][read_by_hash]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "Hello World");

    auto hash = snap.stat("file.txt").hash;
    auto data = snap.read_by_hash(hash, 6, 5);
    std::string result(data.begin(), data.end());
    CHECK(result == "World");

    fs::remove_all(path);
}
