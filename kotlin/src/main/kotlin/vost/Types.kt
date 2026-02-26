package vost

/**
 * Git file type enum.
 *
 * Members: BLOB, EXECUTABLE, LINK, TREE.
 */
enum class FileType {
    BLOB,
    EXECUTABLE,
    LINK,
    TREE;

    /** Return the git filemode integer for this type. */
    fun filemode(): Int = when (this) {
        BLOB -> GIT_FILEMODE_BLOB
        EXECUTABLE -> GIT_FILEMODE_BLOB_EXECUTABLE
        LINK -> GIT_FILEMODE_LINK
        TREE -> GIT_FILEMODE_TREE
    }

    companion object {
        /** Convert a git filemode integer to a FileType. */
        fun fromMode(mode: Int): FileType = when (mode) {
            GIT_FILEMODE_BLOB -> BLOB
            GIT_FILEMODE_BLOB_EXECUTABLE -> EXECUTABLE
            GIT_FILEMODE_LINK -> LINK
            GIT_FILEMODE_TREE -> TREE
            else -> throw IllegalArgumentException("Unknown filemode: ${mode.toString(8)}")
        }
    }
}

/** Git filemode constants. */
const val GIT_FILEMODE_TREE: Int = 0x4000            // 0o040000
const val GIT_FILEMODE_BLOB: Int = 0x81A4            // 0o100644
const val GIT_FILEMODE_BLOB_EXECUTABLE: Int = 0x81ED // 0o100755
const val GIT_FILEMODE_LINK: Int = 0xA000            // 0o120000

/**
 * A file entry yielded by walk and listdir.
 *
 * @property name Entry name (file or directory basename).
 * @property oid 40-char hex object ID.
 * @property mode Git filemode integer (e.g. 0o100644).
 */
data class WalkEntry(
    val name: String,
    val oid: String,
    val mode: Int,
) {
    /** Return the FileType for this entry. */
    val fileType: FileType get() = FileType.fromMode(mode)
}

/**
 * os.walk-style directory entry.
 *
 * @property dirpath Directory path relative to walk root.
 * @property dirnames Subdirectory names in this directory.
 * @property files File entries in this directory.
 */
data class WalkDirEntry(
    val dirpath: String,
    val dirnames: List<String>,
    val files: List<WalkEntry>,
)

/**
 * POSIX-like stat result for a vost path.
 *
 * @property mode Raw git filemode (e.g. 0o100644, 0o040000).
 * @property fileType FileType enum value.
 * @property size Object size in bytes (0 for directories).
 * @property hash 40-char hex SHA of the object.
 * @property nlink 1 for files/symlinks, 2 + subdirs for directories.
 * @property mtime Commit timestamp as POSIX epoch seconds.
 */
data class StatResult(
    val mode: Int,
    val fileType: FileType,
    val size: Long,
    val hash: String,
    val nlink: Int,
    val mtime: Long,
)

/**
 * Describes a single file write for Fs.apply().
 *
 * Exactly one of data or target must be provided.
 *
 * @property data Raw bytes, text string, or null.
 * @property mode Optional file mode override.
 * @property target Symlink target string (mutually exclusive with data).
 */
data class WriteEntry(
    val data: ByteArray? = null,
    val mode: FileType? = null,
    val target: String? = null,
) {
    init {
        require(!(data != null && target != null)) { "Cannot specify both data and target" }
        require(data != null || target != null) { "Must specify either data or target" }
        require(!(target != null && mode != null)) { "Cannot specify mode for symlinks" }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is WriteEntry) return false
        return data.contentEquals(other.data) && mode == other.mode && target == other.target
    }

    override fun hashCode(): Int {
        var result = data?.contentHashCode() ?: 0
        result = 31 * result + (mode?.hashCode() ?: 0)
        result = 31 * result + (target?.hashCode() ?: 0)
        return result
    }
}

/**
 * A file path with type information, used in ChangeReport lists.
 *
 * @property path Relative path (repo-style forward slashes).
 * @property fileType FileType of the entry.
 */
data class FileEntry(
    val path: String,
    val fileType: FileType,
) {
    companion object {
        fun fromMode(path: String, mode: Int): FileEntry =
            FileEntry(path, FileType.fromMode(mode))
    }
}

/** Kind of change action: ADD, UPDATE, or DELETE. */
enum class ChangeActionKind {
    ADD, UPDATE, DELETE
}

/**
 * A single add/update/delete action in a ChangeReport.
 */
data class ChangeAction(
    val path: String,
    val action: ChangeActionKind,
)

/**
 * A file that failed during an operation.
 */
data class ChangeError(
    val path: String,
    val error: String,
)

/**
 * Result of a copy, sync, move, or remove operation.
 */
data class ChangeReport(
    val add: List<FileEntry> = emptyList(),
    val update: List<FileEntry> = emptyList(),
    val delete: List<FileEntry> = emptyList(),
    val errors: List<ChangeError> = emptyList(),
    val warnings: List<ChangeError> = emptyList(),
) {
    /** True if there are no add, update, or delete actions. */
    val inSync: Boolean get() = add.isEmpty() && update.isEmpty() && delete.isEmpty()

    /** Total number of add + update + delete actions. */
    val total: Int get() = add.size + update.size + delete.size

    /** Return all actions as a flat list sorted by path. */
    fun actions(): List<ChangeAction> {
        val result = mutableListOf<ChangeAction>()
        for (e in add) result.add(ChangeAction(e.path, ChangeActionKind.ADD))
        for (e in update) result.add(ChangeAction(e.path, ChangeActionKind.UPDATE))
        for (e in delete) result.add(ChangeAction(e.path, ChangeActionKind.DELETE))
        result.sortBy { it.path }
        return result
    }
}

/**
 * Author/committer identity used for commits.
 */
data class Signature(
    val name: String,
    val email: String,
) {
    internal val identity: String get() = "$name <$email>"
}

/**
 * A single reflog entry recording a branch movement.
 */
data class ReflogEntry(
    val oldSha: String,
    val newSha: String,
    val committer: String,
    val timestamp: Long,
    val message: String,
)

/**
 * Mirror diff describing ref changes.
 */
data class MirrorDiff(
    val add: List<RefChange> = emptyList(),
    val update: List<RefChange> = emptyList(),
    val delete: List<RefChange> = emptyList(),
)

/**
 * A single ref change in a mirror operation.
 */
data class RefChange(
    val refName: String,
    val oldTarget: String?,
    val newTarget: String?,
)

/** Byte content wrapper that signals this is a pre-hashed blob OID. */
@JvmInline
value class BlobOid(val hex: String)

/**
 * Generates commit message from changes.
 */
internal fun formatCommitMessage(
    changes: ChangeReport,
    customMessage: String?,
    operation: String?,
): String {
    if (customMessage != null) return customMessage
    return autoMessage(changes, operation)
}

private fun autoMessage(changes: ChangeReport, operation: String?): String {
    if (changes.total == 0) return "No changes"

    if (changes.total == 1) {
        if (changes.add.isNotEmpty()) {
            val e = changes.add[0]
            val suffix = if (e.fileType != FileType.BLOB) " (${e.fileType.name.lowercase()})" else ""
            return "+ ${e.path}$suffix"
        } else if (changes.update.isNotEmpty()) {
            val e = changes.update[0]
            val suffix = if (e.fileType != FileType.BLOB) " (${e.fileType.name.lowercase()})" else ""
            return "~ ${e.path}$suffix"
        } else {
            return "- ${changes.delete[0].path}"
        }
    }

    val parts = mutableListOf<String>()
    if (changes.add.isNotEmpty()) parts.add("+${changes.add.size}")
    if (changes.update.isNotEmpty()) parts.add("~${changes.update.size}")
    if (changes.delete.isNotEmpty()) parts.add("-${changes.delete.size}")

    val prefix = if (operation != null) "Batch $operation:" else "Batch:"
    return "$prefix ${parts.joinToString(" ")}"
}
