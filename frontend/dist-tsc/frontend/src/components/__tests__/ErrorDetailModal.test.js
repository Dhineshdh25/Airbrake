"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const ErrorDetailModal_1 = require("../ErrorDetailModal");
describe('getTraceDisplayText', () => {
    it('returns the solution text when present', () => {
        expect((0, ErrorDetailModal_1.getTraceDisplayText)('Traceback: ValueError', 'Use the new config')).toBe('Use the new config');
    });
    it('returns null when solution text is absent', () => {
        expect((0, ErrorDetailModal_1.getTraceDisplayText)('Traceback: ValueError', null)).toBeNull();
        expect((0, ErrorDetailModal_1.getTraceDisplayText)('Traceback: ValueError', '')).toBeNull();
    });
    it('returns null when both arguments are empty', () => {
        expect((0, ErrorDetailModal_1.getTraceDisplayText)(undefined, null)).toBeNull();
        expect((0, ErrorDetailModal_1.getTraceDisplayText)(null, undefined)).toBeNull();
    });
    it('returns solution text regardless of error_detail value', () => {
        expect((0, ErrorDetailModal_1.getTraceDisplayText)(null, 'Fix the DB pool')).toBe('Fix the DB pool');
        expect((0, ErrorDetailModal_1.getTraceDisplayText)('', 'Fix the DB pool')).toBe('Fix the DB pool');
    });
});
describe('getStackTraceDisplayText', () => {
    it('prefers AI explanation before raw_trace when there are no frames', () => {
        expect((0, ErrorDetailModal_1.getStackTraceDisplayText)("'Run' object has no attribute 'add_comment'", { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" }, 'The request payload was malformed before the model could process it.', 'The root cause was a bad JSON payload.')).toBe('The request payload was malformed before the model could process it.');
        expect((0, ErrorDetailModal_1.getStackTraceDisplayText)('ValueError: invalid input', { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" }, null, 'The root cause was a bad JSON payload.')).toBe('The root cause was a bad JSON payload.');
        expect((0, ErrorDetailModal_1.getStackTraceDisplayText)('ValueError: invalid input', { frames: [], raw_trace: "'Run' object has no attribute 'add_comment'" }, null, null)).toBe("'Run' object has no attribute 'add_comment'");
    });
});
//# sourceMappingURL=ErrorDetailModal.test.js.map