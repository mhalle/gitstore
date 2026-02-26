#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_htest_" + std::to_string(
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
// author_name / author_email
// ---------------------------------------------------------------------------

TEST_CASE("History: author_name defaults to vost", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    CHECK(snap.author_name() == "vost");
    fs::remove_all(path);
}

TEST_CASE("History: author_email defaults to vost@localhost", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    CHECK(snap.author_email() == "vost@localhost");
    fs::remove_all(path);
}

TEST_CASE("History: custom author propagates to commits", "[history]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    opts.author = "alice";
    opts.email  = "alice@example.com";
    auto store = vost::GitStore::open(path, opts);
    auto snap  = store.branches().get("main");

    CHECK(snap.author_name()  == "alice");
    CHECK(snap.author_email() == "alice@example.com");
    fs::remove_all(path);
}

TEST_CASE("History: author fields persist after subsequent writes", "[history]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    opts.author = "bob";
    opts.email  = "bob@example.com";
    auto store = vost::GitStore::open(path, opts);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    CHECK(snap.author_name()  == "bob");
    CHECK(snap.author_email() == "bob@example.com");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// back(0) returns same commit
// ---------------------------------------------------------------------------

TEST_CASE("History: back(0) returns snapshot with same commit hash", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("v.txt", "1");

    auto same = snap.back(0);
    CHECK(same.commit_hash() == snap.commit_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// parent() of initial commit is nullopt
// ---------------------------------------------------------------------------

TEST_CASE("History: parent of the initial commit returns nullopt", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    // This IS the initial commit

    auto p = snap.parent();
    CHECK_FALSE(p.has_value());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// parent chain traversal
// ---------------------------------------------------------------------------

TEST_CASE("History: parent chain matches individual write order", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("n.txt", "1");  // commit A
    snap = snap.write_text("n.txt", "2");  // commit B
    snap = snap.write_text("n.txt", "3");  // commit C  (HEAD)

    // C.parent == B
    auto b = snap.parent();
    REQUIRE(b.has_value());
    CHECK(b->read_text("n.txt") == "2");

    // B.parent == A
    auto a = b->parent();
    REQUIRE(a.has_value());
    CHECK(a->read_text("n.txt") == "1");

    // A.parent == initial commit (no "n.txt")
    auto init = a->parent();
    REQUIRE(init.has_value());
    CHECK_FALSE(init->exists("n.txt"));

    fs::remove_all(path);
}

TEST_CASE("History: back(n) is equivalent to n calls to parent", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("x.txt", "a");
    snap = snap.write_text("x.txt", "b");
    snap = snap.write_text("x.txt", "c");

    auto via_back   = snap.back(2);
    auto via_parent = snap.parent()->parent();

    REQUIRE(via_parent.has_value());
    CHECK(via_back.commit_hash() == via_parent->commit_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Message preserved in history
// ---------------------------------------------------------------------------

TEST_CASE("History: commit messages are accessible through parent chain", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions opts1;
    opts1.message = "commit one";
    snap = snap.write_text("f.txt", "1", opts1);

    vost::WriteOptions opts2;
    opts2.message = "commit two";
    snap = snap.write_text("f.txt", "2", opts2);

    CHECK(snap.message() == "commit two");

    auto prev = snap.parent();
    REQUIRE(prev.has_value());
    CHECK(prev->message() == "commit one");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// back() throws when history is too short
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// log()
// ---------------------------------------------------------------------------

TEST_CASE("History: log returns all commits", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    auto entries = snap.log();
    // 3 commits: init + 2 writes
    CHECK(entries.size() >= 3);
    // Most recent first
    CHECK(entries[0].commit_hash == *snap.commit_hash());
    fs::remove_all(path);
}

TEST_CASE("History: log with limit", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    vost::LogOptions opts;
    opts.limit = 2;
    auto entries = snap.log(opts);
    CHECK(entries.size() == 2);
    fs::remove_all(path);
}

TEST_CASE("History: log with skip", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions w1; w1.message = "commit v1";
    snap = snap.write_text("f.txt", "v1", w1);
    vost::WriteOptions w2; w2.message = "commit v2";
    snap = snap.write_text("f.txt", "v2", w2);
    vost::WriteOptions w3; w3.message = "commit v3";
    snap = snap.write_text("f.txt", "v3", w3);

    vost::LogOptions opts;
    opts.skip = 1;
    opts.limit = 1;
    auto entries = snap.log(opts);
    REQUIRE(entries.size() == 1);
    // Skipped the most recent (v3), so this is v2
    CHECK(entries[0].message == "commit v2");
    fs::remove_all(path);
}

TEST_CASE("History: log with path filter", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");
    snap = snap.write_text("a.txt", "a2");

    vost::LogOptions opts;
    opts.path = "a.txt";
    auto entries = snap.log(opts);
    // Should match commits that changed a.txt: the initial add + the update
    CHECK(entries.size() == 2);
    fs::remove_all(path);
}

TEST_CASE("History: log with match_pattern", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions w1; w1.message = "feat: add login";
    snap = snap.write_text("f.txt", "v1", w1);
    vost::WriteOptions w2; w2.message = "fix: typo";
    snap = snap.write_text("f.txt", "v2", w2);
    vost::WriteOptions w3; w3.message = "feat: add logout";
    snap = snap.write_text("f.txt", "v3", w3);

    vost::LogOptions opts;
    opts.match_pattern = "feat:*";
    auto entries = snap.log(opts);
    CHECK(entries.size() == 2);
    fs::remove_all(path);
}

TEST_CASE("History: log with before filter", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    auto t1 = snap.time();
    // All commits are nearly the same time, so test with a future cutoff
    vost::LogOptions opts;
    opts.before = t1 + 1;
    auto entries = snap.log(opts);
    CHECK(entries.size() >= 1);

    // With a past cutoff, should get nothing
    opts.before = 1; // epoch + 1 second
    entries = snap.log(opts);
    CHECK(entries.empty());
    fs::remove_all(path);
}

TEST_CASE("History: log on empty snapshot returns empty", "[history][log]") {
    auto path  = make_temp_repo();
    vost::OpenOptions oo;
    oo.create = true;
    auto store = vost::GitStore::open(path, oo);

    // Create an empty branch
    auto snap = vost::Fs::empty(store.inner(), "empty");
    auto entries = snap.log();
    CHECK(entries.empty());
    fs::remove_all(path);
}

TEST_CASE("History: log detects mode-only changes via path filter", "[history][log]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("script.sh", "#!/bin/sh");

    // Change mode only
    vost::WriteOptions wopts;
    wopts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("script.sh", "#!/bin/sh", wopts);

    vost::LogOptions opts;
    opts.path = "script.sh";
    auto entries = snap.log(opts);
    CHECK(entries.size() == 2); // initial write + mode change
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// undo()
// ---------------------------------------------------------------------------

TEST_CASE("History: undo single commit", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    auto undone = snap.undo();
    CHECK(undone.read_text("f.txt") == "v1");
    // Branch should be updated
    auto latest = store.branches().get("main");
    CHECK(latest.read_text("f.txt") == "v1");
    fs::remove_all(path);
}

TEST_CASE("History: undo multiple commits", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");
    snap = snap.write_text("f.txt", "v3");

    auto undone = snap.undo(2);
    CHECK(undone.read_text("f.txt") == "v1");
    fs::remove_all(path);
}

TEST_CASE("History: undo(0) returns same snapshot", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    auto same = snap.undo(0);
    CHECK(same.commit_hash() == snap.commit_hash());
    fs::remove_all(path);
}

TEST_CASE("History: undo throws on tag", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    store.tags().set("v1.0", snap);
    auto tag_snap = store.tags().get("v1.0");

    REQUIRE_THROWS_AS(tag_snap.undo(), vost::PermissionError);
    fs::remove_all(path);
}

TEST_CASE("History: undo throws when history too short", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    // Only the initial commit — no parent

    REQUIRE_THROWS_AS(snap.undo(), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("History: undo throws StaleSnapshotError", "[history][undo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    auto stale = snap; // save stale ref
    snap.write_text("f.txt", "v2"); // advance branch

    REQUIRE_THROWS_AS(stale.undo(), vost::StaleSnapshotError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// redo()
// ---------------------------------------------------------------------------

TEST_CASE("History: redo after undo", "[history][redo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    auto undone = snap.undo();
    CHECK(undone.read_text("f.txt") == "v1");

    auto redone = undone.redo();
    CHECK(redone.read_text("f.txt") == "v2");
    fs::remove_all(path);
}

TEST_CASE("History: redo(0) returns same snapshot", "[history][redo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    auto same = snap.redo(0);
    CHECK(same.commit_hash() == snap.commit_hash());
    fs::remove_all(path);
}

TEST_CASE("History: redo throws when no redo history", "[history][redo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    // No undo was performed, so redo should fail
    REQUIRE_THROWS_AS(snap.redo(), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("History: redo throws on tag", "[history][redo]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    store.tags().set("v1.0", snap);
    auto tag_snap = store.tags().get("v1.0");

    REQUIRE_THROWS_AS(tag_snap.redo(), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

TEST_CASE("History: back(n) throws NotFoundError when history is shorter", "[history]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("x.txt", "x");  // only one write commit

    // back(10) — way more than available history
    REQUIRE_THROWS_AS(snap.back(10), vost::NotFoundError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: log with path filter - added then removed
// ---------------------------------------------------------------------------

TEST_CASE("History: log with path filter shows add and remove", "[history][log]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("temp.txt", "data");
    snap = snap.remove({"temp.txt"});

    vost::LogOptions opts;
    opts.path = "temp.txt";
    auto entries = snap.log(opts);
    // Should have 2 entries: add + remove
    CHECK(entries.size() == 2);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: undo/redo roundtrip
// ---------------------------------------------------------------------------

TEST_CASE("History: undo then redo restores content", "[history][undo][redo]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");

    auto undone = snap.undo();
    CHECK(undone.read_text("f.txt") == "v1");

    auto redone = undone.redo();
    CHECK(redone.read_text("f.txt") == "v2");

    // Verify branch state
    auto latest = store.branches().get("main");
    CHECK(latest.read_text("f.txt") == "v2");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: redo on readonly throws
// ---------------------------------------------------------------------------

TEST_CASE("History: redo on readonly tag throws PermissionError", "[history][redo]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    store.tags().set("release", snap);
    auto tag = store.tags().get("release");

    REQUIRE_THROWS_AS(tag.redo(), vost::PermissionError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: commit metadata
// ---------------------------------------------------------------------------

TEST_CASE("History: log entries have valid commit metadata", "[history][log]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    vost::WriteOptions wopts;
    wopts.message = "test metadata";
    snap = snap.write_text("f.txt", "data", wopts);

    auto entries = snap.log();
    REQUIRE(!entries.empty());
    CHECK(entries[0].message == "test metadata");
    CHECK(entries[0].commit_hash.size() == 40);
    REQUIRE(entries[0].author_name.has_value());
    CHECK(*entries[0].author_name == "vost");
    REQUIRE(entries[0].author_email.has_value());
    CHECK(*entries[0].author_email == "vost@localhost");
    REQUIRE(entries[0].time.has_value());
    CHECK(*entries[0].time > 0);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: undo stale snapshot
// ---------------------------------------------------------------------------

TEST_CASE("History: undo on stale snapshot throws", "[history][undo]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");

    auto stale = snap;
    snap.write_text("f.txt", "v2"); // advance branch

    REQUIRE_THROWS_AS(stale.undo(), vost::StaleSnapshotError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History: multiple undo then redo
// ---------------------------------------------------------------------------

TEST_CASE("History: undo multiple then redo restores to before undo", "[history][undo][redo]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");
    snap = snap.write_text("f.txt", "v1");
    snap = snap.write_text("f.txt", "v2");
    snap = snap.write_text("f.txt", "v3");

    auto undone = snap.undo(2);
    CHECK(undone.read_text("f.txt") == "v1");

    // redo reverses the entire undo — goes back to v3 (pre-undo state)
    auto redone = undone.redo();
    CHECK(redone.read_text("f.txt") == "v3");
    fs::remove_all(path);
}
