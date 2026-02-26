#include "vost/batch.h"
#include "vost/fs.h"
#include "internal.h"

namespace vost {

// ---------------------------------------------------------------------------
// Batch
// ---------------------------------------------------------------------------

Batch::Batch(Fs fs, BatchOptions opts)
    : fs_(std::move(fs))
    , message_(std::move(opts.message))
{}

void Batch::require_open() const {
    if (closed_) throw BatchClosedError();
}

// ---------------------------------------------------------------------------
// Write staging
// ---------------------------------------------------------------------------

Batch& Batch::write(const std::string& path, const std::vector<uint8_t>& data) {
    return write_with_mode(path, data, MODE_BLOB);
}

Batch& Batch::write_with_mode(const std::string& path,
                               const std::vector<uint8_t>& data,
                               uint32_t mode) {
    require_open();
    std::string norm = paths::normalize(path);

    // Remove from removes list if present
    removes_.erase(std::remove(removes_.begin(), removes_.end(), norm),
                   removes_.end());

    // Remove existing write for same path
    writes_.erase(
        std::remove_if(writes_.begin(), writes_.end(),
                       [&norm](const auto& kv) { return kv.first == norm; }),
        writes_.end());

    writes_.push_back({norm, {data, mode}});
    return *this;
}

Batch& Batch::write_text(const std::string& path, const std::string& text) {
    std::vector<uint8_t> data(text.begin(), text.end());
    return write(path, data);
}

Batch& Batch::write_symlink(const std::string& path, const std::string& target) {
    std::vector<uint8_t> data(target.begin(), target.end());
    return write_with_mode(path, data, MODE_LINK);
}

Batch& Batch::remove(const std::string& path) {
    require_open();
    std::string norm = paths::normalize(path);
    // Remove any pending write for this path
    writes_.erase(
        std::remove_if(writes_.begin(), writes_.end(),
                       [&norm](const auto& kv) { return kv.first == norm; }),
        writes_.end());

    // Add to removes if not already there
    if (std::find(removes_.begin(), removes_.end(), norm) == removes_.end()) {
        removes_.push_back(norm);
    }
    return *this;
}

// ---------------------------------------------------------------------------
// Commit
// ---------------------------------------------------------------------------

Fs Batch::commit() {
    require_open();
    closed_ = true;

    std::string msg;
    if (message_) {
        msg = *message_;
    } else {
        // Auto-generate from staged operations
        if (!writes_.empty() && removes_.empty()) {
            msg = "batch: write " + std::to_string(writes_.size()) + " file(s)";
        } else if (writes_.empty() && !removes_.empty()) {
            msg = "batch: remove " + std::to_string(removes_.size()) + " file(s)";
        } else {
            msg = "batch: " + std::to_string(writes_.size()) + " write(s), " +
                  std::to_string(removes_.size()) + " remove(s)";
        }
    }

    // Delegate to Fs::commit_changes (internal)
    return fs_.commit_changes(writes_, removes_, msg);
}

} // namespace vost
