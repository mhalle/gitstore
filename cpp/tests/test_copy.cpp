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
               ("vost_ctest_" + std::to_string(
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

/// Create a temp directory with some files for copy tests.
static fs::path make_src_dir() {
    auto dir = fs::temp_directory_path() /
               ("vost_src_" + std::to_string(
                    std::hash<std::thread::id>{}(std::this_thread::get_id())
                    ^ static_cast<size_t>(
                          std::chrono::steady_clock::now()
                              .time_since_epoch()
                              .count())));
    fs::create_directories(dir);
    return dir;
}

static void write_file(const fs::path& p, const std::string& content) {
    fs::create_directories(p.parent_path());
    std::ofstream ofs(p, std::ios::binary);
    ofs << content;
}

// ---------------------------------------------------------------------------
// copy_in tests
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_in basic", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "hello.txt", "hello");
    write_file(src / "sub" / "deep.txt", "deep");

    auto [report, new_snap] = snap.copy_in(src);
    CHECK(report.add.size() == 2);
    CHECK(new_snap.read_text("hello.txt") == "hello");
    CHECK(new_snap.read_text("sub/deep.txt") == "deep");

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Copy: copy_in with dest prefix", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "a.txt", "alpha");

    auto [report, new_snap] = snap.copy_in(src, "imported");
    CHECK(new_snap.read_text("imported/a.txt") == "alpha");
    CHECK(report.add.size() == 1);
    CHECK(report.add[0].path == "imported/a.txt");

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Copy: copy_in with include filter", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "keep.txt", "yes");
    write_file(src / "skip.md", "no");

    vost::CopyInOptions opts;
    opts.include = std::vector<std::string>{"*.txt"};
    auto [report, new_snap] = snap.copy_in(src, "", opts);
    CHECK(report.add.size() == 1);
    CHECK(new_snap.exists("keep.txt"));
    CHECK(!new_snap.exists("skip.md"));

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Copy: copy_in with exclude filter", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "keep.txt", "yes");
    write_file(src / "skip.tmp", "no");

    vost::CopyInOptions opts;
    opts.exclude = std::vector<std::string>{"*.tmp"};
    auto [report, new_snap] = snap.copy_in(src, "", opts);
    CHECK(report.add.size() == 1);
    CHECK(new_snap.exists("keep.txt"));
    CHECK(!new_snap.exists("skip.tmp"));

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Copy: copy_in checksum skips unchanged", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "f.txt", "content");

    // First copy_in
    auto [r1, snap2] = snap.copy_in(src);
    CHECK(r1.add.size() == 1);

    // Second copy_in (same content) — should skip
    auto [r2, snap3] = snap2.copy_in(src);
    CHECK(r2.add.empty());
    // commit_hash should be same (no new commit)
    CHECK(snap2.commit_hash() == snap3.commit_hash());

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Copy: copy_in dry_run does not commit", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "f.txt", "content");

    vost::CopyInOptions opts;
    opts.dry_run = true;
    auto [report, new_snap] = snap.copy_in(src, "", opts);
    CHECK(report.add.size() == 1);
    // Snapshot should be unchanged
    CHECK(snap.commit_hash() == new_snap.commit_hash());

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

// ---------------------------------------------------------------------------
// copy_out tests
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_out basic", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("hello.txt", "hello world");
    snap = snap.write_text("sub/note.txt", "note");

    auto dest = make_src_dir();
    auto report = snap.copy_out("", dest);
    CHECK(report.add.size() == 2);

    // Read back from disk
    std::ifstream ifs1(dest / "hello.txt");
    std::string content1((std::istreambuf_iterator<char>(ifs1)),
                          std::istreambuf_iterator<char>());
    CHECK(content1 == "hello world");

    std::ifstream ifs2(dest / "sub" / "note.txt");
    std::string content2((std::istreambuf_iterator<char>(ifs2)),
                          std::istreambuf_iterator<char>());
    CHECK(content2 == "note");

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

TEST_CASE("Copy: copy_out subdirectory", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("top.txt", "top");
    snap = snap.write_text("dir/a.txt", "a");
    snap = snap.write_text("dir/b.txt", "b");

    auto dest = make_src_dir();
    auto report = snap.copy_out("dir", dest);
    CHECK(report.add.size() == 2);
    CHECK(fs::exists(dest / "a.txt"));
    CHECK(fs::exists(dest / "b.txt"));
    CHECK(!fs::exists(dest / "top.txt"));

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

TEST_CASE("Copy: copy_out with filter", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.md", "b");

    auto dest = make_src_dir();
    vost::CopyOutOptions opts;
    opts.include = std::vector<std::string>{"*.txt"};
    auto report = snap.copy_out("", dest, opts);
    CHECK(report.add.size() == 1);
    CHECK(fs::exists(dest / "a.txt"));
    CHECK(!fs::exists(dest / "b.md"));

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

// ---------------------------------------------------------------------------
// sync_in tests
// ---------------------------------------------------------------------------

TEST_CASE("Sync: sync_in detects add/update/delete", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    // Initial: put some files in repo
    snap = snap.write_text("keep.txt", "old");
    snap = snap.write_text("gone.txt", "delete me");

    // Create disk source: keep.txt (updated), new.txt (added)
    auto src = make_src_dir();
    write_file(src / "keep.txt", "updated");
    write_file(src / "new.txt", "fresh");

    auto [report, new_snap] = snap.sync_in(src);
    CHECK(!report.add.empty());   // new.txt
    CHECK(!report.update.empty()); // keep.txt
    CHECK(!report.del.empty());   // gone.txt

    CHECK(new_snap.read_text("keep.txt") == "updated");
    CHECK(new_snap.read_text("new.txt") == "fresh");
    CHECK(!new_snap.exists("gone.txt"));

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

TEST_CASE("Sync: sync_in with checksum skips unchanged", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "f.txt", "same");

    auto [r1, snap2] = snap.sync_in(src);
    CHECK(r1.add.size() == 1);

    // sync again (same content)
    auto [r2, snap3] = snap2.sync_in(src);
    CHECK(r2.in_sync());
    CHECK(snap2.commit_hash() == snap3.commit_hash());

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

// ---------------------------------------------------------------------------
// sync_out tests
// ---------------------------------------------------------------------------

TEST_CASE("Sync: sync_out removes extra local files", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");

    auto dest = make_src_dir();
    // Pre-populate dest with an extra file
    write_file(dest / "a.txt", "old");
    write_file(dest / "extra.txt", "extra");

    auto report = snap.sync_out("", dest);
    CHECK(!report.add.empty());   // a.txt was written
    CHECK(!report.del.empty());   // extra.txt was deleted

    CHECK(fs::exists(dest / "a.txt"));
    CHECK(!fs::exists(dest / "extra.txt"));

    // Verify content
    std::ifstream ifs(dest / "a.txt");
    std::string content((std::istreambuf_iterator<char>(ifs)),
                         std::istreambuf_iterator<char>());
    CHECK(content == "a");

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

TEST_CASE("Sync: sync_out prunes empty directories", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("root.txt", "r");

    auto dest = make_src_dir();
    // Create an extra nested directory
    write_file(dest / "sub" / "extra.txt", "extra");

    auto report = snap.sync_out("", dest);
    CHECK(!fs::exists(dest / "sub" / "extra.txt"));
    CHECK(!fs::exists(dest / "sub")); // dir should be pruned

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

// ---------------------------------------------------------------------------
// Roundtrip test
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_in then copy_out roundtrip", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    // Create source
    auto src = make_src_dir();
    write_file(src / "a.txt", "alpha");
    write_file(src / "sub" / "b.txt", "beta");

    // copy_in
    auto [r1, snap2] = snap.copy_in(src);
    CHECK(r1.add.size() == 2);

    // copy_out to different directory
    auto dest = make_src_dir();
    auto r2 = snap2.copy_out("", dest);
    CHECK(r2.add.size() == 2);

    // Verify roundtrip
    std::ifstream ifs1(dest / "a.txt");
    std::string c1((std::istreambuf_iterator<char>(ifs1)),
                    std::istreambuf_iterator<char>());
    CHECK(c1 == "alpha");

    std::ifstream ifs2(dest / "sub" / "b.txt");
    std::string c2((std::istreambuf_iterator<char>(ifs2)),
                    std::istreambuf_iterator<char>());
    CHECK(c2 == "beta");

    fs::remove_all(repo_path);
    fs::remove_all(src);
    fs::remove_all(dest);
}

// ---------------------------------------------------------------------------
// copy_from_ref tests
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref basic cross-branch copy", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("a.txt", "alpha");
    main_snap = main_snap.write_text("b.txt", "beta");

    // Create dev branch
    auto dev = store.branches().set_and_get("dev", main_snap);
    dev = dev.write_text("c.txt", "gamma");

    // Copy from dev to main
    main_snap = store.branches().get("main");
    main_snap = main_snap.copy_from_ref(dev, {"c.txt"}, "");
    CHECK(main_snap.read_text("c.txt") == "gamma");
    CHECK(main_snap.read_text("a.txt") == "alpha");

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref directory copy", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("src/a.txt", "a");
    snap = snap.write_text("src/b.txt", "b");

    store.branches().set("dev", snap);
    auto dev = store.branches().get("dev");
    dev = dev.write_text("data/x.txt", "x");
    dev = dev.write_text("data/y.txt", "y");

    // Copy data/ from dev to main under "imported"
    snap = store.branches().get("main");
    snap = snap.copy_from_ref(dev, {"data/"}, "imported");
    CHECK(snap.read_text("imported/x.txt") == "x");
    CHECK(snap.read_text("imported/y.txt") == "y");

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref with delete_extra", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("extra.txt", "extra");

    store.branches().set("dev", snap);
    auto dev = store.branches().get("dev");
    dev = dev.remove({"extra.txt"});
    dev = dev.write_text("a.txt", "updated a");

    snap = store.branches().get("main");
    vost::CopyFromRefOptions opts;
    opts.delete_extra = true;
    snap = snap.copy_from_ref(dev, {""}, "", opts);
    CHECK(snap.read_text("a.txt") == "updated a");
    CHECK_FALSE(snap.exists("extra.txt"));

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref dry_run", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");

    store.branches().set("dev", snap);
    auto dev = store.branches().get("dev");
    dev = dev.write_text("new.txt", "new");

    snap = store.branches().get("main");
    auto hash_before = snap.commit_hash();
    vost::CopyFromRefOptions opts;
    opts.dry_run = true;
    auto result = snap.copy_from_ref(dev, {"new.txt"}, "", opts);
    CHECK(result.commit_hash() == hash_before);

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref non-existent source throws", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    store.branches().set("dev", snap);
    auto dev = store.branches().get("dev");

    REQUIRE_THROWS_AS(snap.copy_from_ref(dev, {"ghost.txt"}, ""),
                      vost::NotFoundError);

    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// ExcludeFilter tests
// ---------------------------------------------------------------------------

TEST_CASE("ExcludeFilter: basic pattern matching", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"*.log", "build/"});

    CHECK(filter.is_excluded("test.log"));
    CHECK(filter.is_excluded("sub/debug.log"));
    CHECK(filter.is_excluded("build", true)); // dir_only pattern
    CHECK_FALSE(filter.is_excluded("build", false)); // not a dir
    CHECK_FALSE(filter.is_excluded("readme.txt"));
}

TEST_CASE("ExcludeFilter: negation patterns", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"*.log", "!important.log"});

    CHECK(filter.is_excluded("debug.log"));
    CHECK_FALSE(filter.is_excluded("important.log"));
}

TEST_CASE("ExcludeFilter: comments and empty lines ignored", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"# this is a comment", "", "*.tmp"});

    CHECK(filter.is_excluded("test.tmp"));
    CHECK_FALSE(filter.is_excluded("# this is a comment"));
    CHECK(filter.active());
}

TEST_CASE("ExcludeFilter: load_from_file", "[exclude]") {
    auto tmp = fs::temp_directory_path() / "vost_exclude_test";
    fs::create_directories(tmp);
    {
        std::ofstream ofs(tmp / ".gitignore");
        ofs << "*.pyc\n__pycache__/\n";
    }

    vost::ExcludeFilter filter;
    filter.load_from_file(tmp / ".gitignore");

    CHECK(filter.is_excluded("test.pyc"));
    CHECK(filter.is_excluded("__pycache__", true));
    CHECK_FALSE(filter.is_excluded("main.py"));

    fs::remove_all(tmp);
}

TEST_CASE("ExcludeFilter: inactive when empty", "[exclude]") {
    vost::ExcludeFilter filter;
    CHECK_FALSE(filter.active());
    CHECK_FALSE(filter.is_excluded("anything.txt"));
}

// ---------------------------------------------------------------------------
// copy_in: empty file
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_in empty file", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "empty.txt", "");

    auto [report, new_snap] = snap.copy_in(src);
    CHECK(new_snap.exists("empty.txt"));
    CHECK(new_snap.read_text("empty.txt") == "");

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

// ---------------------------------------------------------------------------
// copy_in: binary data
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_in binary data", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    {
        std::ofstream ofs(src / "data.bin", std::ios::binary);
        char bytes[] = {0x00, static_cast<char>(0xFF), 0x42};
        ofs.write(bytes, 3);
    }

    auto [report, new_snap] = snap.copy_in(src);
    auto data = new_snap.read("data.bin");
    REQUIRE(data.size() == 3);
    CHECK(data[0] == 0x00);
    CHECK(data[1] == 0xFF);
    CHECK(data[2] == 0x42);

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

// ---------------------------------------------------------------------------
// copy_out: missing throws
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_out nonexistent source throws", "[copy]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    auto dest = make_src_dir();
    REQUIRE_THROWS_AS(snap.copy_out("nonexistent", dest), vost::NotFoundError);

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

// ---------------------------------------------------------------------------
// sync_in: idempotent
// ---------------------------------------------------------------------------

TEST_CASE("Sync: sync_in is idempotent", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    auto src = make_src_dir();
    write_file(src / "file.txt", "content");

    auto [r1, snap2] = snap.sync_in(src);
    CHECK(r1.add.size() == 1);

    // Second sync with identical content
    auto [r2, snap3] = snap2.sync_in(src);
    CHECK(r2.in_sync());
    CHECK(snap2.commit_hash() == snap3.commit_hash());

    fs::remove_all(repo_path);
    fs::remove_all(src);
}

// ---------------------------------------------------------------------------
// sync_out: prunes empty dirs
// ---------------------------------------------------------------------------

TEST_CASE("Sync: sync_out prunes nested empty directories", "[sync]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("keep.txt", "kept");

    auto dest = make_src_dir();
    // Create deep extra directory
    write_file(dest / "a" / "b" / "extra.txt", "extra");

    snap.sync_out("", dest);
    CHECK_FALSE(fs::exists(dest / "a" / "b" / "extra.txt"));
    CHECK_FALSE(fs::exists(dest / "a" / "b"));
    CHECK_FALSE(fs::exists(dest / "a"));

    fs::remove_all(repo_path);
    fs::remove_all(dest);
}

// ---------------------------------------------------------------------------
// copy_from_ref: contents mode
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref contents mode trailing slash", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("dir/a.txt", "a");
    snap = snap.write_text("dir/b.txt", "b");

    auto dev = store.branches().set_and_get("dev", snap);
    dev = dev.write_text("other.txt", "other");

    snap = store.branches().get("main");
    snap = snap.copy_from_ref(dev, {"dir/"}, "imported");
    CHECK(snap.read_text("imported/a.txt") == "a");
    CHECK(snap.read_text("imported/b.txt") == "b");

    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// copy_from_ref: stale error
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref stale snapshot throws", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    auto dev = store.branches().set_and_get("dev", snap);

    // Advance main to make snap stale
    auto fresh = store.branches().get("main");
    fresh.write_text("advance.txt", "advance");

    // snap is now stale
    REQUIRE_THROWS_AS(snap.copy_from_ref(dev, {"a.txt"}, ""),
                      vost::StaleSnapshotError);
    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// copy_from_ref: readonly dest throws
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref readonly dest throws", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    store.tags().set("v1", snap);
    auto tag_snap = store.tags().get("v1");

    REQUIRE_THROWS_AS(tag_snap.copy_from_ref(snap, {"a.txt"}, ""),
                      vost::PermissionError);
    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// copy_from_ref: custom message
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref custom message", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    auto dev = store.branches().set_and_get("dev", snap);
    dev = dev.write_text("new.txt", "new");

    snap = store.branches().get("main");
    vost::CopyFromRefOptions opts;
    opts.message = "custom copy message";
    snap = snap.copy_from_ref(dev, {"new.txt"}, "", opts);

    CHECK(snap.message() == "custom copy message");
    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// copy_from_ref: noop when identical
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref identical content preserves tree", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "data");

    auto dev = store.branches().set_and_get("dev", snap);

    snap = store.branches().get("main");
    auto tree_before = snap.tree_hash();
    snap = snap.copy_from_ref(dev);
    // Identical content — tree hash should be the same
    CHECK(snap.tree_hash() == tree_before);

    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// copy_from_ref: preserves executable mode
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref preserves executable mode", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto snap = store.branches().get("main");

    vost::WriteOptions wopts;
    wopts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("script.sh", "#!/bin/sh", wopts);

    auto dev = store.branches().set_and_get("dev", snap);

    auto dest = store.branches().set_and_get("dest", snap);
    dest = dest.remove({"script.sh"});
    dest = dest.copy_from_ref(dev, {"script.sh"}, "");
    CHECK(dest.file_type("script.sh") == vost::FileType::Executable);

    fs::remove_all(repo_path);
}

// ---------------------------------------------------------------------------
// ExcludeFilter: more patterns
// ---------------------------------------------------------------------------

TEST_CASE("ExcludeFilter: double star pattern in subdirs", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"**/*.log"});

    CHECK(filter.is_excluded("sub/dir/error.log"));
    CHECK(filter.is_excluded("dir/debug.log"));
    CHECK_FALSE(filter.is_excluded("readme.txt"));
}

TEST_CASE("ExcludeFilter: basename matching", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"*.log"});

    CHECK(filter.is_excluded("debug.log"));
    CHECK(filter.is_excluded("sub/dir/error.log"));
    CHECK_FALSE(filter.is_excluded("readme.txt"));
}

TEST_CASE("ExcludeFilter: question mark wildcard", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"file?.txt"});

    CHECK(filter.is_excluded("file1.txt"));
    CHECK(filter.is_excluded("fileA.txt"));
    CHECK_FALSE(filter.is_excluded("file12.txt"));
}

TEST_CASE("ExcludeFilter: no dotfile protection", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"*"});

    // ExcludeFilter matches everything including dotfiles
    CHECK(filter.is_excluded("regular.txt"));
    CHECK(filter.is_excluded(".hidden"));
}

TEST_CASE("ExcludeFilter: last rule wins", "[exclude]") {
    vost::ExcludeFilter filter;
    filter.add_patterns({"*.log", "!important.log", "*.log"});

    // Last *.log re-excludes important.log
    CHECK(filter.is_excluded("important.log"));
    CHECK(filter.is_excluded("debug.log"));
}

// ---------------------------------------------------------------------------
// copy_from_ref by name string
// ---------------------------------------------------------------------------

TEST_CASE("Copy: copy_from_ref resolves branch name string", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("a.txt", "alpha");

    auto dev = store.branches().set_and_get("dev", main_snap);
    dev = dev.write_text("b.txt", "beta");

    main_snap = store.branches().get("main");
    main_snap = main_snap.copy_from_ref("dev", {"b.txt"});
    CHECK(main_snap.read_text("b.txt") == "beta");
    CHECK(main_snap.read_text("a.txt") == "alpha");

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref resolves tag name string", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("data/a.txt", "alpha");

    store.tags().set("v1", main_snap);

    auto dev = store.branches().set_and_get("dev", main_snap);
    dev = dev.write_text("other.txt", "other");

    // Copy directory from tag into a new dest
    dev = dev.copy_from_ref("v1", {"data"}, "copied");
    CHECK(dev.read_text("copied/data/a.txt") == "alpha");

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref nonexistent name throws", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("a.txt", "alpha");

    CHECK_THROWS(main_snap.copy_from_ref("no-such-branch", {"a.txt"}));

    fs::remove_all(repo_path);
}

TEST_CASE("Copy: copy_from_ref prefers branch over tag with same name", "[copy][copy_from_ref]") {
    auto repo_path = make_temp_repo();
    auto store = open_store(repo_path);
    auto main_snap = store.branches().get("main");
    main_snap = main_snap.write_text("data/a.txt", "from-main");

    auto other = store.branches().set_and_get("other", main_snap);
    other = other.write_text("data/a.txt", "from-other");

    // Tag "other" pointing to main
    store.tags().set("other", main_snap);

    // Branch should win — copy the directory
    main_snap = store.branches().get("main");
    main_snap = main_snap.copy_from_ref("other", {"data"});
    CHECK(main_snap.read_text("data/a.txt") == "from-other");

    fs::remove_all(repo_path);
}
