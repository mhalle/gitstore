/**
 * Path normalization and validation utilities.
 */

import { InvalidPathError, InvalidRefNameError } from './types.js';

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
  if (!path) throw new InvalidPathError('Path must not be empty');
  const segments = path.split('/');
  for (const seg of segments) {
    if (!seg) throw new InvalidPathError(`Empty segment in path: '${path}'`);
    if (seg === '.' || seg === '..') throw new InvalidPathError(`Invalid path segment: '${seg}'`);
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
      throw new InvalidRefNameError(`Invalid ref name '${name}': contains ${label}`);
    }
  }
}
