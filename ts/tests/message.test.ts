import { describe, it, expect } from 'vitest';
import {
  formatCommitMessage,
  emptyChangeReport,
  changeReportTotal,
  type ChangeReport,
  type FileEntry,
  FileType,
} from '../src/types.js';

function makeReport(add = 0, update = 0, del = 0): ChangeReport {
  const r = emptyChangeReport();
  for (let i = 0; i < add; i++) {
    r.add.push({ path: `add${i}.txt`, type: FileType.BLOB });
  }
  for (let i = 0; i < update; i++) {
    r.update.push({ path: `upd${i}.txt`, type: FileType.BLOB });
  }
  for (let i = 0; i < del; i++) {
    r.delete.push({ path: `del${i}.txt`, type: FileType.BLOB });
  }
  return r;
}

describe('plain message', () => {
  it('returns custom message as-is', () => {
    const msg = formatCommitMessage(makeReport(1), 'my message');
    expect(msg).toBe('my message');
  });

  it('generates auto message when no custom', () => {
    const msg = formatCommitMessage(makeReport(1));
    expect(msg).toContain('add0.txt');
  });
});

describe('default placeholder', () => {
  it('{default} with single add', () => {
    const msg = formatCommitMessage(makeReport(1), '{default}');
    expect(msg).toBe('+ add0.txt');
  });

  it('{default} batch with operation', () => {
    const msg = formatCommitMessage(makeReport(2, 1), '{default}', 'sync');
    expect(msg).toBe('Batch sync: +2 ~1');
  });

  it('{default} batch without operation', () => {
    const msg = formatCommitMessage(makeReport(2, 1), '{default}');
    expect(msg).toBe('Batch: +2 ~1');
  });

  it('{default} empty report', () => {
    const msg = formatCommitMessage(makeReport(0, 0, 0), '{default}');
    expect(msg).toBe('No changes');
  });
});

describe('count placeholders', () => {
  it('{add_count} {update_count} {delete_count}', () => {
    const msg = formatCommitMessage(
      makeReport(3, 2, 1),
      'a={add_count} u={update_count} d={delete_count}',
    );
    expect(msg).toBe('a=3 u=2 d=1');
  });

  it('{total_count}', () => {
    const msg = formatCommitMessage(makeReport(2, 3, 4), 'total={total_count}');
    expect(msg).toBe('total=9');
  });

  it('zero counts', () => {
    const msg = formatCommitMessage(
      makeReport(0, 0, 0),
      'a={add_count} u={update_count} d={delete_count}',
    );
    expect(msg).toBe('a=0 u=0 d=0');
  });
});

describe('op placeholder', () => {
  it('{op} with operation', () => {
    const msg = formatCommitMessage(makeReport(1), 'op={op}', 'cp');
    expect(msg).toBe('op=cp');
  });

  it('{op} without operation', () => {
    const msg = formatCommitMessage(makeReport(1), 'op={op}');
    expect(msg).toBe('op=');
  });
});

describe('mixed placeholders', () => {
  it('all placeholders in one message', () => {
    const msg = formatCommitMessage(
      makeReport(1, 2, 3),
      '{op}: {add_count}+{update_count}~{delete_count}- (total {total_count}) [{default}]',
      'sync',
    );
    expect(msg).toBe('sync: 1+2~3- (total 6) [Batch sync: +1 ~2 -3]');
  });
});

describe('auto message details', () => {
  it('single add shows path', () => {
    const msg = formatCommitMessage(makeReport(1));
    expect(msg).toBe('+ add0.txt');
  });

  it('single update shows path with ~', () => {
    const msg = formatCommitMessage(makeReport(0, 1));
    expect(msg).toBe('~ upd0.txt');
  });

  it('single delete shows path with -', () => {
    const msg = formatCommitMessage(makeReport(0, 0, 1));
    expect(msg).toBe('- del0.txt');
  });

  it('single add with non-blob type appends type', () => {
    const r = emptyChangeReport();
    r.add.push({ path: 'link.txt', type: FileType.LINK });
    const msg = formatCommitMessage(r);
    expect(msg).toBe('+ link.txt (link)');
  });

  it('batch message with all categories', () => {
    const msg = formatCommitMessage(makeReport(2, 3, 1));
    expect(msg).toBe('Batch: +2 ~3 -1');
  });
});
