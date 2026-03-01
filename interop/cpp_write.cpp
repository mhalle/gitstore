/**
 * Write repos from fixtures.json so other languages can read them.
 * Usage: cpp_write <fixtures.json> <output_dir>
 */

#include <vost/vost.h>
#include "json.hpp"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

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

static std::vector<uint8_t> str_to_bytes(const std::string& s) {
    return std::vector<uint8_t>(s.begin(), s.end());
}

static void write_scenario(vost::GitStore& store, const std::string& branch,
                            const json& spec) {
    auto fs = store.branches()[branch];
    auto batch = fs.batch({});

    if (spec.contains("files")) {
        for (auto& [filepath, content] : spec["files"].items()) {
            batch.write(filepath, str_to_bytes(content.get<std::string>()));
        }
    }
    if (spec.contains("symlinks")) {
        for (auto& [filepath, target] : spec["symlinks"].items()) {
            batch.write_symlink(filepath, target.get<std::string>());
        }
    }
    if (spec.contains("binary_files")) {
        for (auto& [filepath, b64] : spec["binary_files"].items()) {
            batch.write(filepath, b64_decode(b64.get<std::string>()));
        }
    }
    if (spec.contains("executable_files")) {
        for (auto& [filepath, content] : spec["executable_files"].items()) {
            batch.write_with_mode(filepath,
                                   str_to_bytes(content.get<std::string>()),
                                   vost::MODE_BLOB_EXEC);
        }
    }

    batch.commit();
}

static void write_history(vost::GitStore& store, const std::string& branch,
                           const json& spec) {
    for (auto& step : spec["commits"]) {
        auto fs = store.branches()[branch];
        vost::BatchOptions opts;
        opts.message = step["message"].get<std::string>();
        auto batch = fs.batch(opts);

        if (step.contains("files")) {
            for (auto& [filepath, content] : step["files"].items()) {
                batch.write(filepath, str_to_bytes(content.get<std::string>()));
            }
        }
        if (step.contains("removes")) {
            for (auto& filepath : step["removes"]) {
                batch.remove(filepath.get<std::string>());
            }
        }

        batch.commit();
    }
}

static void write_notes(vost::GitStore& store, const std::string& branch,
                          const json& spec) {
    auto fs = store.branches()[branch];
    auto commit_hash = *fs.commit_hash();

    for (auto& [ns_name, text] : spec["notes"].items()) {
        store.notes()[ns_name].set(commit_hash, text.get<std::string>());
    }
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: cpp_write <fixtures.json> <output_dir>\n";
        return 1;
    }

    std::string fixtures_path = argv[1];
    std::string output_dir = argv[2];

    std::ifstream f(fixtures_path);
    if (!f) {
        std::cerr << "Cannot open " << fixtures_path << "\n";
        return 1;
    }
    json fixtures = json::parse(f);

    for (auto& [name, spec] : fixtures.items()) {
        std::string repo_path = output_dir + "/cpp_" + name + ".git";
        std::string branch = spec.value("branch", "main");

        vost::OpenOptions opts;
        opts.create = true;
        opts.branch = branch;
        auto store = vost::GitStore::open(repo_path, opts);

        if (spec.contains("commits")) {
            write_history(store, branch, spec);
        } else {
            write_scenario(store, branch, spec);
        }

        if (spec.contains("notes")) {
            write_notes(store, branch, spec);
        }

        store.backup(output_dir + "/cpp_" + name + ".bundle");
        std::cout << "  cpp_write: " << name << " -> " << repo_path << "\n";
    }

    return 0;
}
