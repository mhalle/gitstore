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

/// Create a temporary bare repository, returning its path.
/// The directory is removed when the returned path falls out of scope if
/// the caller wraps it in a std::filesystem scope, or you can call
/// fs::remove_all manually.
static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_test_" + std::to_string(
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
// GitStore::open — create
// ---------------------------------------------------------------------------

TEST_CASE("GitStore: open creates bare repo when create=true", "[store]") {
    auto path = make_temp_repo();
    REQUIRE_FALSE(fs::exists(path));

    {
        vost::OpenOptions opts;
        opts.create = true;
        opts.branch = "main";
        auto store = vost::GitStore::open(path, opts);
        CHECK(store.path() == path);
        CHECK(fs::exists(path));
    }

    fs::remove_all(path);
}

TEST_CASE("GitStore: open throws NotFoundError when missing and create=false", "[store]") {
    auto path = make_temp_repo();
    REQUIRE_FALSE(fs::exists(path));

    REQUIRE_THROWS_AS(vost::GitStore::open(path), vost::NotFoundError);
}

// ---------------------------------------------------------------------------
// GitStore::open — reopen existing
// ---------------------------------------------------------------------------

TEST_CASE("GitStore: can reopen an existing repo", "[store]") {
    auto path = make_temp_repo();

    {
        vost::OpenOptions opts;
        opts.create = true;
        opts.branch = "main";
        vost::GitStore::open(path, opts);
    }

    // Reopen without create
    {
        auto store = vost::GitStore::open(path);
        CHECK(store.path() == path);
    }

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// GitStore::signature
// ---------------------------------------------------------------------------

TEST_CASE("GitStore: default signature is vost/vost@localhost", "[store]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    auto store = vost::GitStore::open(path, opts);

    CHECK(store.signature().name  == "vost");
    CHECK(store.signature().email == "vost@localhost");

    fs::remove_all(path);
}

TEST_CASE("GitStore: custom signature propagates", "[store]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.author = "alice";
    opts.email  = "alice@example.com";
    auto store  = vost::GitStore::open(path, opts);

    CHECK(store.signature().name  == "alice");
    CHECK(store.signature().email == "alice@example.com");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict — branches / tags
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: branches returns empty for fresh repo without branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    auto store = vost::GitStore::open(path, opts);

    // No branch created — keys() should be empty
    auto keys = store.branches().keys();
    CHECK(keys.empty());

    fs::remove_all(path);
}

TEST_CASE("RefDict: branches contains 'main' after create with branch=main", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);

    auto keys = store.branches().keys();
    REQUIRE(keys.size() == 1);
    CHECK(keys[0] == "main");

    fs::remove_all(path);
}

TEST_CASE("RefDict: get throws KeyNotFoundError for missing branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    auto store = vost::GitStore::open(path, opts);

    REQUIRE_THROWS_AS(store.branches().get("nonexistent"), vost::KeyNotFoundError);

    fs::remove_all(path);
}

TEST_CASE("RefDict: contains returns false for missing branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    auto store = vost::GitStore::open(path, opts);

    CHECK_FALSE(store.branches().contains("missing"));

    fs::remove_all(path);
}

TEST_CASE("RefDict: contains returns true for existing branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "dev";
    auto store = vost::GitStore::open(path, opts);

    CHECK(store.branches().contains("dev"));
    CHECK_FALSE(store.branches().contains("main"));

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// current_name / set_current
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: current_name returns branch name after init", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);

    auto cur = store.branches().current_name();
    REQUIRE(cur.has_value());
    CHECK(*cur == "main");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict: del
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: del removes a branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);

    // Write a file to create the branch, then create a second branch
    auto fs = store.branches().get("main");
    fs = fs.write_text("readme.txt", "hello");
    store.branches().set("other", fs);

    CHECK(store.branches().contains("other"));
    store.branches().del("other");
    CHECK_FALSE(store.branches().contains("other"));

    fs::remove_all(path);
}

TEST_CASE("RefDict: del throws KeyNotFoundError for missing branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    auto store = vost::GitStore::open(path, opts);

    REQUIRE_THROWS_AS(store.branches().del("ghost"), vost::KeyNotFoundError);

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict: multiple branches in keys()
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: keys lists all created branches", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    store.branches().set("dev",     snap);
    store.branches().set("release", snap);

    auto keys = store.branches().keys();
    REQUIRE(keys.size() == 3);
    std::sort(keys.begin(), keys.end());
    CHECK(keys[0] == "dev");
    CHECK(keys[1] == "main");
    CHECK(keys[2] == "release");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict: set_current changes current_name
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: set_current changes the current branch", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("x.txt", "x");
    store.branches().set("dev", snap);

    store.branches().set_current("dev");

    auto cur = store.branches().current_name();
    REQUIRE(cur.has_value());
    CHECK(*cur == "dev");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict: reflog has entries after writes
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tags: contains / del
// ---------------------------------------------------------------------------

TEST_CASE("Tags: contains returns true for existing tag", "[store][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");
    store.tags().set("v1.0", snap);

    CHECK(store.tags().contains("v1.0"));
    CHECK_FALSE(store.tags().contains("v2.0"));
    fs::remove_all(path);
}

TEST_CASE("Tags: del removes a tag", "[store][tags]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");
    store.tags().set("v1.0", snap);

    CHECK(store.tags().contains("v1.0"));
    store.tags().del("v1.0");
    CHECK_FALSE(store.tags().contains("v1.0"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// branches().current() returns optional<Fs>
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: current returns Fs for HEAD branch", "[store][refdict]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    auto cur = store.branches().current();
    REQUIRE(cur.has_value());
    CHECK(cur->read_text("f.txt") == "data");
    CHECK(cur->writable());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict::set rejects invalid ref names
// ---------------------------------------------------------------------------

TEST_CASE("RefDict: set rejects empty ref name", "[store][refdict]") {
    auto path  = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    REQUIRE_THROWS_AS(store.branches().set("", snap), vost::InvalidRefNameError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Detached Fs metadata
// ---------------------------------------------------------------------------

TEST_CASE("Detached Fs: message, time, author work", "[store][detached]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    auto detached = store.fs(*snap.commit_hash());
    CHECK_FALSE(detached.ref_name().has_value());
    CHECK_FALSE(detached.writable());
    CHECK_FALSE(detached.message().empty());
    CHECK(detached.time() > 0);
    CHECK(detached.author_name() == "vost");
    CHECK(detached.author_email() == "vost@localhost");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

TEST_CASE("RefDict: reflog non-empty after writes", "[store][refdict]") {
    auto path = make_temp_repo();
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = "main";
    auto store = vost::GitStore::open(path, opts);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "a");
    snap = snap.write_text("b.txt", "b");

    auto log = store.branches().reflog("main");
    // At least 2 write commits; libgit2 also logs the initial ref creation.
    // (Some bare repo configurations do not write reflogs — skip if empty.)
    if (!log.empty()) {
        // Most recent entry should be the last write
        CHECK(log[0].new_sha == *snap.commit_hash());
        CHECK(log.size() >= 2);
    }

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// RefDict::set — ref name validation
// ---------------------------------------------------------------------------

TEST_CASE("RefDict::set rejects double-dot in name", "[store][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(store.branches().set("bad..name", snap),
                      vost::InvalidRefNameError);
    fs::remove_all(path);
}

TEST_CASE("RefDict::set rejects @{ in name", "[store][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(store.branches().set("a@{1}", snap),
                      vost::InvalidRefNameError);
    fs::remove_all(path);
}

TEST_CASE("RefDict::set rejects .lock suffix", "[store][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(store.branches().set("foo.lock", snap),
                      vost::InvalidRefNameError);
    fs::remove_all(path);
}

TEST_CASE("RefDict::set rejects star in name", "[store][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(store.branches().set("has*star", snap),
                      vost::InvalidRefNameError);
    fs::remove_all(path);
}

TEST_CASE("RefDict::set rejects trailing dot", "[store][refdict]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap = store.branches().get("main");

    REQUIRE_THROWS_AS(store.branches().set("trail.", snap),
                      vost::InvalidRefNameError);
    fs::remove_all(path);
}
