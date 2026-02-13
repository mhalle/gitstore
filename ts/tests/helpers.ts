import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { GitStore, FS } from '../src/index.js';

const enc = new TextEncoder();
const dec = new TextDecoder();

export function toBytes(s: string): Uint8Array {
  return enc.encode(s);
}

export function fromBytes(b: Uint8Array): string {
  return dec.decode(b);
}

export function makeTmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'gitstore-test-'));
}

export function rmTmpDir(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

export async function freshStore(opts?: {
  branch?: string | null;
  author?: string;
  email?: string;
}): Promise<{ store: GitStore; tmpDir: string }> {
  const tmpDir = makeTmpDir();
  const repoPath = path.join(tmpDir, 'test.git');
  const store = await GitStore.open(repoPath, {
    fs,
    branch: opts?.branch !== undefined ? opts.branch : 'main',
    author: opts?.author,
    email: opts?.email,
  });
  return { store, tmpDir };
}

/**
 * Create a store pre-populated with files on "main":
 *   existing.txt, dir/a.txt, dir/b.txt, dir/.dotfile, other/c.txt
 */
export async function storeWithFiles(): Promise<{
  store: GitStore;
  fsSnap: FS;
  tmpDir: string;
}> {
  const { store, tmpDir } = await freshStore();
  let fsSnap = await store.branches.get('main');

  const b = fsSnap.batch({ message: 'seed files' });
  await b.write('existing.txt', toBytes('existing'));
  await b.write('dir/a.txt', toBytes('aaa'));
  await b.write('dir/b.txt', toBytes('bbb'));
  await b.write('dir/.dotfile', toBytes('dot'));
  await b.write('other/c.txt', toBytes('ccc'));
  fsSnap = await b.commit();

  return { store, fsSnap, tmpDir };
}

export { fs };
