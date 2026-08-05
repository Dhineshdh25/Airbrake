"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * Unit tests for Break Detail view.
 * Requirements: 4.1, 4.4
 */
require("@testing-library/jest-dom");
const react_1 = require("@testing-library/react");
const BreakDetail_1 = require("../BreakDetail");
const mockBreak = {
    id: 'break-1',
    applicationId: 'app-a',
    environment: 'production',
    severity: 'error',
    errorMessage: 'NullPointerException in UserService',
    stackTrace: 'at UserService.getUser (UserService.ts:42)',
    endpoint: '/api/users/123',
    requestPayload: { userId: '123' },
    userSession: { sessionId: 'sess-abc' },
    timestamp: '2026-03-17T10:00:00Z',
    fingerprint: 'abc123',
    status: 'new',
    firstOccurrence: '2026-03-17T09:00:00Z',
    lastOccurrence: '2026-03-17T10:00:00Z',
    occurrenceCount: 5,
    correlatedLogs: [
        {
            id: 'log-1',
            applicationId: 'app-a',
            environment: 'production',
            severity: 'error',
            message: 'User lookup failed',
            timestamp: '2026-03-17T10:00:01Z',
            tags: [],
            rawPayload: {},
        },
    ],
};
beforeEach(() => {
    global.fetch = jest.fn();
});
afterEach(() => {
    jest.resetAllMocks();
});
describe('BreakDetail', () => {
    it('renders all required fields for a known break', async () => {
        global.fetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => mockBreak,
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakDetail_1.BreakDetail, { breakId: "break-1" }));
        await (0, react_1.waitFor)(() => expect(react_1.screen.getByTestId('break-detail')).toBeInTheDocument());
        expect(react_1.screen.getByTestId('break-error-message')).toHaveTextContent('NullPointerException');
        expect(react_1.screen.getByTestId('break-stack-trace')).toHaveTextContent('UserService.ts:42');
        expect(react_1.screen.getByTestId('break-endpoint')).toHaveTextContent('/api/users/123');
        expect(react_1.screen.getByTestId('first-occurrence')).toBeInTheDocument();
        expect(react_1.screen.getByTestId('last-occurrence')).toBeInTheDocument();
        expect(react_1.screen.getByTestId('occurrence-count')).toHaveTextContent('5');
        expect(react_1.screen.getByTestId('break-status')).toHaveTextContent('new');
    });
    it('shows correlated log entries', async () => {
        global.fetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => mockBreak,
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakDetail_1.BreakDetail, { breakId: "break-1" }));
        await (0, react_1.waitFor)(() => expect(react_1.screen.getByTestId('correlated-logs')).toBeInTheDocument());
        expect(react_1.screen.getAllByTestId('correlated-log-entry')).toHaveLength(1);
    });
    it('shows "Data not available" placeholder for null requestPayload', async () => {
        const breakWithNulls = { ...mockBreak, requestPayload: null, userSession: null };
        global.fetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => breakWithNulls,
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakDetail_1.BreakDetail, { breakId: "break-1" }));
        await (0, react_1.waitFor)(() => expect(react_1.screen.getByTestId('break-detail')).toBeInTheDocument());
        expect(react_1.screen.getByTestId('request-payload-unavailable')).toHaveTextContent('Data not available');
        expect(react_1.screen.getByTestId('user-session-unavailable')).toHaveTextContent('Data not available');
    });
    it('shows not found message for 404', async () => {
        global.fetch.mockResolvedValueOnce({
            ok: false,
            status: 404,
            statusText: 'Not Found',
            json: async () => ({}),
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakDetail_1.BreakDetail, { breakId: "nonexistent" }));
        await (0, react_1.waitFor)(() => expect(react_1.screen.getByTestId('break-not-found')).toBeInTheDocument());
    });
});
//# sourceMappingURL=breakDetail.test.js.map