/**
 * Reflog read/write using direct filesystem access.
 *
 * Git reflog format (one line per entry):
 *   <old-sha> <new-sha> <committer> <timestamp> <tz>\t<message>\n
 */

import type { FsModule, ReflogEntry } from './types.js';

/** The all-zeros SHA used for newly-created refs in reflog entries. */
const ZERO_SHA = '0000000000000000000000000000000000000000';

/**
 * Read reflog entries for a branch.
 * Returns entries in chronological order (oldest first).
 *
 * @param fsModule   - Node.js-compatible fs module.
 * @param gitdir     - Path to the bare git repository.
 * @param branchName - Branch name (e.g. "main").
 * @returns Array of {@link ReflogEntry} objects.
 * @throws Error if no reflog file exists for the branch.
 */
export async function readReflog(
  fsModule: FsModule,
  gitdir: string,
  branchName: string,
): Promise<ReflogEntry[]> {
  const reflogPath = `${gitdir}/logs/refs/heads/${branchName}`;

  let data: string;
  try {
    const raw = await fsModule.promises.readFile(reflogPath, { encoding: 'utf8' });
    data = typeof raw === 'string' ? raw : new TextDecoder().decode(raw);
  } catch (err: any) {
    if (err?.code === 'ENOENT') {
      throw new Error(`No reflog found for branch '${branchName}'`);
    }
    throw err;
  }

  const entries: ReflogEntry[] = [];
  for (const line of data.split('\n')) {
    if (!line.trim()) continue;

    // Format: <old> <new> <committer> <timestamp> <tz>\t<message>
    const tabIdx = line.indexOf('\t');
    const message = tabIdx >= 0 ? line.slice(tabIdx + 1) : '';
    const header = tabIdx >= 0 ? line.slice(0, tabIdx) : line;

    // Parse header: old_sha new_sha committer_name <email> timestamp tz
    const oldSha = header.slice(0, 40);
    const newSha = header.slice(41, 81);
    const rest = header.slice(82); // "Name <email> timestamp tz"

    // Extract timestamp: find the last two space-separated tokens
    const parts = rest.split(' ');
    const tz = parts.pop() ?? '+0000';
    const timestampStr = parts.pop() ?? '0';
    const committer = parts.join(' ');

    entries.push({
      oldSha,
      newSha,
      committer,
      timestamp: parseInt(timestampStr, 10),
      message,
    });
  }

  return entries;
}

/**
 * Append a reflog entry for a ref update.
 *
 * @param fsModule  - Node.js-compatible fs module.
 * @param gitdir    - Path to the bare git repository.
 * @param refName   - Full ref name (e.g. "refs/heads/main").
 * @param oldSha    - Previous 40-char hex commit SHA (ZERO_SHA for new refs).
 * @param newSha    - New 40-char hex commit SHA.
 * @param committer - Identity string (e.g. "vost \<vost@localhost\>").
 * @param message   - Reflog message (e.g. "commit: + file.txt").
 */
export async function writeReflogEntry(
  fsModule: FsModule,
  gitdir: string,
  refName: string,
  oldSha: string,
  newSha: string,
  committer: string,
  message: string,
): Promise<void> {
  // Construct reflog path: refs/heads/main → logs/refs/heads/main
  const reflogPath = `${gitdir}/logs/${refName}`;

  // Create parent directories
  const parentDir = reflogPath.slice(0, reflogPath.lastIndexOf('/'));
  await fsModule.promises.mkdir(parentDir, { recursive: true });

  // Format entry
  const timestamp = Math.floor(Date.now() / 1000);
  const line = `${oldSha} ${newSha} ${committer} ${timestamp} +0000\t${message}\n`;

  // Append
  await fsModule.promises.appendFile(reflogPath, line);
}

export { ZERO_SHA };
