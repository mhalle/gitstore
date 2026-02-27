#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <string>
#include <thread>

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static fs::path make_temp_mirror_dir() {
    auto tmp = fs::temp_directory_path() /
               ("vost_mirror_" + std::to_string(
                    std::hash<std::thread::id>{}(std::this_thread::get_id())
                    ^ static_cast<size_t>(
                          std::chrono::steady_clock::now()
                              .time_since_epoch()
                              .count())));
    return tmp;
}

static vost::GitStore open_mirror_store(const fs::path& path,
                                        const std::string& branch = "main") {
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = branch;
    return vost::GitStore::open(path, opts);
}

static bool contains(const std::vector<std::string>& v, const std::string& s) {
    return std::find(v.begin(), v.end(), s) != v.end();
}

static bool any_ref_contains(const std::vector<vost::RefChange>& changes,
                             const std::string& substr) {
    return std::any_of(changes.begin(), changes.end(),
                       [&](const vost::RefChange& r) {
                           return r.ref_name.find(substr) != std::string::npos;
                       });
}

// ---------------------------------------------------------------------------
// backup
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup to local bare repo", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();

    auto diff = store.backup(remote_url);

    CHECK_FALSE(diff.in_sync());
    CHECK_FALSE(diff.add.empty());

    // Verify remote has the refs
    auto remote = vost::GitStore::open(remote_path);
    auto branches = remote.branches().keys();
    CHECK(contains(branches, "main"));
    CHECK(remote.branches()["main"].read_text("a.txt") == "hello");

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

// ---------------------------------------------------------------------------
// restore
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: restore from local bare repo", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Create a new empty store and restore into it
    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions opts;
    opts.create = true;
    auto store2 = vost::GitStore::open(restore_path, opts);

    auto diff = store2.restore(remote_url);
    CHECK_FALSE(diff.in_sync());
    CHECK_FALSE(diff.add.empty());

    auto branches = store2.branches().keys();
    CHECK(contains(branches, "main"));
    CHECK(store2.branches()["main"].read_text("a.txt") == "hello");

    fs::remove_all(path);
    fs::remove_all(remote_path);
    fs::remove_all(restore_path);
}

// ---------------------------------------------------------------------------
// dry-run
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: dry-run backup makes no changes", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();

    // First do a real backup
    store.backup(remote_url);

    // Write more data
    f = store.branches()["main"];
    f = f.write_text("b.txt", "world");

    // Dry-run should report changes but not push
    vost::BackupOptions bo;
    bo.dry_run = true;
    auto diff = store.backup(remote_url, bo);
    CHECK_FALSE(diff.in_sync());

    // Remote should still only have the old data
    auto remote = vost::GitStore::open(remote_path);
    CHECK_FALSE(remote.branches()["main"].exists("b.txt"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

TEST_CASE("Mirror: dry-run restore makes no changes", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Create empty store
    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions opts;
    opts.create = true;
    auto store2 = vost::GitStore::open(restore_path, opts);

    vost::RestoreOptions ro;
    ro.dry_run = true;
    auto diff = store2.restore(remote_url, ro);
    CHECK_FALSE(diff.in_sync());

    // Store2 should still be empty
    CHECK(store2.branches().keys().empty());

    fs::remove_all(path);
    fs::remove_all(remote_path);
    fs::remove_all(restore_path);
}

// ---------------------------------------------------------------------------
// stale ref deletion (backup) / additive restore
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup deletes stale remote refs", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    // Create a second branch
    store.branches().set("extra", f);

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Verify remote has both branches
    {
        auto remote = vost::GitStore::open(remote_path);
        CHECK(contains(remote.branches().keys(), "extra"));
    }

    // Delete the extra branch locally
    store.branches().del("extra");

    // Backup again — should delete the remote extra branch
    auto diff = store.backup(remote_url);
    CHECK(any_ref_contains(diff.del, "extra"));

    // Verify remote no longer has the extra branch
    auto remote = vost::GitStore::open(remote_path);
    CHECK_FALSE(contains(remote.branches().keys(), "extra"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

TEST_CASE("Mirror: restore is additive", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Create a local-only branch
    store.branches().set("local-only", f);
    CHECK(contains(store.branches().keys(), "local-only"));

    // Restore from remote — local-only branch should survive (additive)
    auto diff = store.restore(remote_url);
    CHECK(diff.del.empty());
    CHECK(contains(store.branches().keys(), "local-only"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

// ---------------------------------------------------------------------------
// round-trip
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: round-trip backup then restore", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "aaa");
    f = f.write_text("b.txt", "bbb");

    store.branches().set("feature", f);
    auto feat = store.branches()["feature"];
    feat = feat.write_text("c.txt", "ccc");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Create new store and restore
    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions opts;
    opts.create = true;
    auto store2 = vost::GitStore::open(restore_path, opts);
    store2.restore(remote_url);

    CHECK(store2.branches()["main"].read_text("a.txt") == "aaa");
    CHECK(store2.branches()["main"].read_text("b.txt") == "bbb");
    CHECK(contains(store2.branches().keys(), "feature"));
    CHECK(store2.branches()["feature"].read_text("c.txt") == "ccc");

    fs::remove_all(path);
    fs::remove_all(remote_path);
    fs::remove_all(restore_path);
}

// ---------------------------------------------------------------------------
// already in sync
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup when already in sync", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    // Second backup should be in sync
    auto diff = store.backup(remote_url);
    CHECK(diff.in_sync());
    CHECK(diff.total() == 0);

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

// ---------------------------------------------------------------------------
// tags
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup with tags", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    auto remote = vost::GitStore::open(remote_path);
    auto tags = remote.tags().keys();
    CHECK(contains(tags, "v1.0"));
    CHECK(remote.tags()["v1.0"].read_text("a.txt") == "hello");

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

// ---------------------------------------------------------------------------
// bundle
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup to bundle", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto bundle = (path.parent_path() / "backup.bundle").string();
    auto diff = store.backup(bundle);

    CHECK_FALSE(diff.in_sync());
    CHECK_FALSE(diff.add.empty());
    CHECK(fs::exists(bundle));

    fs::remove_all(path);
    fs::remove(bundle);
}

TEST_CASE("Mirror: restore from bundle", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto bundle = (path.parent_path() / "backup.bundle").string();
    store.backup(bundle);

    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions opts;
    opts.create = true;
    auto store2 = vost::GitStore::open(restore_path, opts);

    auto diff = store2.restore(bundle);
    CHECK_FALSE(diff.in_sync());

    CHECK(contains(store2.branches().keys(), "main"));
    CHECK(store2.branches()["main"].read_text("a.txt") == "hello");
    CHECK(contains(store2.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove(bundle);
    fs::remove_all(restore_path);
}

TEST_CASE("Mirror: bundle dry run", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");

    auto bundle = (path.parent_path() / "backup.bundle").string();
    vost::BackupOptions bo;
    bo.dry_run = true;
    auto diff = store.backup(bundle, bo);

    CHECK_FALSE(diff.in_sync());
    CHECK_FALSE(fs::exists(bundle));

    fs::remove_all(path);
}

TEST_CASE("Mirror: bundle round trip", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "aaa");
    f = f.write_text("b.txt", "bbb");
    store.tags().set("v1.0", f);

    auto bundle = (path.parent_path() / "roundtrip.bundle").string();
    store.backup(bundle);

    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions opts;
    opts.create = true;
    auto store2 = vost::GitStore::open(restore_path, opts);
    store2.restore(bundle);

    CHECK(store2.branches()["main"].read_text("a.txt") == "aaa");
    CHECK(store2.branches()["main"].read_text("b.txt") == "bbb");
    CHECK(contains(store2.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove(bundle);
    fs::remove_all(restore_path);
}

// ---------------------------------------------------------------------------
// refs filtering
// ---------------------------------------------------------------------------

TEST_CASE("Mirror: backup with refs filter", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();

    vost::BackupOptions bo;
    bo.refs = {"main"};
    store.backup(remote_url, bo);

    auto remote = vost::GitStore::open(remote_path);
    CHECK(contains(remote.branches().keys(), "main"));
    CHECK_FALSE(contains(remote.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
}

TEST_CASE("Mirror: restore with refs filter", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();
    store.backup(remote_url);

    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions oo;
    oo.create = true;
    auto store2 = vost::GitStore::open(restore_path, oo);

    vost::RestoreOptions ro;
    ro.refs = {"v1.0"};
    store2.restore(remote_url, ro);

    CHECK(contains(store2.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
    fs::remove_all(restore_path);
}

TEST_CASE("Mirror: backup bundle with refs", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto bundle = (path.parent_path() / "main-only.bundle").string();
    vost::BackupOptions bo;
    bo.refs = {"main"};
    store.backup(bundle, bo);

    auto restore_path = path.parent_path() / (path.filename().string() + "_restored.git");
    vost::OpenOptions oo;
    oo.create = true;
    auto store2 = vost::GitStore::open(restore_path, oo);
    store2.restore(bundle);

    CHECK(contains(store2.branches().keys(), "main"));
    CHECK_FALSE(contains(store2.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove(bundle);
    fs::remove_all(restore_path);
}

TEST_CASE("Mirror: backup ref preserves existing remote refs", "[mirror]") {
    auto path = make_temp_mirror_dir();
    auto store = open_mirror_store(path);
    auto f = store.branches()["main"];
    f = f.write_text("a.txt", "hello");
    store.tags().set("v1.0", f);

    auto remote_path = path.parent_path() / (path.filename().string() + "_remote.git");
    auto remote_url = remote_path.string();

    // Full backup first
    store.backup(remote_url);

    // Verify remote has both
    {
        auto remote = vost::GitStore::open(remote_path);
        CHECK(contains(remote.branches().keys(), "main"));
        CHECK(contains(remote.tags().keys(), "v1.0"));
    }

    // Targeted backup of only main — v1.0 should still survive on remote
    vost::BackupOptions bo;
    bo.refs = {"main"};
    auto diff = store.backup(remote_url, bo);
    CHECK(diff.del.empty()); // no deletes with ref filter

    auto remote = vost::GitStore::open(remote_path);
    CHECK(contains(remote.tags().keys(), "v1.0"));

    fs::remove_all(path);
    fs::remove_all(remote_path);
}
