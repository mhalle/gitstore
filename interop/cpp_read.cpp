/**
 * Read repos written by another language and verify contents match fixtures.
 * Usage: cpp_read <fixtures.json> <repo_dir> <prefix>
 */

#include <vost/vost.h>
#include "json.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;
using json = nlohmann::json;

static std::vector<uint8_t> b64_decode(const std::string& encoded) {
    static const std::string chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    std::vector<uint8_t> out;
    std::vector<int> T(256, -1);
    for (int i = 0; i < 64; i++) T[static_cast<unsigned char>(chars[i])] = i;

    int val = 0, valb = -8;
    for (unsigned char c : encoded) {
        if (T[c] == -1) break;
        val = (val << 6) + T[c];
        valb += 6;
        if (valb >= 0) {
            out.push_back(static_cast<uint8_t>((val >> valb) & 0xFF));
            valb -= 8;
        }
    }
    return out;
}

static int check_basic(vost::Fs& snapshot, const json& spec,
                        const std::string& name) {
    int failures = 0;

    // Text files
    if (spec.contains("files")) {
        for (auto& [filepath, expected] : spec["files"].items()) {
            try {
                auto actual = snapshot.read_text(filepath);
                if (actual != expected.get<std::string>()) {
                    std::cout << "  FAIL " << name << ": " << filepath
                              << " content expected \"" << expected.get<std::string>()
                              << "\", got \"" << actual << "\"\n";
                    failures++;
                } else {
                    std::cout << "  OK   " << name << ": " << filepath << "\n";
                }
            } catch (const std::exception& e) {
                std::cout << "  FAIL " << name << ": " << filepath
                          << " error: " << e.what() << "\n";
                failures++;
            }
        }
    }

    // Symlinks
    if (spec.contains("symlinks")) {
        for (auto& [filepath, expected_target] : spec["symlinks"].items()) {
            try {
                auto actual = snapshot.readlink(filepath);
                if (actual != expected_target.get<std::string>()) {
                    std::cout << "  FAIL " << name << ": " << filepath
                              << " link target expected \""
                              << expected_target.get<std::string>()
                              << "\", got \"" << actual << "\"\n";
                    failures++;
                } else {
                    std::cout << "  OK   " << name << ": symlink " << filepath
                              << " -> " << actual << "\n";
                }
            } catch (const std::exception& e) {
                std::cout << "  FAIL " << name << ": " << filepath
                          << " error: " << e.what() << "\n";
                failures++;
            }
        }
    }

    // Binary files
    if (spec.contains("binary_files")) {
        for (auto& [filepath, b64] : spec["binary_files"].items()) {
            try {
                auto expected_bytes = b64_decode(b64.get<std::string>());
                auto actual_bytes = snapshot.read(filepath);
                if (actual_bytes != expected_bytes) {
                    std::cout << "  FAIL " << name << ": " << filepath
                              << " binary content mismatch\n";
                    failures++;
                } else {
                    std::cout << "  OK   " << name << ": binary " << filepath
                              << " (" << actual_bytes.size() << " bytes)\n";
                }
            } catch (const std::exception& e) {
                std::cout << "  FAIL " << name << ": " << filepath
                          << " error: " << e.what() << "\n";
                failures++;
            }
        }
    }

    // Executable files
    if (spec.contains("executable_files")) {
        for (auto& [filepath, expected] : spec["executable_files"].items()) {
            try {
                auto actual = snapshot.read_text(filepath);
                if (actual != expected.get<std::string>()) {
                    std::cout << "  FAIL " << name << ": " << filepath
                              << " content mismatch\n";
                    failures++;
                    continue;
                }
                // Check mode via walk
                auto dir_entries = snapshot.walk("");
                bool found = false;
                for (auto& de : dir_entries) {
                    for (auto& entry : de.files) {
                        std::string path = de.dirpath.empty()
                            ? entry.name : de.dirpath + "/" + entry.name;
                        if (path == filepath) {
                            auto ft = vost::file_type_from_mode(entry.mode);
                            if (!ft || *ft != vost::FileType::Executable) {
                                std::cout << "  FAIL " << name << ": " << filepath
                                          << " expected EXECUTABLE, got mode "
                                          << std::oct << entry.mode << std::dec << "\n";
                                failures++;
                            } else {
                                std::cout << "  OK   " << name << ": executable "
                                          << filepath << "\n";
                            }
                            found = true;
                            break;
                        }
                    }
                    if (found) break;
                }
                if (!found) {
                    std::cout << "  FAIL " << name << ": " << filepath
                              << " not found in walk\n";
                    failures++;
                }
            } catch (const std::exception& e) {
                std::cout << "  FAIL " << name << ": " << filepath
                          << " error: " << e.what() << "\n";
                failures++;
            }
        }
    }

    // Verify file count
    std::set<std::string> all_files;
    try {
        auto dir_entries = snapshot.walk("");
        for (auto& de : dir_entries) {
            for (auto& entry : de.files) {
                std::string path = de.dirpath.empty()
                    ? entry.name : de.dirpath + "/" + entry.name;
                all_files.insert(path);
            }
        }
    } catch (...) {}

    std::set<std::string> expected_files;
    if (spec.contains("files"))
        for (auto& [k, v] : spec["files"].items()) expected_files.insert(k);
    if (spec.contains("symlinks"))
        for (auto& [k, v] : spec["symlinks"].items()) expected_files.insert(k);
    if (spec.contains("binary_files"))
        for (auto& [k, v] : spec["binary_files"].items()) expected_files.insert(k);
    if (spec.contains("executable_files"))
        for (auto& [k, v] : spec["executable_files"].items()) expected_files.insert(k);

    std::vector<std::string> extra, missing;
    for (auto& f : all_files)
        if (expected_files.find(f) == expected_files.end()) extra.push_back(f);
    for (auto& f : expected_files)
        if (all_files.find(f) == all_files.end()) missing.push_back(f);

    if (!extra.empty()) {
        std::cout << "  FAIL " << name << ": unexpected files [";
        for (size_t i = 0; i < extra.size(); ++i) {
            if (i) std::cout << ", ";
            std::cout << "\"" << extra[i] << "\"";
        }
        std::cout << "]\n";
        failures++;
    }
    if (!missing.empty()) {
        std::cout << "  FAIL " << name << ": missing files [";
        for (size_t i = 0; i < missing.size(); ++i) {
            if (i) std::cout << ", ";
            std::cout << "\"" << missing[i] << "\"";
        }
        std::cout << "]\n";
        failures++;
    }

    return failures;
}

static int check_history(vost::GitStore& store, const std::string& branch,
                          const json& spec, const std::string& name) {
    int failures = 0;
    auto snapshot = store.branches()[branch];

    // Final state: last commit's files
    auto& commits = spec["commits"];
    auto& last = commits.back();
    if (last.contains("files")) {
        for (auto& [filepath, expected] : last["files"].items()) {
            try {
                auto actual = snapshot.read_text(filepath);
                if (actual != expected.get<std::string>()) {
                    std::cout << "  FAIL " << name << ": HEAD " << filepath
                              << " expected \"" << expected.get<std::string>()
                              << "\", got \"" << actual << "\"\n";
                    failures++;
                } else {
                    std::cout << "  OK   " << name << ": HEAD " << filepath << "\n";
                }
            } catch (const std::exception& e) {
                std::cout << "  FAIL " << name << ": HEAD " << filepath
                          << " error: " << e.what() << "\n";
                failures++;
            }
        }
    }

    // Removed files should not exist
    if (last.contains("removes")) {
        for (auto& filepath_val : last["removes"]) {
            auto filepath = filepath_val.get<std::string>();
            if (snapshot.exists(filepath)) {
                std::cout << "  FAIL " << name << ": " << filepath
                          << " should have been removed\n";
                failures++;
            } else {
                std::cout << "  OK   " << name << ": " << filepath << " removed\n";
            }
        }
    }

    // Walk back through history
    size_t num_commits = commits.size();
    try {
        auto back_fs = snapshot.back(static_cast<int>(num_commits) - 1);
        auto& first = commits[0];
        if (first.contains("files")) {
            for (auto& [filepath, expected] : first["files"].items()) {
                try {
                    auto actual = back_fs.read_text(filepath);
                    if (actual != expected.get<std::string>()) {
                        std::cout << "  FAIL " << name << ": commit[0] " << filepath
                                  << " expected \"" << expected.get<std::string>()
                                  << "\", got \"" << actual << "\"\n";
                        failures++;
                    } else {
                        std::cout << "  OK   " << name << ": commit[0] "
                                  << filepath << "\n";
                    }
                } catch (const std::exception& e) {
                    std::cout << "  FAIL " << name << ": commit[0] " << filepath
                              << " error: " << e.what() << "\n";
                    failures++;
                }
            }
        }
    } catch (const std::exception& e) {
        std::cout << "  FAIL " << name << ": back(" << (num_commits - 1)
                  << ") error: " << e.what() << "\n";
        failures++;
    }

    // Count commits by walking parents
    int count = 0;
    auto current = snapshot;
    while (true) {
        count++;
        auto p = current.parent();
        if (!p) break;
        current = *p;
    }
    // +1 for the initial empty commit created by GitStore.open
    int expected_count = static_cast<int>(num_commits) + 1;
    if (count != expected_count) {
        std::cout << "  FAIL " << name << ": expected " << expected_count
                  << " commits, found " << count << "\n";
        failures++;
    } else {
        std::cout << "  OK   " << name << ": " << count
                  << " commits in history\n";
    }

    return failures;
}

static int check_notes(vost::GitStore& store, const std::string& branch,
                        const json& spec, const std::string& name) {
    int failures = 0;
    auto snapshot = store.branches()[branch];
    auto commit_hash = *snapshot.commit_hash();

    for (auto& [ns_name, expected_text] : spec["notes"].items()) {
        try {
            auto actual = store.notes()[ns_name].get(commit_hash);
            if (actual != expected_text.get<std::string>()) {
                std::cout << "  FAIL " << name << ": notes[" << ns_name
                          << "] expected \"" << expected_text.get<std::string>()
                          << "\", got \"" << actual << "\"\n";
                failures++;
            } else {
                std::cout << "  OK   " << name << ": notes[" << ns_name << "]\n";
            }
        } catch (const std::exception&) {
            std::cout << "  FAIL " << name << ": notes[" << ns_name
                      << "] not found for " << commit_hash << "\n";
            failures++;
        }
    }

    return failures;
}

static std::string make_temp_dir() {
    std::string tmpl = (fs::temp_directory_path() / "vost-bundle-XXXXXX").string();
    std::vector<char> buf(tmpl.begin(), tmpl.end());
    buf.push_back('\0');
    if (!mkdtemp(buf.data())) {
        throw std::runtime_error("mkdtemp failed");
    }
    return std::string(buf.data());
}

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: cpp_read <fixtures.json> <repo_dir> <prefix> [bundle]\n";
        return 1;
    }

    std::string fixtures_path = argv[1];
    std::string repo_dir = argv[2];
    std::string prefix = argv[3];
    std::string mode = (argc > 4) ? argv[4] : "repo";

    std::ifstream f(fixtures_path);
    if (!f) {
        std::cerr << "Cannot open " << fixtures_path << "\n";
        return 1;
    }
    json fixtures = json::parse(f);

    int failures = 0;
    std::vector<std::string> temp_dirs;

    for (auto& [name, spec] : fixtures.items()) {
        std::string branch = spec.value("branch", "main");

        if (mode == "bundle") {
            std::string bundle_path = repo_dir + "/" + prefix + "_" + name + ".bundle";
            if (!fs::exists(bundle_path)) {
                std::cout << "  FAIL " << name << ": bundle not found at "
                          << bundle_path << "\n";
                failures++;
                continue;
            }
            std::string tmp = make_temp_dir();
            temp_dirs.push_back(tmp);
            std::string store_path = tmp + "/store.git";
            vost::OpenOptions opts;
            opts.create = true;
            opts.branch = branch;
            auto store = vost::GitStore::open(store_path, opts);
            store.restore(bundle_path);

            if (spec.contains("commits")) {
                failures += check_history(store, branch, spec, name);
            } else {
                auto snapshot = store.branches()[branch];
                failures += check_basic(snapshot, spec, name);
            }
            if (spec.contains("notes")) {
                failures += check_notes(store, branch, spec, name);
            }
        } else {
            std::string repo_path = repo_dir + "/" + prefix + "_" + name + ".git";
            if (!fs::exists(repo_path)) {
                std::cout << "  FAIL " << name << ": repo not found at "
                          << repo_path << "\n";
                failures++;
                continue;
            }
            vost::OpenOptions opts;
            opts.create = false;
            auto store = vost::GitStore::open(repo_path, opts);

            if (spec.contains("commits")) {
                failures += check_history(store, branch, spec, name);
            } else {
                auto snapshot = store.branches()[branch];
                failures += check_basic(snapshot, spec, name);
            }
            if (spec.contains("notes")) {
                failures += check_notes(store, branch, spec, name);
            }
        }
    }

    for (auto& tmp : temp_dirs) {
        fs::remove_all(tmp);
    }

    if (failures > 0) {
        std::cout << "\n" << failures << " failure(s)\n";
        return 1;
    } else {
        std::cout << "\nAll checks passed\n";
        return 0;
    }
}
