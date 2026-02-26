/**
 * Gitignore-style exclude filter for copy_in/sync_in operations.
 *
 * Patterns follow gitignore semantics: `*` and `?` wildcards, negation with `!`,
 * directory-only patterns with a trailing `/`, and path-anchoring when `/` appears
 * in the pattern body. Unlike the vost glob matcher, dotfiles are NOT protected —
 * `*.pyc` will match `.hidden.pyc`.
 */

import { readFileSync, existsSync } from 'node:fs';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface Pattern {
  raw: string;
  negated: boolean;
  dirOnly: boolean;
}

/**
 * Convert a gitignore-style glob pattern to a RegExp.
 *
 * Supports `*` (any sequence of chars) and `?` (any single char).
 * Does NOT provide dotfile protection — `*` matches leading `.`.
 */
function patternToRegex(pattern: string): RegExp {
  let result = '^';
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern[i];
    if (ch === '*') {
      result += '.*';
    } else if (ch === '?') {
      result += '.';
    } else if ('.+^${}()|\\[]'.includes(ch)) {
      result += '\\' + ch;
    } else {
      result += ch;
    }
    i++;
  }
  result += '$';
  return new RegExp(result);
}

/**
 * Match a pattern against a path.
 *
 * If the pattern contains `/`, it is matched against the full relative path.
 * Otherwise it is matched against the basename only.
 */
function matchPattern(pattern: string, path: string): boolean {
  if (pattern.includes('/')) {
    return patternToRegex(pattern).test(path);
  }
  const slash = path.lastIndexOf('/');
  const basename = slash >= 0 ? path.slice(slash + 1) : path;
  return patternToRegex(pattern).test(basename);
}

// ---------------------------------------------------------------------------
// ExcludeFilter
// ---------------------------------------------------------------------------

/**
 * Gitignore-style exclude filter for copy_in/sync_in operations.
 *
 * Patterns are evaluated in order; later patterns take precedence.
 * A pattern prefixed with `!` negates the exclusion. A pattern ending
 * with `/` only matches directories. If a pattern contains `/` (other than
 * a trailing one), it is matched against the full relative path; otherwise
 * it is matched against the basename.
 *
 * @example
 * ```ts
 * const filter = new ExcludeFilter({ patterns: ['*.log', 'build/'] });
 * filter.isExcluded('app.log');          // true
 * filter.isExcluded('build', true);      // true (dir-only pattern)
 * filter.isExcluded('build/out.bin');    // false (not a dir itself)
 * ```
 */
export class ExcludeFilter {
  private _patterns: Pattern[] = [];

  /**
   * Create an ExcludeFilter.
   *
   * @param options.patterns   - Gitignore-style pattern strings to add immediately.
   * @param options.excludeFrom - Path to a file containing patterns (one per line).
   */
  constructor(options: { patterns?: string[]; excludeFrom?: string } = {}) {
    if (options.patterns != null) {
      this.addPatterns(options.patterns);
    }
    if (options.excludeFrom != null) {
      this.loadFromFile(options.excludeFrom);
    }
  }

  /** True if any patterns have been configured. */
  get active(): boolean {
    return this._patterns.length > 0;
  }

  /**
   * Add gitignore-style patterns to the filter.
   *
   * Blank lines and lines beginning with `#` are ignored.
   * A leading `!` negates the pattern. A trailing `/` makes it directory-only.
   *
   * @param patterns - Array of raw pattern strings.
   */
  addPatterns(patterns: string[]): void {
    for (const raw of patterns) {
      const trimmed = raw.trimEnd();
      if (trimmed.length === 0 || trimmed.startsWith('#')) continue;

      let s = trimmed;
      let negated = false;
      let dirOnly = false;

      if (s.startsWith('!')) {
        negated = true;
        s = s.slice(1);
      }
      if (s.endsWith('/')) {
        dirOnly = true;
        s = s.slice(0, -1);
      }
      if (s.length > 0) {
        this._patterns.push({ raw: s, negated, dirOnly });
      }
    }
  }

  /**
   * Load patterns from a file (one pattern per line, gitignore syntax).
   *
   * If the file does not exist, this is a no-op.
   *
   * @param path - Path to the patterns file (e.g. `.gitignore`).
   */
  loadFromFile(path: string): void {
    if (!existsSync(path)) return;
    const content = readFileSync(path, 'utf8');
    const lines = content.split('\n').map((l) => l.trimEnd()).filter((l) => l.length > 0);
    this.addPatterns(lines);
  }

  /**
   * Check whether a relative path should be excluded.
   *
   * Patterns are applied in order; the last matching pattern wins.
   * Negated patterns (`!`) un-exclude a previously excluded path.
   *
   * @param relPath - Repo-relative path to test (e.g. `'src/app.log'`).
   * @param isDir   - True if the path is a directory. Required for dir-only patterns.
   * @returns True if the path is excluded by the current pattern set.
   */
  isExcluded(relPath: string, isDir = false): boolean {
    let excluded = false;
    for (const p of this._patterns) {
      if (p.dirOnly && !isDir) continue;
      if (matchPattern(p.raw, relPath)) {
        excluded = !p.negated;
      }
    }
    return excluded;
  }
}
