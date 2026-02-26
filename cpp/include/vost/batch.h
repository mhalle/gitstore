#pragma once

#include "error.h"
#include "fs.h"
#include "types.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace vost {

// ---------------------------------------------------------------------------
// Batch — accumulate writes before committing
// ---------------------------------------------------------------------------

/// Accumulates writes and removes, then commits them atomically via commit().
///
/// Obtain a Batch via Fs::batch(). Calling commit() returns a new Fs.
///
/// Usage:
/// @code
///     auto batch = fs.batch();
///     batch.write("a.txt", data1);
///     batch.write("b.txt", data2);
///     fs = batch.commit();
/// @endcode
///
/// Fluent chaining (write() returns Batch&):
/// @code
///     fs = fs.batch()
///         .write("a.txt", data1)
///         .write("b.txt", data2)
///         .commit();
/// @endcode
class Batch {
public:
    explicit Batch(Fs fs, BatchOptions opts = {});

    // Non-copyable (contains move-only internal data)
    Batch(const Batch&) = delete;
    Batch& operator=(const Batch&) = delete;
    Batch(Batch&&) = default;
    Batch& operator=(Batch&&) = default;

    // -- Write staging -------------------------------------------------------

    /// Stage raw bytes at `path` with MODE_BLOB.
    /// @throws BatchClosedError if already committed.
    Batch& write(const std::string& path, const std::vector<uint8_t>& data);

    /// Stage raw bytes at `path` with an explicit mode.
    Batch& write_with_mode(const std::string& path,
                           const std::vector<uint8_t>& data,
                           uint32_t mode);

    /// Stage a UTF-8 string at `path`.
    Batch& write_text(const std::string& path, const std::string& text);

    /// Stage a symlink at `path` pointing to `target`.
    Batch& write_symlink(const std::string& path, const std::string& target);

    /// Stage `path` for removal.
    Batch& remove(const std::string& path);

    // -- Commit --------------------------------------------------------------

    /// Commit all staged changes and return the resulting Fs.
    /// After this call the Batch is closed — further writes throw BatchClosedError.
    Fs commit();

    // -- State ---------------------------------------------------------------

    bool closed() const { return closed_; }

    size_t pending_writes()  const { return writes_.size(); }
    size_t pending_removes() const { return removes_.size(); }

private:
    void require_open() const;

    Fs                                                             fs_;
    /// Each element: (normalized_path, {data, mode}).
    /// data is empty for removes that have been superseded.
    std::vector<std::pair<std::string,
                          std::pair<std::vector<uint8_t>, uint32_t>>> writes_;
    std::vector<std::string> removes_;
    std::optional<std::string>               message_;
    bool                                     closed_ = false;
};

} // namespace vost
