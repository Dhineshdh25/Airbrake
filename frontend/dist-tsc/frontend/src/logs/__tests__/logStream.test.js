"use strict";
/**
 * Unit tests for log stream filter UI.
 * Requirements: 1.3, 1.4, 1.6
 */
Object.defineProperty(exports, "__esModule", { value: true });
require("@testing-library/jest-dom");
const react_1 = require("@testing-library/react");
const useLogFilters_1 = require("../useLogFilters");
function makeLog(overrides = {}) {
    return {
        id: 'log-1',
        applicationId: 'app-a',
        environment: 'production',
        severity: 'error',
        message: 'Something went wrong',
        timestamp: new Date('2026-03-17T10:00:00Z'),
        tags: [],
        rawPayload: {},
        ...overrides,
    };
}
describe('useLogFilters', () => {
    it('returns all logs when no filters set', () => {
        const logs = [makeLog(), makeLog({ id: 'log-2', applicationId: 'app-b' })];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        expect(result.current.filtered).toHaveLength(2);
    });
    it('filters by application', () => {
        const logs = [makeLog({ applicationId: 'app-a' }), makeLog({ id: 'log-2', applicationId: 'app-b' })];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => result.current.updateFilter('application', 'app-a'));
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].applicationId).toBe('app-a');
    });
    it('filters by environment', () => {
        const logs = [
            makeLog({ environment: 'production' }),
            makeLog({ id: 'log-2', environment: 'qa' }),
        ];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => result.current.updateFilter('environment', 'qa'));
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].environment).toBe('qa');
    });
    it('filters by severity', () => {
        const logs = [
            makeLog({ severity: 'error' }),
            makeLog({ id: 'log-2', severity: 'info' }),
        ];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => result.current.updateFilter('severity', 'info'));
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].severity).toBe('info');
    });
    it('filters by keyword (case-insensitive)', () => {
        const logs = [
            makeLog({ message: 'Database connection failed' }),
            makeLog({ id: 'log-2', message: 'Request timeout' }),
        ];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => result.current.updateFilter('keyword', 'database'));
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].message).toContain('Database');
    });
    it('filters by timestamp range', () => {
        const logs = [
            makeLog({ id: 'log-1', timestamp: new Date('2026-03-17T08:00:00Z') }),
            makeLog({ id: 'log-2', timestamp: new Date('2026-03-17T12:00:00Z') }),
            makeLog({ id: 'log-3', timestamp: new Date('2026-03-17T16:00:00Z') }),
        ];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => {
            result.current.updateFilter('from', '2026-03-17T09:00:00Z');
            result.current.updateFilter('to', '2026-03-17T14:00:00Z');
        });
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].id).toBe('log-2');
    });
    it('applies multiple filters simultaneously', () => {
        const logs = [
            makeLog({ applicationId: 'app-a', severity: 'error' }),
            makeLog({ id: 'log-2', applicationId: 'app-a', severity: 'info' }),
            makeLog({ id: 'log-3', applicationId: 'app-b', severity: 'error' }),
        ];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => {
            result.current.updateFilter('application', 'app-a');
            result.current.updateFilter('severity', 'error');
        });
        expect(result.current.filtered).toHaveLength(1);
        expect(result.current.filtered[0].id).toBe('log-1');
    });
    it('resets all filters', () => {
        const logs = [makeLog(), makeLog({ id: 'log-2', applicationId: 'app-b' })];
        const { result } = (0, react_1.renderHook)(() => (0, useLogFilters_1.useLogFilters)(logs));
        (0, react_1.act)(() => result.current.updateFilter('application', 'app-a'));
        expect(result.current.filtered).toHaveLength(1);
        (0, react_1.act)(() => result.current.resetFilters());
        expect(result.current.filtered).toHaveLength(2);
    });
});
//# sourceMappingURL=logStream.test.js.map