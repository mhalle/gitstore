#pragma once

#include "error.h"
#include "types.h"

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace vost {

struct GitStoreInner;
class NotesBatch;

// ---------------------------------------------------------------------------
// NoteNamespace — read/write notes under refs/notes/<namespace>
// ---------------------------------------------------------------------------

/// Access git notes under a single namespace (e.g. "commits", "reviews").
///
/// Notes are keyed by 40-char hex commit hashes. Each note is a UTF-8 string
/// stored as a blob in a tree committed to `refs/notes/<namespace>`.
///
/// Reads support both flat (40-char filename) and 2/38 fanout layout.
/// Writes always use flat layout.
class NoteNamespace {
public:
    NoteNamespace(std::shared_ptr<GitStoreInner> inner, std::string ns_name);

    /// Get the note text for a commit hash.
    /// @throws KeyNotFoundError if no note exists.
    /// @throws InvalidHashError if hash is not valid 40-char hex.
    std::string get(const std::string& hash) const;

    /// Set (or overwrite) the note text for a commit hash.
    /// @throws InvalidHashError if hash is not valid 40-char hex.
    void set(const std::string& hash, const std::string& text);

    /// Delete the note for a commit hash.
    /// @throws KeyNotFoundError if no note exists.
    /// @throws InvalidHashError if hash is not valid 40-char hex.
    void del(const std::string& hash);

    /// Return true if a note exists for this hash.
    bool has(const std::string& hash) const;

    /// Return all hashes that have notes (sorted).
    std::vector<std::string> list() const;

    /// Return the number of notes in this namespace.
    size_t size() const;

    /// Return true if no notes exist.
    bool empty() const;

    /// Get the note for the current HEAD branch's tip commit.
    /// @throws NotFoundError if HEAD is unresolvable or no note exists.
    std::string get_for_current_branch() const;

    /// Set the note for the current HEAD branch's tip commit.
    /// @throws NotFoundError if HEAD is unresolvable.
    void set_for_current_branch(const std::string& text);

    /// Create a batch for accumulating multiple note changes.
    NotesBatch batch();

    // -- Internal (used by NotesBatch) ---------------------------------------

    /// The namespace name (e.g. "commits").
    const std::string& namespace_name() const { return namespace_; }

    /// The full ref name (e.g. "refs/notes/commits").
    const std::string& ref_name() const { return ref_name_; }

    /// Access the shared inner state.
    std::shared_ptr<GitStoreInner> inner() const { return inner_; }

private:
    friend class NotesBatch;

    std::shared_ptr<GitStoreInner> inner_;
    std::string namespace_;
    std::string ref_name_;

    // -- Internal helpers ----------------------------------------------------

    /// Resolve the notes ref to its commit OID, or nullopt if no notes yet.
    std::optional<std::string> tip_oid() const;

    /// Get the tree OID from the tip commit, or nullopt.
    std::optional<std::string> tree_oid() const;

    /// Find a note blob OID in the tree (flat or fanout), or nullopt.
    std::optional<std::string> find_note(const std::string& tree_hex,
                                          const std::string& hash) const;

    /// Iterate all notes: (hash, blob_oid) pairs.
    std::vector<std::pair<std::string, std::string>> iter_notes(
        const std::string& tree_hex) const;

    /// Build a new tree from base, applying writes and deletes (flat layout).
    /// Returns the new tree OID hex.
    std::string build_note_tree(
        const std::optional<std::string>& base_tree_hex,
        const std::vector<std::pair<std::string, std::string>>& writes,
        const std::vector<std::string>& deletes) const;

    /// Commit a new tree to the notes ref with CAS.
    void commit_note_tree(const std::string& new_tree_hex,
                          const std::string& message);
};

// ---------------------------------------------------------------------------
// NotesBatch — accumulate note changes for a single commit
// ---------------------------------------------------------------------------

/// Accumulates note writes and deletes, then commits them in a single
/// git commit.
///
/// Usage:
/// @code
///     auto batch = ns.batch();
///     batch.set(hash1, "note 1");
///     batch.set(hash2, "note 2");
///     batch.commit();
/// @endcode
class NotesBatch {
public:
    explicit NotesBatch(NoteNamespace ns);

    /// Stage a note write.
    void set(const std::string& hash, const std::string& text);

    /// Stage a note deletion.
    void del(const std::string& hash);

    /// Commit all staged changes as a single commit.
    /// @throws BatchClosedError if already committed.
    void commit();

    bool committed() const { return committed_; }

private:
    NoteNamespace ns_;
    std::vector<std::pair<std::string, std::string>> writes_;
    std::vector<std::string> deletes_;
    bool committed_ = false;
};

// ---------------------------------------------------------------------------
// NoteDict — access point for all note namespaces
// ---------------------------------------------------------------------------

/// Access point for git notes.
/// Obtained via GitStore::notes().
///
/// Usage:
/// @code
///     auto notes = store.notes();
///     notes["commits"].set(hash, "reviewed");
///     notes.ns("reviews").get(hash);
/// @endcode
class NoteDict {
public:
    explicit NoteDict(std::shared_ptr<GitStoreInner> inner);

    /// Get a NoteNamespace by name.
    NoteNamespace operator[](const std::string& ns_name);

    /// Get a NoteNamespace by name.
    NoteNamespace ns(const std::string& ns_name);

    /// Shortcut for notes["commits"].
    NoteNamespace commits() { return (*this)["commits"]; }

private:
    std::shared_ptr<GitStoreInner> inner_;
};

} // namespace vost
