"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const globals_1 = require("@jest/globals");
const PaginationControls_1 = require("../PaginationControls");
(0, globals_1.describe)('coercePageValue', () => {
    (0, globals_1.it)('accepts valid page numbers inside range and rejects invalid ones', () => {
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('11', 12)).toBe(11);
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('1', 12)).toBe(1);
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('12', 12)).toBe(12);
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('0', 12)).toBe(1);
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('999', 12)).toBe(12);
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('abc', 12)).toBeNull();
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('1.5', 12)).toBeNull();
        (0, globals_1.expect)((0, PaginationControls_1.coercePageValue)('', 12)).toBeNull();
    });
});
//# sourceMappingURL=PaginationControls.test.js.map