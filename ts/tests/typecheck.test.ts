/**
 * Verify that tsc type-checking passes cleanly.
 * This catches type regressions that vitest (esbuild) doesn't surface.
 */

import { describe, it, expect } from 'vitest';
import { execSync } from 'node:child_process';
import * as path from 'node:path';

describe('tsc typecheck', () => {
  it('passes with no errors', () => {
    const tsDir = path.resolve(import.meta.dirname, '..');
    const result = execSync('npx tsc --noEmit', {
      cwd: tsDir,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    // execSync throws on non-zero exit, so reaching here means success
    expect(true).toBe(true);
  });
});
