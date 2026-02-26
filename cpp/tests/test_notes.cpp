#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <chrono>
#include <filesystem>
#include <string>
#include <thread>

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_notes_test_" + std::to_string(
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

/// Write a file so we have a commit hash to use for notes.
static std::string setup_commit(vost::GitStore& store,
                                 const std::string& branch = "main") {
    auto snap = store.branches()["main"];
    snap = snap.write_text("test.txt", "content");
    return *snap.commit_hash();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

TEST_CASE("Notes: set and get roundtrip", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    store.notes()["commits"].set(hash, "hello note");
    auto text = store.notes()["commits"].get(hash);
    CHECK(text == "hello note");

    fs::remove_all(path);
}

TEST_CASE("Notes: get non-existent throws KeyNotFoundError", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    CHECK_THROWS_AS(store.notes()["commits"].get(hash), vost::KeyNotFoundError);

    fs::remove_all(path);
}

TEST_CASE("Notes: has returns true/false correctly", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    auto ns = store.notes()["commits"];
    CHECK_FALSE(ns.has(hash));

    ns.set(hash, "exists");
    CHECK(ns.has(hash));

    fs::remove_all(path);
}

TEST_CASE("Notes: empty and size", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    auto ns = store.notes()["commits"];
    CHECK(ns.empty());
    CHECK(ns.size() == 0);

    ns.set(hash, "note1");
    CHECK_FALSE(ns.empty());
    CHECK(ns.size() == 1);

    fs::remove_all(path);
}

TEST_CASE("Notes: list returns sorted hashes", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);

    // Create two commits for two distinct hashes
    auto snap = store.branches()["main"];
    snap = snap.write_text("a.txt", "aaa");
    auto hash1 = *snap.commit_hash();
    snap = snap.write_text("b.txt", "bbb");
    auto hash2 = *snap.commit_hash();

    auto ns = store.notes()["commits"];
    ns.set(hash1, "note for commit 1");
    ns.set(hash2, "note for commit 2");

    auto hashes = ns.list();
    REQUIRE(hashes.size() == 2);
    // Should be sorted
    CHECK(hashes[0] < hashes[1]);

    // Both hashes present
    CHECK((hashes[0] == hash1 || hashes[0] == hash2));
    CHECK((hashes[1] == hash1 || hashes[1] == hash2));
    CHECK(hashes[0] != hashes[1]);

    fs::remove_all(path);
}

TEST_CASE("Notes: delete removes note", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    auto ns = store.notes()["commits"];
    ns.set(hash, "to delete");
    CHECK(ns.has(hash));

    ns.del(hash);
    CHECK_FALSE(ns.has(hash));
    CHECK(ns.empty());

    fs::remove_all(path);
}

TEST_CASE("Notes: delete non-existent throws KeyNotFoundError", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    CHECK_THROWS_AS(store.notes()["commits"].del(hash), vost::KeyNotFoundError);

    fs::remove_all(path);
}

TEST_CASE("Notes: multiple namespaces are independent", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    store.notes()["commits"].set(hash, "commit note");
    store.notes()["reviews"].set(hash, "review note");
    store.notes()["metadata"].set(hash, "meta note");

    CHECK(store.notes()["commits"].get(hash) == "commit note");
    CHECK(store.notes()["reviews"].get(hash) == "review note");
    CHECK(store.notes()["metadata"].get(hash) == "meta note");

    // Deleting from one doesn't affect others
    store.notes()["reviews"].del(hash);
    CHECK_FALSE(store.notes()["reviews"].has(hash));
    CHECK(store.notes()["commits"].has(hash));
    CHECK(store.notes()["metadata"].has(hash));

    fs::remove_all(path);
}

TEST_CASE("Notes: batch set multiple notes in single commit", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);

    auto snap = store.branches()["main"];
    snap = snap.write_text("a.txt", "aaa");
    auto hash1 = *snap.commit_hash();
    snap = snap.write_text("b.txt", "bbb");
    auto hash2 = *snap.commit_hash();

    auto ns = store.notes()["commits"];
    auto batch = ns.batch();
    batch.set(hash1, "batch note 1");
    batch.set(hash2, "batch note 2");
    batch.commit();

    CHECK(ns.get(hash1) == "batch note 1");
    CHECK(ns.get(hash2) == "batch note 2");
    CHECK(ns.size() == 2);

    fs::remove_all(path);
}

TEST_CASE("Notes: batch commit is idempotent for empty batch", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);

    auto ns = store.notes()["commits"];
    auto batch = ns.batch();
    batch.commit(); // empty batch — should not throw

    CHECK(ns.empty());

    fs::remove_all(path);
}

TEST_CASE("Notes: overwrite existing note", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    auto ns = store.notes()["commits"];
    ns.set(hash, "original");
    CHECK(ns.get(hash) == "original");

    ns.set(hash, "updated");
    CHECK(ns.get(hash) == "updated");
    CHECK(ns.size() == 1);

    fs::remove_all(path);
}

TEST_CASE("Notes: invalid hash throws InvalidHashError", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);

    auto ns = store.notes()["commits"];

    CHECK_THROWS_AS(ns.get("not-a-hash"), vost::InvalidHashError);
    CHECK_THROWS_AS(ns.set("not-a-hash", "text"), vost::InvalidHashError);
    CHECK_THROWS_AS(ns.del("not-a-hash"), vost::InvalidHashError);
    CHECK_THROWS_AS(ns.has("ABCD"), vost::InvalidHashError);

    fs::remove_all(path);
}

TEST_CASE("Notes: unicode text roundtrip", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    std::string text = "LGTM \xe2\x9c\x85\nline2\nline3"; // UTF-8 for checkmark
    store.notes()["reviews"].set(hash, text);
    CHECK(store.notes()["reviews"].get(hash) == text);

    fs::remove_all(path);
}

TEST_CASE("Notes: read fanout layout", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    // Manually create a note in 2/38 fanout layout using git CLI
    // We write a note using git-notes which uses fanout
    {
        std::string cmd = "cd " + path.string() +
                          " && git notes --ref=fanout add -m 'fanout note' " +
                          hash;
        int rc = std::system(cmd.c_str());
        // If git is not available or fails, skip test
        if (rc != 0) {
            SKIP("git CLI not available for fanout test");
        }
    }

    // Now read it with our code
    auto text = store.notes()["fanout"].get(hash);
    CHECK(text == "fanout note\n"); // git adds trailing newline

    // has should work too
    CHECK(store.notes()["fanout"].has(hash));

    // list should find it
    auto hashes = store.notes()["fanout"].list();
    REQUIRE(hashes.size() == 1);
    CHECK(hashes[0] == hash);

    fs::remove_all(path);
}

TEST_CASE("Notes: batch double-commit throws BatchClosedError", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    auto ns = store.notes()["commits"];
    auto batch = ns.batch();
    batch.set(hash, "note");
    batch.commit();

    CHECK_THROWS_AS(batch.commit(), vost::BatchClosedError);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// NoteDict::commits() shortcut
// ---------------------------------------------------------------------------

TEST_CASE("Notes: commits() shortcut works", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto hash = setup_commit(store);

    store.notes().commits().set(hash, "via commits()");
    CHECK(store.notes().commits().get(hash) == "via commits()");

    // Also accessible via ["commits"]
    CHECK(store.notes()["commits"].get(hash) == "via commits()");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// NoteNamespace::get_for_current_branch / set_for_current_branch
// ---------------------------------------------------------------------------

TEST_CASE("Notes: set_for_current_branch and get_for_current_branch roundtrip", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write_text("test.txt", "data");

    auto ns = store.notes()["commits"];
    ns.set_for_current_branch("current branch note");
    CHECK(ns.get_for_current_branch() == "current branch note");

    // Verify it's stored under the HEAD tip commit hash
    auto tip = *snap.commit_hash();
    // After write_text, HEAD has advanced. Re-read to get actual tip.
    auto latest = store.branches()["main"];
    auto latest_hash = *latest.commit_hash();
    CHECK(ns.get(latest_hash) == "current branch note");

    fs::remove_all(path);
}

TEST_CASE("Notes: get_for_current_branch throws when no note exists", "[notes]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write_text("test.txt", "data");

    auto ns = store.notes()["commits"];
    CHECK_THROWS_AS(ns.get_for_current_branch(), vost::KeyNotFoundError);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict::set_and_get
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: set_and_get returns writable Fs", "[notes][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches()["main"];
    snap = snap.write_text("f.txt", "data");

    auto dev = store.branches().set_and_get("dev", snap);
    CHECK(dev.writable());
    CHECK(*dev.ref_name() == "dev");
    CHECK(dev.read_text("f.txt") == "data");

    // Can write to it
    dev = dev.write_text("g.txt", "new data");
    CHECK(dev.read_text("g.txt") == "new data");

    fs::remove_all(path);
}
