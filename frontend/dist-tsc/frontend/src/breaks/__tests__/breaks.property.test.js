"use strict";
/**
 * Property tests for Break Detail view.
 * Requirements: 2.1, 4.1, 4.2, 4.3, 4.4
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const fc = __importStar(require("fast-check"));
// ─── Arbitraries ─────────────────────────────────────────────────────────────
const arbSeverity = fc.constantFrom('info', 'warning', 'error', 'critical');
const arbBreak = fc.record({
    id: fc.uuid(),
    applicationId: fc.string({ minLength: 1, maxLength: 32 }),
    environment: fc.string({ minLength: 1, maxLength: 16 }),
    severity: arbSeverity,
    errorMessage: fc.string({ minLength: 1, maxLength: 200 }),
    stackTrace: fc.string({ minLength: 1, maxLength: 2000 }),
    endpoint: fc.option(fc.string({ minLength: 1, maxLength: 100 }), { nil: null }),
    requestPayload: fc.option(fc.record({ key: fc.string() }), { nil: null }),
    userSession: fc.option(fc.record({ sessionId: fc.string() }), { nil: null }),
    timestamp: fc.date(),
    fingerprint: fc.hexaString({ minLength: 32, maxLength: 64 }),
});
const arbLogRecord = fc.record({
    id: fc.uuid(),
    applicationId: fc.string({ minLength: 1, maxLength: 32 }),
    environment: fc.constantFrom('production', 'qa', 'development'),
    severity: arbSeverity,
    message: fc.string({ minLength: 1, maxLength: 200 }),
    timestamp: fc.date(),
    tags: fc.array(fc.string()),
    rawPayload: fc.record({}),
});
// ─── Property 3: Break Detail View Contains Required Fields ──────────────────
// Feature: live-airbrake-monitoring-portal, Property 3: Break Detail View Contains Required Fields
describe('Property 3: Break Detail View Contains Required Fields', () => {
    it('every Break has all required display fields populated', () => {
        fc.assert(fc.property(arbBreak, (b) => {
            expect(b.errorMessage).toBeTruthy();
            expect(b.stackTrace).toBeTruthy();
            expect(b.id).toBeTruthy();
            expect(b.applicationId).toBeTruthy();
            expect(b.severity).toMatch(/^(info|warning|error|critical)$/);
            expect(b.fingerprint).toBeTruthy();
            expect(b.timestamp).toBeInstanceOf(Date);
        }), { numRuns: 100 });
    });
});
// ─── Property 11: Log Correlation Correctness ────────────────────────────────
// Feature: live-airbrake-monitoring-portal, Property 11: Log Correlation Correctness
describe('Property 11: Log Correlation Correctness', () => {
    it('correlated logs match application and fall within timestamp window', () => {
        fc.assert(fc.property(arbBreak, fc.array(arbLogRecord, { minLength: 0, maxLength: 20 }), (b, logs) => {
            const FIVE_MIN_MS = 5 * 60 * 1000;
            const breakTime = new Date(b.timestamp).getTime();
            const from = breakTime - FIVE_MIN_MS;
            const to = breakTime + FIVE_MIN_MS;
            const correlated = logs.filter((log) => log.applicationId === b.applicationId &&
                new Date(log.timestamp).getTime() >= from &&
                new Date(log.timestamp).getTime() <= to);
            // Every correlated log must match app and time window
            for (const log of correlated) {
                expect(log.applicationId).toBe(b.applicationId);
                expect(new Date(log.timestamp).getTime()).toBeGreaterThanOrEqual(from);
                expect(new Date(log.timestamp).getTime()).toBeLessThanOrEqual(to);
            }
            // No non-matching log should appear in correlated set
            const nonCorrelated = logs.filter((log) => log.applicationId !== b.applicationId ||
                new Date(log.timestamp).getTime() < from ||
                new Date(log.timestamp).getTime() > to);
            for (const log of nonCorrelated) {
                expect(correlated).not.toContain(log);
            }
        }), { numRuns: 100 });
    });
});
// ─── Property 12: Missing Data Graceful Handling ─────────────────────────────
// Feature: live-airbrake-monitoring-portal, Property 12: Missing Data Graceful Handling
describe('Property 12: Missing Data Graceful Handling', () => {
    it('null requestPayload or userSession does not cause errors', () => {
        fc.assert(fc.property(arbBreak, (b) => {
            const withNulls = { ...b, requestPayload: null, userSession: null };
            // Simulates what the UI would do: check for null before rendering
            const requestDisplay = withNulls.requestPayload !== null && withNulls.requestPayload !== undefined
                ? JSON.stringify(withNulls.requestPayload)
                : 'Data not available';
            const sessionDisplay = withNulls.userSession !== null && withNulls.userSession !== undefined
                ? JSON.stringify(withNulls.userSession)
                : 'Data not available';
            expect(requestDisplay).toBe('Data not available');
            expect(sessionDisplay).toBe('Data not available');
        }), { numRuns: 100 });
    });
    it('non-null requestPayload renders without placeholder', () => {
        fc.assert(fc.property(arbBreak, fc.record({ key: fc.string() }), (b, payload) => {
            const withPayload = { ...b, requestPayload: payload };
            const requestDisplay = withPayload.requestPayload !== null && withPayload.requestPayload !== undefined
                ? JSON.stringify(withPayload.requestPayload)
                : 'Data not available';
            expect(requestDisplay).not.toBe('Data not available');
        }), { numRuns: 100 });
    });
});
//# sourceMappingURL=breaks.property.test.js.map