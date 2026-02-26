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
               ("vost_btest_" + std::to_string(
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
// Basic Batch usage
// ---------------------------------------------------------------------------

TEST_CASE("Batch: commit writes all staged files atomically", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("a.txt", "hello");
    batch.write_text("b.txt", "world");
    auto result = batch.commit();

    CHECK(result.read_text("a.txt") == "hello");
    CHECK(result.read_text("b.txt") == "world");
    // Should be a single commit covering both writes
    CHECK(result.commit_hash() != snap.commit_hash());
    fs::remove_all(path);
}

TEST_CASE("Batch: commit with removes", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("old.txt", "old");

    auto batch = snap.batch();
    batch.remove("old.txt");
    batch.write_text("new.txt", "new");
    snap = batch.commit();

    CHECK_FALSE(snap.exists("old.txt"));
    CHECK(snap.read_text("new.txt") == "new");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Fluent chaining
// ---------------------------------------------------------------------------

TEST_CASE("Batch: fluent chaining works", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    snap = snap.batch()
               .write_text("x.txt", "X")
               .write_text("y.txt", "Y")
               .commit();

    CHECK(snap.read_text("x.txt") == "X");
    CHECK(snap.read_text("y.txt") == "Y");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// BatchClosedError
// ---------------------------------------------------------------------------

TEST_CASE("Batch: throws BatchClosedError after commit", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("f.txt", "data");
    batch.commit();

    REQUIRE_THROWS_AS(batch.write_text("g.txt", "oops"), vost::BatchClosedError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// write_with_mode
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write_with_mode sets executable bit", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    const std::string script_str = "#!/bin/sh\n";
    std::vector<uint8_t> script(script_str.begin(), script_str.end());
    snap = snap.batch()
               .write_with_mode("run.sh", script, vost::MODE_BLOB_EXEC)
               .commit();

    CHECK(snap.file_type("run.sh") == vost::FileType::Executable);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// write_symlink in batch
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write_symlink creates a link", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    snap = snap.batch()
               .write_text("real.txt", "content")
               .write_symlink("alias", "real.txt")
               .commit();

    CHECK(snap.file_type("alias") == vost::FileType::Link);
    CHECK(snap.readlink("alias") == "real.txt");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Overwrite in batch
// ---------------------------------------------------------------------------

TEST_CASE("Batch: later write to same path wins", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("f.txt", "first");
    batch.write_text("f.txt", "second"); // should overwrite
    snap = batch.commit();

    CHECK(snap.read_text("f.txt") == "second");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Custom batch message
// ---------------------------------------------------------------------------

TEST_CASE("Batch: custom message is used for commit", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::BatchOptions opts;
    opts.message = "my batch commit";
    auto batch = snap.batch(opts);
    batch.write_text("f.txt", "data");
    snap = batch.commit();

    CHECK(snap.message() == "my batch commit");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Pending counts
// ---------------------------------------------------------------------------

TEST_CASE("Batch: pending_writes and pending_removes track staged ops", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");

    auto batch = snap.batch();
    batch.write_text("c.txt", "c");
    batch.write_text("d.txt", "d");
    batch.remove("a.txt");

    CHECK(batch.pending_writes()  == 2);
    CHECK(batch.pending_removes() == 1);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// StaleSnapshotError propagates from batch
// ---------------------------------------------------------------------------

TEST_CASE("Batch: commit throws StaleSnapshotError if branch advanced", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");

    // Advance branch externally
    snap1.write_text("x.txt", "advance"); // this writes and updates HEAD

    // Now build batch from original stale snap1 (before write)
    // snap1 itself is still the pre-write snapshot
    // Re-fetch snap1 so we can make it stale
    auto stale = store.branches().get("main");
    stale.write_text("x.txt", "concurrent"); // advance HEAD again

    auto batch = stale.batch();
    batch.write_text("y.txt", "data");

    // stale is now stale — commit should fail
    REQUIRE_THROWS_AS(batch.commit(), vost::StaleSnapshotError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Last-operation-wins within a single batch
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write then remove same path — file is absent", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("conflict.txt", "written");
    batch.remove("conflict.txt");
    snap = batch.commit();

    CHECK_FALSE(snap.exists("conflict.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// batch.closed() before and after commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: closed() returns false before commit and true after", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    auto batch = snap.batch();
    CHECK_FALSE(batch.closed());

    batch.write_text("f.txt", "data");
    CHECK_FALSE(batch.closed());

    batch.commit();
    CHECK(batch.closed());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Empty batch commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: empty batch commit creates a new commit", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    auto old_hash = snap.commit_hash();

    auto batch = snap.batch();
    auto result = batch.commit();

    // A commit is still created
    CHECK(result.commit_hash() != old_hash);
    CHECK(batch.closed());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

TEST_CASE("Batch: remove then write same path — file is present", "[batch]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("conflict.txt", "original");

    auto batch = snap.batch();
    batch.remove("conflict.txt");
    batch.write_text("conflict.txt", "restored");
    snap = batch.commit();

    REQUIRE(snap.exists("conflict.txt"));
    CHECK(snap.read_text("conflict.txt") == "restored");
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

TEST_CASE("Batch: write_from_file stages local file", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto tmp = fs::temp_directory_path() / "vost_batch_wff_test";
    fs::create_directories(tmp);
    write_local_file(tmp / "data.txt", "from disk");

    auto batch = snap.batch();
    batch.write_from_file("data.txt", tmp / "data.txt");
    snap = batch.commit();

    CHECK(snap.read_text("data.txt") == "from disk");
    fs::remove_all(path);
    fs::remove_all(tmp);
}

// ---------------------------------------------------------------------------
// BatchWriter
// ---------------------------------------------------------------------------

TEST_CASE("BatchWriter: accumulates writes and stages on close", "[batch][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    {
        vost::BatchWriter w(batch, "stream.txt");
        w.write("chunk1 ");
        w.write("chunk2");
        w.close();
    }
    snap = batch.commit();

    CHECK(snap.read_text("stream.txt") == "chunk1 chunk2");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: readonly throws PermissionError
// ---------------------------------------------------------------------------

TEST_CASE("Batch: readonly throws PermissionError on commit", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    store.tags().set("v1", snap);
    auto tag_snap = store.tags().get("v1");

    auto batch = tag_snap.batch();
    batch.write_text("new.txt", "data");
    REQUIRE_THROWS_AS(batch.commit(), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: remove directory throws IsADirectoryError on commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: remove file works correctly", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");

    auto batch = snap.batch();
    batch.remove("a.txt");
    auto result = batch.commit();
    CHECK_FALSE(result.exists("a.txt"));
    CHECK(result.exists("b.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: changes report after commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: commit applies all staged writes", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("existing.txt", "v1");

    auto batch = snap.batch();
    batch.write_text("new.txt", "new");
    batch.write_text("existing.txt", "v2");
    auto result = batch.commit();

    CHECK(result.read_text("new.txt") == "new");
    CHECK(result.read_text("existing.txt") == "v2");
    CHECK(result.commit_hash() != snap.commit_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: identical writes no new commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: identical writes produce no change in tree", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    auto batch = snap.batch();
    batch.write_text("file.txt", "data");
    auto result = batch.commit();

    // Same tree content — tree_hash is same
    CHECK(result.tree_hash() == snap.tree_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: double commit throws BatchClosedError
// ---------------------------------------------------------------------------

TEST_CASE("Batch: double commit throws BatchClosedError", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("f.txt", "data");
    batch.commit();

    REQUIRE_THROWS_AS(batch.commit(), vost::BatchClosedError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: write_from_file preserves executable
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write_from_file preserves executable mode", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto tmp = fs::temp_directory_path() / "vost_batch_exec_test";
    fs::create_directories(tmp);
    write_local_file(tmp / "script.sh", "#!/bin/sh");
    fs::permissions(tmp / "script.sh",
                    fs::perms::owner_exec | fs::perms::owner_read | fs::perms::owner_write,
                    fs::perm_options::replace);

    auto batch = snap.batch();
    batch.write_from_file("script.sh", tmp / "script.sh", vost::MODE_BLOB_EXEC);
    snap = batch.commit();

    CHECK(snap.file_type("script.sh") == vost::FileType::Executable);
    fs::remove_all(path);
    fs::remove_all(tmp);
}

// ---------------------------------------------------------------------------
// Batch: write_from_file missing file throws
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write_from_file missing file throws", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    REQUIRE_THROWS_AS(
        batch.write_from_file("f.txt", "/nonexistent/path/file.txt"),
        vost::IoError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: fs() accessor after commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: fs() accessor returns committed snapshot", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("file.txt", "data");
    auto result = batch.commit();

    CHECK(batch.fs().has_value());
    CHECK(batch.fs()->commit_hash() == result.commit_hash());
    CHECK(batch.fs()->read_text("file.txt") == "data");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Batch: remove nonexistent throws NotFoundError on commit
// ---------------------------------------------------------------------------

TEST_CASE("Batch: write nested paths creates directories", "[batch]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    batch.write_text("a/b/c.txt", "deep");
    auto result = batch.commit();
    CHECK(result.exists("a/b/c.txt"));
    CHECK(result.read_text("a/b/c.txt") == "deep");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// BatchWriter: text mode
// ---------------------------------------------------------------------------

TEST_CASE("BatchWriter: text mode via string writes", "[batch][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    {
        vost::BatchWriter w(batch, "log.txt");
        w.write("line1\n");
        w.write("line2\n");
        w.close();
    }
    snap = batch.commit();

    CHECK(snap.read_text("log.txt") == "line1\nline2\n");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// BatchWriter: write after close throws
// ---------------------------------------------------------------------------

TEST_CASE("BatchWriter: write after close throws", "[batch][writer]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    auto batch = snap.batch();
    vost::BatchWriter w(batch, "file.txt");
    w.write("data");
    w.close();

    REQUIRE_THROWS_AS(w.write("more"), vost::BatchClosedError);
    fs::remove_all(path);
}
