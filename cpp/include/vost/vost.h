#pragma once

/// @file vost.h
/// Umbrella header — include this to get the full vost C++ API.

#include "error.h"
#include "types.h"
#include "gitstore.h"
#include "fs.h"
#include "batch.h"
#include "notes.h"
#include "mirror.h"

#include <algorithm>
#include <chrono>
#include <thread>
#include <type_traits>

namespace vost {

/// Glob pattern matching against the local filesystem.
/// Matches files using dotfile-aware glob rules.
/// Returns sorted results.
std::vector<std::string> disk_glob(const std::string& pattern,
                                    const std::string& root = ".");

/// Retry a write operation with exponential backoff on StaleSnapshotError.
///
/// Calls `f()` up to 6 times (1 initial + 5 retries).  On each
/// StaleSnapshotError, sleeps min(10 * 2^attempt, 200) ms before retrying.
///
/// @code
///     auto result = vost::retry_write([&]() {
///         auto fs = store.branches()["main"];
///         return fs.write_text("counter.txt", std::to_string(++n));
///     });
/// @endcode
template <typename F>
auto retry_write(F&& f) -> decltype(f()) {
    constexpr int max_retries = 5;
    for (int attempt = 0; ; ++attempt) {
        try {
            return f();
        } catch (const StaleSnapshotError&) {
            if (attempt >= max_retries) throw;
            int delay_ms = std::min(10 * (1 << attempt), 200);
            std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
        }
    }
}

} // namespace vost
