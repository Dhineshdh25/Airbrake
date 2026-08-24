import { describe, it, expect } from '@jest/globals';
import { coercePageValue } from '../PaginationControls';

describe('coercePageValue', () => {
  it('accepts valid page numbers inside range and rejects invalid ones', () => {
    expect(coercePageValue('11', 12)).toBe(11);
    expect(coercePageValue('1', 12)).toBe(1);
    expect(coercePageValue('12', 12)).toBe(12);
    expect(coercePageValue('0', 12)).toBe(1);
    expect(coercePageValue('999', 12)).toBe(12);
    expect(coercePageValue('abc', 12)).toBeNull();
    expect(coercePageValue('1.5', 12)).toBeNull();
    expect(coercePageValue('', 12)).toBeNull();
  });
});
