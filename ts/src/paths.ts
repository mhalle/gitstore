/**
 * Path normalization and validation utilities.
 */

/**
 * Return true if path represents the root (empty or only slashes).
 */
export function isRootPath(path: string): boolean {
  return path.replace(/[/\\]/g, '') === '';
}

/**
 * Normalize a repo path: strip leading/trailing slashes, reject bad segments.
 * Always uses forward slashes.
 */
export function normalizePath(path: string): string {
  path = path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!path) throw new Error('Path must not be empty');
  const segments = path.split('/');
  for (const seg of segments) {
    if (!seg) throw new Error(`Empty segment in path: '${path}'`);
    if (seg === '.' || seg === '..') throw new Error(`Invalid path segment: '${seg}'`);
  }
  return segments.join('/');
}

/**
 * Reject ref names containing ':', space, tab, or newline.
 */
export function validateRefName(name: string): void {
  const bad: [string, string][] = [
    [':', 'colon'],
    [' ', 'space'],
    ['\t', 'tab'],
    ['\n', 'newline'],
  ];
  for (const [ch, label] of bad) {
    if (name.includes(ch)) {
      throw new Error(`Invalid ref name '${name}': contains ${label}`);
    }
  }
}
