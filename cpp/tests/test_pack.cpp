#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <chrono>
#include <filesystem>
#include <thread>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_pack_" + std::to_string(
                    std::hash<std::thread::id>{}(std::this_thread::get_id())
                    ^ static_cast<size_t>(
                          std::chrono::steady_clock::now()
                              .time_since_epoch()
                              .count())));
    return tmp;
}

static vost::GitStore open_store(const fs::path& path) {
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    return vost::GitStore::open(path, opts);
}

TEST_CASE("pack returns count", "[pack]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write("a.txt", {'a', 'a', 'a'});
    snap = snap.write("b.txt", {'b', 'b', 'b'});
    auto count = store.pack();
    CHECK(count > 0);
    fs::remove_all(path);
}

TEST_CASE("pack preserves data", "[pack]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write("a.txt", {'h', 'e', 'l', 'l', 'o'});
    snap = snap.write("b.txt", {'w', 'o', 'r', 'l', 'd'});
    store.pack();
    auto snap2 = store.branches()["main"];
    CHECK(snap2.read("a.txt") == std::vector<uint8_t>({'h', 'e', 'l', 'l', 'o'}));
    CHECK(snap2.read("b.txt") == std::vector<uint8_t>({'w', 'o', 'r', 'l', 'd'}));
    fs::remove_all(path);
}

TEST_CASE("gc returns count", "[pack]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write("a.txt", {'a', 'a', 'a'});
    auto count = store.gc();
    CHECK(count > 0);
    fs::remove_all(path);
}

TEST_CASE("gc preserves data", "[pack]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write("a.txt", {'h', 'e', 'l', 'l', 'o'});
    store.gc();
    auto snap2 = store.branches()["main"];
    CHECK(snap2.read("a.txt") == std::vector<uint8_t>({'h', 'e', 'l', 'l', 'o'}));
    fs::remove_all(path);
}
