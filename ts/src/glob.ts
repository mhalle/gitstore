/**
 * Glob matching utilities for gitstore.
 *
 * Provides fnmatch-style matching with dotfile-aware semantics:
 * `*` and `?` do not match a leading `.` unless the pattern itself starts with `.`.
 */

/**
 * Match a single filename against a glob pattern segment.
 *
 * Supports `*`, `?`, `[seq]`, and `[!seq]`. Does not match across `/`.
 * A leading `.` in name is not matched by `*` or `?` unless the pattern
 * itself starts with `.` (Unix/rsync convention).
 */
export function globMatch(pattern: string, name: string): boolean {
  if (!pattern.startsWith('.') && name.startsWith('.')) {
    return false;
  }
  return fnmatch(pattern, name);
}

/**
 * fnmatch-style glob matching (single segment, no path separators).
 * Supports `*`, `?`, `[seq]`, `[!seq]`.
 */
function fnmatch(pattern: string, name: string): boolean {
  const regex = globToRegex(pattern);
  return regex.test(name);
}

function globToRegex(pattern: string): RegExp {
  let result = '^';
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern[i];
    if (ch === '*') {
      result += '.*';
    } else if (ch === '?') {
      result += '.';
    } else if (ch === '[') {
      let j = i + 1;
      let negate = false;
      if (j < pattern.length && pattern[j] === '!') {
        negate = true;
        j++;
      }
      const end = pattern.indexOf(']', j);
      if (end < 0) {
        // No closing bracket — treat `[` as literal
        result += '\\[';
      } else {
        const chars = pattern.slice(j, end).replace(/[\\\]^]/g, '\\$&');
        result += negate ? `[^${chars}]` : `[${chars}]`;
        i = end;
      }
    } else if ('.+^${}()|\\'.includes(ch)) {
      result += '\\' + ch;
    } else {
      result += ch;
    }
    i++;
  }
  result += '$';
  return new RegExp(result);
}
