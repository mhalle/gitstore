import { describe, it, expect } from 'vitest';
import {
  mirrorDiffInSync,
  mirrorDiffTotal,
  type MirrorDiff,
  type RefChange,
} from '../src/types.js';

describe('MirrorDiff structure', () => {
  it('empty diff is in_sync', () => {
    const diff: MirrorDiff = { add: [], update: [], delete: [] };
    expect(mirrorDiffInSync(diff)).toBe(true);
    expect(mirrorDiffTotal(diff)).toBe(0);
  });

  it('RefChange fields', () => {
    const rc: RefChange = { ref: 'refs/heads/main', oldTarget: 'abc', newTarget: 'def' };
    expect(rc.ref).toBe('refs/heads/main');
    expect(rc.oldTarget).toBe('abc');
    expect(rc.newTarget).toBe('def');
  });

  it('total counts all categories', () => {
    const diff: MirrorDiff = {
      add: [{ ref: 'a' }],
      update: [{ ref: 'b' }, { ref: 'c' }],
      delete: [{ ref: 'd' }],
    };
    expect(mirrorDiffTotal(diff)).toBe(4);
    expect(mirrorDiffInSync(diff)).toBe(false);
  });
});
