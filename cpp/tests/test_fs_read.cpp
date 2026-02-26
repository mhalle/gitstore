#include <catch2/catch_test_macros.hpp>
#include <vost/vost.h>

#include <filesystem>
#include <string>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static fs::path make_temp_repo() {
    auto tmp = fs::temp_directory_path() /
               ("vost_rtest_" + std::to_string(
                    std::hash<std::thread::id>{}(std::this_thread::get_id())
                    ^ static_cast<size_t>(
                          std::chrono::steady_clock::now()
                              .time_since_epoch()
                              .count())));
    return tmp;
}

static vost::GitStore open_store(const fs::path& path, const std::string& branch = "main") {
    vost::OpenOptions opts;
    opts.create = true;
    opts.branch = branch;
    return vost::GitStore::open(path, opts);
}

// ---------------------------------------------------------------------------
// Fs metadata
// ---------------------------------------------------------------------------

TEST_CASE("Fs: commit_hash is non-empty after init", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");

    auto hash = snapshot.commit_hash();
    REQUIRE(hash.has_value());
    CHECK(hash->size() == 40);

    fs::remove_all(path);
}

TEST_CASE("Fs: tree_hash is non-empty after init", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");

    auto hash = snapshot.tree_hash();
    REQUIRE(hash.has_value());
    CHECK(hash->size() == 40);

    fs::remove_all(path);
}

TEST_CASE("Fs: ref_name matches branch name", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");

    REQUIRE(snapshot.ref_name().has_value());
    CHECK(*snapshot.ref_name() == "main");

    fs::remove_all(path);
}

TEST_CASE("Fs: writable is true for branch snapshot", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK(snapshot.writable());
    fs::remove_all(path);
}

TEST_CASE("Fs: message returns commit message", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path, "main");
    auto snapshot = store.branches().get("main");
    // Initial commit message is "Initialize main"
    CHECK(snapshot.message() == "Initialize main");
    fs::remove_all(path);
}

TEST_CASE("Fs: time returns positive epoch seconds", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK(snapshot.time() > 0);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Fs::exists / is_dir / file_type
// ---------------------------------------------------------------------------

TEST_CASE("Fs: exists returns false for nonexistent file", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK_FALSE(snapshot.exists("ghost.txt"));
    fs::remove_all(path);
}

TEST_CASE("Fs: exists returns true for root", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK(snapshot.exists(""));
    fs::remove_all(path);
}

TEST_CASE("Fs: is_dir returns true for root", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK(snapshot.is_dir(""));
    fs::remove_all(path);
}

TEST_CASE("Fs: is_dir returns false for nonexistent path", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK_FALSE(snapshot.is_dir("nothing"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// After writing a file — read operations
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read returns written bytes", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("hello.txt", "world");

    auto data = snapshot.read("hello.txt");
    std::string text(data.begin(), data.end());
    CHECK(text == "world");

    fs::remove_all(path);
}

TEST_CASE("Fs: read_text returns string", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("note.txt", "hello vost");

    CHECK(snapshot.read_text("note.txt") == "hello vost");
    fs::remove_all(path);
}

TEST_CASE("Fs: read throws NotFoundError for missing path", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    REQUIRE_THROWS_AS(snapshot.read("missing.txt"), vost::NotFoundError);
    fs::remove_all(path);
}

TEST_CASE("Fs: read throws IsADirectoryError for a dir", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("subdir/file.txt", "content");

    REQUIRE_THROWS_AS(snapshot.read("subdir"), vost::IsADirectoryError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// ls / walk
// ---------------------------------------------------------------------------

TEST_CASE("Fs: ls returns empty list for empty tree", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    CHECK(snapshot.ls().empty());
    fs::remove_all(path);
}

TEST_CASE("Fs: ls returns name strings after writing files", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("a.txt", "A");
    snapshot = snapshot.write_text("b.txt", "B");

    auto names = snapshot.ls();
    REQUIRE(names.size() == 2);
    std::sort(names.begin(), names.end());
    CHECK(names[0] == "a.txt");
    CHECK(names[1] == "b.txt");

    fs::remove_all(path);
}

TEST_CASE("Fs: ls throws NotADirectoryError for a file path", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("file.txt", "data");

    REQUIRE_THROWS_AS(snapshot.ls("file.txt"), vost::NotADirectoryError);
    fs::remove_all(path);
}

TEST_CASE("Fs: walk returns os.walk-style entries", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("a.txt", "A");
    snapshot = snapshot.write_text("sub/b.txt", "B");
    snapshot = snapshot.write_text("sub/deep/c.txt", "C");

    auto entries = snapshot.walk();
    // 3 directories: root, sub, sub/deep
    REQUIRE(entries.size() == 3);

    // Root entry
    CHECK(entries[0].dirpath == "");
    CHECK(entries[0].dirnames.size() == 1);
    CHECK(entries[0].dirnames[0] == "sub");
    CHECK(entries[0].files.size() == 1);
    CHECK(entries[0].files[0].name == "a.txt");

    // sub entry
    CHECK(entries[1].dirpath == "sub");
    CHECK(entries[1].dirnames.size() == 1);
    CHECK(entries[1].dirnames[0] == "deep");
    CHECK(entries[1].files.size() == 1);
    CHECK(entries[1].files[0].name == "b.txt");

    // sub/deep entry
    CHECK(entries[2].dirpath == "sub/deep");
    CHECK(entries[2].dirnames.empty());
    CHECK(entries[2].files.size() == 1);
    CHECK(entries[2].files[0].name == "c.txt");

    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// file_type / size / object_hash
// ---------------------------------------------------------------------------

TEST_CASE("Fs: file_type returns Blob for regular file", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("f.txt", "data");

    CHECK(snapshot.file_type("f.txt") == vost::FileType::Blob);
    fs::remove_all(path);
}

TEST_CASE("Fs: file_type returns Tree for directory", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("dir/file.txt", "data");

    CHECK(snapshot.file_type("dir") == vost::FileType::Tree);
    fs::remove_all(path);
}

TEST_CASE("Fs: file_type returns Link for symlink", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_symlink("link.txt", "target.txt");

    CHECK(snapshot.file_type("link.txt") == vost::FileType::Link);
    fs::remove_all(path);
}

TEST_CASE("Fs: size returns byte count", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("f.txt", "hello");

    CHECK(snapshot.size("f.txt") == 5);
    fs::remove_all(path);
}

TEST_CASE("Fs: size throws IsADirectoryError for directory", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("dir/f.txt", "x");

    REQUIRE_THROWS_AS(snapshot.size("dir"), vost::IsADirectoryError);
    fs::remove_all(path);
}

TEST_CASE("Fs: object_hash returns 40-char hex", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("f.txt", "hello");

    auto hash = snapshot.object_hash("f.txt");
    CHECK(hash.size() == 40);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// readlink
// ---------------------------------------------------------------------------

TEST_CASE("Fs: readlink returns symlink target", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_symlink("my_link", "some/target");

    CHECK(snapshot.readlink("my_link") == "some/target");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// stat
// ---------------------------------------------------------------------------

TEST_CASE("Fs: stat on root returns Tree type", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");

    auto sr = snapshot.stat("");
    CHECK(sr.file_type == vost::FileType::Tree);
    CHECK(sr.mode == vost::MODE_TREE);
    CHECK(sr.hash.size() == 40);
    fs::remove_all(path);
}

TEST_CASE("Fs: stat on file returns correct info", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("data.bin", "abcde");

    auto sr = snapshot.stat("data.bin");
    CHECK(sr.file_type == vost::FileType::Blob);
    CHECK(sr.size == 5);
    CHECK(sr.nlink == 1);
    CHECK(sr.hash.size() == 40);
    CHECK(sr.mtime > 0);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read_range / read_by_hash
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read_range returns subset of bytes", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("f.txt", "abcdefgh");

    auto slice = snapshot.read_range("f.txt", 2, 3);
    std::string s(slice.begin(), slice.end());
    CHECK(s == "cde");
    fs::remove_all(path);
}

TEST_CASE("Fs: read_by_hash returns correct data", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("f.txt", "hello");

    auto hash = snapshot.object_hash("f.txt");
    auto data = snapshot.read_by_hash(hash);
    std::string s(data.begin(), data.end());
    CHECK(s == "hello");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// History navigation
// ---------------------------------------------------------------------------

TEST_CASE("Fs: parent returns the previous snapshot", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("a.txt", "v1");
    snapshot = snapshot.write_text("a.txt", "v2");

    // parent should have "v1"
    auto p = snapshot.parent();
    REQUIRE(p.has_value());
    CHECK(p->read_text("a.txt") == "v1");

    fs::remove_all(path);
}

TEST_CASE("Fs: back(2) goes two commits back", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snapshot = store.branches().get("main");
    snapshot = snapshot.write_text("v.txt", "1");
    snapshot = snapshot.write_text("v.txt", "2");
    snapshot = snapshot.write_text("v.txt", "3");

    auto old = snapshot.back(2);
    CHECK(old.read_text("v.txt") == "1");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// object_hash content addressing
// ---------------------------------------------------------------------------

TEST_CASE("Fs: object_hash same content produces same hash", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a.txt", "same content");
    snap = snap.write_text("b.txt", "same content");

    CHECK(snap.object_hash("a.txt") == snap.object_hash("b.txt"));
    fs::remove_all(path);
}

TEST_CASE("Fs: object_hash different content produces different hash", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("x.txt", "alpha");
    snap = snap.write_text("y.txt", "beta");

    CHECK(snap.object_hash("x.txt") != snap.object_hash("y.txt"));
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// ls on a subdirectory
// ---------------------------------------------------------------------------

TEST_CASE("Fs: ls on a subdirectory returns its direct children", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("src/main.cpp", "int main(){}");
    snap = snap.write_text("src/util.cpp", "// util");
    snap = snap.write_text("README.md",    "# readme");

    auto names = snap.ls("src");
    REQUIRE(names.size() == 2);
    std::sort(names.begin(), names.end());
    CHECK(names[0] == "main.cpp");
    CHECK(names[1] == "util.cpp");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// walk subtree
// ---------------------------------------------------------------------------

TEST_CASE("Fs: walk from subtree prefix returns entries for that subtree", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a/x.txt", "x");
    snap = snap.write_text("a/y.txt", "y");
    snap = snap.write_text("b/z.txt", "z");

    auto entries = snap.walk("a");
    // Only 1 directory: a (with no subdirs)
    REQUIRE(entries.size() == 1);
    CHECK(entries[0].dirpath == "a");
    CHECK(entries[0].dirnames.empty());
    CHECK(entries[0].files.size() == 2);
    std::vector<std::string> names;
    for (auto& f : entries[0].files) names.push_back(f.name);
    std::sort(names.begin(), names.end());
    CHECK(names[0] == "x.txt");
    CHECK(names[1] == "y.txt");
    fs::remove_all(path);
}

TEST_CASE("Fs: walk on a file path raises NotADirectoryError", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    REQUIRE_THROWS_AS(snap.walk("file.txt"), vost::NotADirectoryError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// listdir alias
// ---------------------------------------------------------------------------

TEST_CASE("Fs: listdir returns WalkEntry while ls returns names", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("p.txt", "P");
    snap = snap.write_text("q.txt", "Q");

    auto names       = snap.ls();
    auto listdir_res = snap.listdir();

    REQUIRE(names.size() == listdir_res.size());
    std::sort(names.begin(), names.end());
    std::vector<std::string> listdir_names;
    for (auto& e : listdir_res) listdir_names.push_back(e.name);
    std::sort(listdir_names.begin(), listdir_names.end());
    CHECK(names == listdir_names);
    // listdir entries have OID and mode
    for (auto& e : listdir_res) {
        CHECK(e.oid.size() == 40);
        CHECK(e.mode != 0);
    }
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read_range edge cases
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read_range without size reads to end", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "abcdef");

    auto slice = snap.read_range("f.txt", 3);  // from offset 3 to end
    std::string s(slice.begin(), slice.end());
    CHECK(s == "def");
    fs::remove_all(path);
}

TEST_CASE("Fs: read_range with offset beyond size returns empty", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "short");

    auto slice = snap.read_range("f.txt", 100);
    CHECK(slice.empty());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// tree_hash changes with content
// ---------------------------------------------------------------------------

TEST_CASE("Fs: tree_hash changes after writing a file", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap1 = store.branches().get("main");
    auto snap2 = snap1.write_text("new.txt", "content");

    REQUIRE(snap1.tree_hash().has_value());
    REQUIRE(snap2.tree_hash().has_value());
    CHECK(*snap1.tree_hash() != *snap2.tree_hash());
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// readlink on non-symlink
// ---------------------------------------------------------------------------

TEST_CASE("Fs: readlink on regular file throws", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("file.txt", "data");

    REQUIRE_THROWS_AS(snap.readlink("file.txt"), vost::InvalidPathError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// stat — directory with subdirectories
// ---------------------------------------------------------------------------

TEST_CASE("Fs: stat root with subdirs has nlink >= 3", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("sub1/a.txt", "a");
    snap = snap.write_text("sub2/b.txt", "b");

    auto sr = snap.stat("");
    // nlink = 2 + number of immediate subdirs (sub1, sub2) = 4
    CHECK(sr.nlink >= 3);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Path normalization
// ---------------------------------------------------------------------------

TEST_CASE("Fs: path with leading slash is accepted", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a/b.txt", "hello");

    // Leading slash should normalize to "a/b.txt"
    CHECK(snap.read_text("/a/b.txt") == "hello");
    fs::remove_all(path);
}

TEST_CASE("Fs: path with double slashes is accepted", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("a/b.txt", "hello");

    // Double slashes should normalize to "a/b.txt"
    CHECK(snap.read_text("a//b.txt") == "hello");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Binary data with null bytes
// ---------------------------------------------------------------------------

TEST_CASE("Fs: binary data roundtrip with null bytes", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    std::vector<uint8_t> data = {0x00, 0x01, 0x00, 0xFF, 0x00};
    snap = snap.write("bin.dat", data);

    auto back = snap.read("bin.dat");
    REQUIRE(back.size() == 5);
    CHECK(back[0] == 0x00);
    CHECK(back[1] == 0x01);
    CHECK(back[2] == 0x00);
    CHECK(back[3] == 0xFF);
    CHECK(back[4] == 0x00);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// stat on symlink, executable, non-root directory
// ---------------------------------------------------------------------------

TEST_CASE("Fs: stat on a symlink returns Link type", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_symlink("my_link", "target");

    auto sr = snap.stat("my_link");
    CHECK(sr.file_type == vost::FileType::Link);
    CHECK(sr.mode == vost::MODE_LINK);
    CHECK(sr.nlink == 1);
    fs::remove_all(path);
}

TEST_CASE("Fs: stat on an executable returns Executable type", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");

    vost::WriteOptions opts;
    opts.mode = vost::MODE_BLOB_EXEC;
    snap = snap.write_text("script.sh", "#!/bin/sh\n", opts);

    auto sr = snap.stat("script.sh");
    CHECK(sr.file_type == vost::FileType::Executable);
    CHECK(sr.mode == vost::MODE_BLOB_EXEC);
    CHECK(sr.nlink == 1);
    CHECK(sr.size == 10);
    fs::remove_all(path);
}

TEST_CASE("Fs: stat on a non-root directory returns Tree type", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("sub/a.txt", "a");
    snap = snap.write_text("sub/inner/b.txt", "b");

    auto sr = snap.stat("sub");
    CHECK(sr.file_type == vost::FileType::Tree);
    CHECK(sr.mode == vost::MODE_TREE);
    // nlink = 2 + subdirs (1 subdir "inner") = 3
    CHECK(sr.nlink == 3);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read_by_hash with offset+size (partial) and invalid hash
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read_by_hash with offset and size (partial read)", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "abcdefghij");

    auto hash = snap.object_hash("f.txt");
    auto slice = snap.read_by_hash(hash, 3, 4);
    std::string s(slice.begin(), slice.end());
    CHECK(s == "defg");
    fs::remove_all(path);
}

TEST_CASE("Fs: read_by_hash with invalid hash throws", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    REQUIRE_THROWS_AS(snap.read_by_hash("not_a_valid_hex"), vost::InvalidHashError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read_range where offset+size exceeds file (clamp)
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read_range clamps when offset+size exceeds file size", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "short");

    auto slice = snap.read_range("f.txt", 2, 100);
    std::string s(slice.begin(), slice.end());
    CHECK(s == "ort");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// object_hash on a directory returns tree OID
// ---------------------------------------------------------------------------

TEST_CASE("Fs: object_hash on a directory returns tree OID", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("dir/file.txt", "data");

    auto dir_hash = snap.object_hash("dir");
    CHECK(dir_hash.size() == 40);
    // It should be different from the root tree hash
    auto root_hash = snap.tree_hash();
    CHECK(dir_hash != *root_hash);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// read() on a symlink returns target bytes
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read on a symlink returns target bytes", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_symlink("link", "some/target");

    auto data = snap.read("link");
    std::string s(data.begin(), data.end());
    CHECK(s == "some/target");
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------
// Path validation in reads
// ---------------------------------------------------------------------------

TEST_CASE("Fs: read '..' throws InvalidPathError", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    REQUIRE_THROWS_AS(snap.read(".."), vost::InvalidPathError);
    fs::remove_all(path);
}

TEST_CASE("Fs: read '.' throws InvalidPathError", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("f.txt", "data");

    REQUIRE_THROWS_AS(snap.read("."), vost::InvalidPathError);
    fs::remove_all(path);
}

// ---------------------------------------------------------------------------

TEST_CASE("Fs: path with trailing slash returns directory entries", "[fs][read]") {
    auto path = make_temp_repo();
    auto store = open_store(path);
    auto snap  = store.branches().get("main");
    snap = snap.write_text("dir/file.txt", "data");

    // Trailing slash should normalize: ls("dir/") == ls("dir")
    auto ls1 = snap.ls("dir");
    auto ls2 = snap.ls("dir/");
    REQUIRE(ls1.size() == ls2.size());
    CHECK(ls1[0] == ls2[0]);
    fs::remove_all(path);
}
