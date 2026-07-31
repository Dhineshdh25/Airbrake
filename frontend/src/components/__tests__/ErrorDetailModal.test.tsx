import { getTraceDisplayText, getStackTraceDisplayText } from '../ErrorDetailModal';

describe('getTraceDisplayText', () => {
  it('returns the solution text when present', () => {
    expect(getTraceDisplayText('Traceback: ValueError', 'Use the new config')).toBe('Use the new config');
  });

  it('returns null when solution text is absent', () => {
    expect(getTraceDisplayText('Traceback: ValueError', null)).toBeNull();
    expect(getTraceDisplayText('Traceback: ValueError', '')).toBeNull();
  });

  it('returns null when both arguments are empty', () => {
    expect(getTraceDisplayText(undefined, null)).toBeNull();
    expect(getTraceDisplayText(null, undefined)).toBeNull();
  });

  it('returns solution text regardless of error_detail value', () => {
    expect(getTraceDisplayText(null, 'Fix the DB pool')).toBe('Fix the DB pool');
    expect(getTraceDisplayText('', 'Fix the DB pool')).toBe('Fix the DB pool');
  });
});

describe('getStackTraceDisplayText', () => {
  it('prefers AI explanation before raw_trace when there are no frames', () => {
    expect(getStackTraceDisplayText(
      "'Run' object has no attribute 'add_comment'",
      { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" } as any,
      'The request payload was malformed before the model could process it.',
      'The root cause was a bad JSON payload.'
    )).toBe('The request payload was malformed before the model could process it.');

    expect(getStackTraceDisplayText(
      'ValueError: invalid input',
      { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" } as any,
      null,
      'The root cause was a bad JSON payload.'
    )).toBe('The root cause was a bad JSON payload.');

    expect(getStackTraceDisplayText(
      'ValueError: invalid input',
      { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" } as any,
      null,
      null
    )).toBe("'Run' object has no attribute 'add_comment'");
  });
});
