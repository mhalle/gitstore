//! Buffered writers for [`Fs`] and [`Batch`].
//!
//! [`FsWriter`] accumulates writes and commits on [`close()`](FsWriter::close).
//! [`BatchWriter`] accumulates writes and stages to a [`Batch`] on
//! [`close()`](BatchWriter::close).
//!
//! Both implement [`std::io::Write`] so you can use `write!` / `write_all`.

use std::io;

use crate::batch::Batch;
use crate::error::Result;
use crate::fs::{Fs, WriteOptions};

/// Buffered writer that commits to an [`Fs`] on close.
///
/// Implements [`std::io::Write`] for streaming data. Call
/// [`close()`](FsWriter::close) to flush the buffer and commit.
///
/// # Example
///
/// ```rust,no_run
/// use std::io::Write;
/// use gitstore::{GitStore, Fs};
///
/// let store = GitStore::open("/tmp/repo").unwrap();
/// let fs = store.branches().get("main").unwrap();
/// let mut w = fs.writer("output.bin").unwrap();
/// w.write_all(b"chunk 1").unwrap();
/// w.write_all(b"chunk 2").unwrap();
/// let fs2 = w.close().unwrap();
/// ```
pub struct FsWriter {
    fs: Fs,
    path: String,
    buf: Vec<u8>,
    closed: bool,
}

impl FsWriter {
    pub(crate) fn new(fs: Fs, path: String) -> Self {
        Self {
            fs,
            path,
            buf: Vec::new(),
            closed: false,
        }
    }

    /// Whether this writer has been closed.
    pub fn closed(&self) -> bool {
        self.closed
    }

    /// Flush the buffer, commit, and return the new [`Fs`] snapshot.
    ///
    /// After closing, the writer cannot be used again.
    pub fn close(&mut self) -> Result<Fs> {
        if self.closed {
            return Ok(self.fs.clone());
        }
        let data = std::mem::take(&mut self.buf);
        let new_fs = self.fs.write(&self.path, &data, WriteOptions::default())?;
        self.fs = new_fs.clone();
        self.closed = true;
        Ok(new_fs)
    }
}

impl io::Write for FsWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.closed {
            return Err(io::Error::new(
                io::ErrorKind::Other,
                "I/O operation on closed writer",
            ));
        }
        self.buf.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl Drop for FsWriter {
    fn drop(&mut self) {
        if !self.closed {
            let _ = self.close();
        }
    }
}

/// Buffered writer that stages to a [`Batch`] on close.
///
/// Implements [`std::io::Write`] for streaming data. Call
/// [`close()`](BatchWriter::close) to flush the buffer and stage to the batch.
///
/// # Example
///
/// ```rust,no_run
/// use std::io::Write;
/// use gitstore::{GitStore, Fs};
/// use gitstore::fs::BatchOptions;
///
/// let store = GitStore::open("/tmp/repo").unwrap();
/// let fs = store.branches().get("main").unwrap();
/// let mut batch = fs.batch(Default::default());
/// let mut w = batch.writer("data.bin").unwrap();
/// w.write_all(b"chunk").unwrap();
/// w.close().unwrap();
/// let fs2 = batch.commit().unwrap();
/// ```
pub struct BatchWriter<'a> {
    batch: &'a mut Batch,
    path: String,
    buf: Vec<u8>,
    closed: bool,
}

impl<'a> BatchWriter<'a> {
    pub(crate) fn new(batch: &'a mut Batch, path: String) -> Self {
        Self {
            batch,
            path,
            buf: Vec::new(),
            closed: false,
        }
    }

    /// Whether this writer has been closed.
    pub fn closed(&self) -> bool {
        self.closed
    }

    /// Flush the buffer and stage the write to the batch.
    pub fn close(&mut self) -> Result<()> {
        if self.closed {
            return Ok(());
        }
        let data = std::mem::take(&mut self.buf);
        self.batch.write(&self.path, &data)?;
        self.closed = true;
        Ok(())
    }
}

impl io::Write for BatchWriter<'_> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.closed {
            return Err(io::Error::new(
                io::ErrorKind::Other,
                "I/O operation on closed writer",
            ));
        }
        self.buf.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl Drop for BatchWriter<'_> {
    fn drop(&mut self) {
        if !self.closed {
            let _ = self.close();
        }
    }
}
