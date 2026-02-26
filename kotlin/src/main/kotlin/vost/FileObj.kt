package vost

import java.io.ByteArrayOutputStream

/**
 * Writable file-like object that commits on close.
 *
 * Use with Fs.writer():
 *   val w = fs.writer("output.bin")
 *   w.write("chunk1".toByteArray())
 *   w.write("chunk2".toByteArray())
 *   w.close()
 *   val newFs = w.fs!!
 */
class FsWriter internal constructor(
    private val _fs: Fs,
    private val path: String,
    private val encoding: String?,
) : AutoCloseable {

    private val buf = ByteArrayOutputStream()
    private var _closed = false

    /** The resulting Fs after close, or null if still open. */
    var fs: Fs? = null
        private set

    val closed: Boolean get() = _closed

    /** Write bytes to the buffer. */
    fun write(data: ByteArray): Int {
        if (_closed) throw IllegalStateException("I/O operation on closed writer.")
        if (encoding != null) throw IllegalArgumentException("expected text for text mode writer")
        buf.write(data)
        return data.size
    }

    /** Write text to the buffer (text mode only). */
    fun write(text: String): Int {
        if (_closed) throw IllegalStateException("I/O operation on closed writer.")
        val bytes = if (encoding != null) {
            text.toByteArray(charset(encoding))
        } else {
            throw IllegalArgumentException("expected bytes for binary mode writer")
        }
        buf.write(bytes)
        return bytes.size
    }

    override fun close() {
        if (!_closed) {
            fs = _fs.write(path, buf.toByteArray())
            _closed = true
        }
    }
}

/**
 * Writable file-like object that stages to a batch on close.
 *
 * Use with Batch.writer():
 *   batch.writer("log.txt", "w").use { w ->
 *       w.write("line 1\n")
 *       w.write("line 2\n")
 *   }
 */
class BatchWriter internal constructor(
    private val batch: Batch,
    private val path: String,
    private val encoding: String?,
) : AutoCloseable {

    private val buf = ByteArrayOutputStream()
    private var _closed = false

    val closed: Boolean get() = _closed

    /** Write bytes to the buffer. */
    fun write(data: ByteArray): Int {
        if (_closed) throw IllegalStateException("I/O operation on closed writer.")
        if (encoding != null) throw IllegalArgumentException("expected text for text mode writer")
        buf.write(data)
        return data.size
    }

    /** Write text to the buffer (text mode only). */
    fun write(text: String): Int {
        if (_closed) throw IllegalStateException("I/O operation on closed writer.")
        val bytes = if (encoding != null) {
            text.toByteArray(charset(encoding))
        } else {
            throw IllegalArgumentException("expected bytes for binary mode writer")
        }
        buf.write(bytes)
        return bytes.size
    }

    override fun close() {
        if (!_closed) {
            batch.write(path, buf.toByteArray())
            _closed = true
        }
    }
}
