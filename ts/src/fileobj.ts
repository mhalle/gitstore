/**
 * Buffered writers for FS and Batch.
 *
 * FsWriter accumulates chunks and commits on close().
 * BatchWriter accumulates chunks and stages to a Batch on close().
 */

import type { FS } from './fs.js';
import type { Batch } from './batch.js';

function concatChunks(chunks: Uint8Array[]): Uint8Array {
  if (chunks.length === 0) return new Uint8Array(0);
  if (chunks.length === 1) return chunks[0];
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

/**
 * Buffered writer that commits to an FS on close.
 *
 * Accepts `Uint8Array` or `string` via `write()`. Strings are UTF-8 encoded.
 *
 * @example
 * ```ts
 * const w = fs.writer('output.bin');
 * w.write(new Uint8Array([1, 2, 3]));
 * await w.close();
 * const newFs = w.fs!;
 * ```
 */
export class FsWriter {
  private _fs: FS;
  private _path: string;
  private _chunks: Uint8Array[] = [];
  private _closed = false;

  /** The resulting FS snapshot after close. Null until `close()` completes. */
  fs: FS | null = null;

  /** @internal */
  constructor(fs: FS, path: string) {
    this._fs = fs;
    this._path = path;
  }

  /** Whether this writer has been closed. */
  get closed(): boolean {
    return this._closed;
  }

  /**
   * Buffer data for writing.
   *
   * @param data - Bytes or string to write. Strings are UTF-8 encoded.
   * @throws {Error} If the writer has been closed.
   */
  write(data: Uint8Array | string): void {
    if (this._closed) throw new Error('I/O operation on closed writer.');
    if (typeof data === 'string') data = new TextEncoder().encode(data);
    this._chunks.push(data);
  }

  /**
   * Flush buffered data and commit.
   *
   * After close, the resulting snapshot is available via `fs`.
   */
  async close(): Promise<void> {
    if (!this._closed) {
      this.fs = await this._fs.write(this._path, concatChunks(this._chunks));
      this._closed = true;
    }
  }
}

/**
 * Buffered writer that stages to a Batch on close.
 *
 * Accepts `Uint8Array` or `string` via `write()`. Strings are UTF-8 encoded.
 *
 * @example
 * ```ts
 * const batch = fs.batch();
 * const w = batch.writer('data.bin');
 * w.write(chunk1);
 * w.write(chunk2);
 * await w.close();
 * const result = await batch.commit();
 * ```
 */
export class BatchWriter {
  private _batch: Batch;
  private _path: string;
  private _chunks: Uint8Array[] = [];
  private _closed = false;

  /** @internal */
  constructor(batch: Batch, path: string) {
    this._batch = batch;
    this._path = path;
  }

  /** Whether this writer has been closed. */
  get closed(): boolean {
    return this._closed;
  }

  /**
   * Buffer data for writing.
   *
   * @param data - Bytes or string to write. Strings are UTF-8 encoded.
   * @throws {Error} If the writer has been closed.
   */
  write(data: Uint8Array | string): void {
    if (this._closed) throw new Error('I/O operation on closed writer.');
    if (typeof data === 'string') data = new TextEncoder().encode(data);
    this._chunks.push(data);
  }

  /**
   * Flush buffered data and stage to the batch.
   */
  async close(): Promise<void> {
    if (!this._closed) {
      await this._batch.write(this._path, concatChunks(this._chunks));
      this._closed = true;
    }
  }
}
