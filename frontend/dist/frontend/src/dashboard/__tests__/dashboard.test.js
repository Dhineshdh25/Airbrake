"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * Unit tests for dashboard widget rendering.
 * Requirements: 3.1, 3.2, 3.3
 */
require("@testing-library/jest-dom");
const react_1 = require("@testing-library/react");
const BreakCountWidget_1 = require("../BreakCountWidget");
const ErrorRateTrendWidget_1 = require("../ErrorRateTrendWidget");
const SeverityBreakdownWidget_1 = require("../SeverityBreakdownWidget");
const TimeSeriesWidget_1 = require("../TimeSeriesWidget");
const TopServicesWidget_1 = require("../TopServicesWidget");
const Dashboard_1 = require("../Dashboard");
describe('BreakCountWidget', () => {
    it('renders 24h and 7d counts', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakCountWidget_1.BreakCountWidget, { data: { last24h: 42, last7d: 300 } }));
        expect(react_1.screen.getByTestId('break-count-24h')).toHaveTextContent('42');
        expect(react_1.screen.getByTestId('break-count-7d')).toHaveTextContent('300');
    });
    it('renders zero counts', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(BreakCountWidget_1.BreakCountWidget, { data: { last24h: 0, last7d: 0 } }));
        expect(react_1.screen.getByTestId('break-count-24h')).toHaveTextContent('0');
        expect(react_1.screen.getByTestId('break-count-7d')).toHaveTextContent('0');
    });
});
describe('ErrorRateTrendWidget', () => {
    it('renders trend points', () => {
        const trend = [
            { timestamp: '2026-03-17T00:00:00Z', count: 5 },
            { timestamp: '2026-03-17T01:00:00Z', count: 10 },
        ];
        (0, react_1.render)((0, jsx_runtime_1.jsx)(ErrorRateTrendWidget_1.ErrorRateTrendWidget, { trend: trend }));
        expect(react_1.screen.getAllByTestId('trend-point')).toHaveLength(2);
    });
    it('shows empty state when no data', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(ErrorRateTrendWidget_1.ErrorRateTrendWidget, { trend: [] }));
        expect(react_1.screen.getByTestId('trend-empty')).toBeInTheDocument();
    });
});
describe('TopServicesWidget', () => {
    it('renders services in order', () => {
        const services = [
            { service: 'api', count: 100 },
            { service: 'worker', count: 50 },
        ];
        (0, react_1.render)((0, jsx_runtime_1.jsx)(TopServicesWidget_1.TopServicesWidget, { services: services }));
        const rows = react_1.screen.getAllByTestId('service-row');
        expect(rows[0]).toHaveTextContent('api');
        expect(rows[1]).toHaveTextContent('worker');
    });
    it('shows empty state when no services', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(TopServicesWidget_1.TopServicesWidget, { services: [] }));
        expect(react_1.screen.getByTestId('services-empty')).toBeInTheDocument();
    });
});
describe('TimeSeriesWidget', () => {
    it('renders time series points', () => {
        const ts = [{ timestamp: '2026-03-17T00:00:00Z', count: 3 }];
        (0, react_1.render)((0, jsx_runtime_1.jsx)(TimeSeriesWidget_1.TimeSeriesWidget, { timeSeries: ts, deploymentEvents: [] }));
        expect(react_1.screen.getAllByTestId('ts-point')).toHaveLength(1);
    });
    it('renders deployment overlays when present', () => {
        const events = [{ timestamp: '2026-03-17T12:00:00Z', version: 'v1.2.3', service: 'api' }];
        (0, react_1.render)((0, jsx_runtime_1.jsx)(TimeSeriesWidget_1.TimeSeriesWidget, { timeSeries: [], deploymentEvents: events }));
        expect(react_1.screen.getByTestId('deployment-overlays')).toBeInTheDocument();
        expect(react_1.screen.getByTestId('deployment-event')).toHaveTextContent('v1.2.3');
    });
    it('does not render deployment section when empty', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(TimeSeriesWidget_1.TimeSeriesWidget, { timeSeries: [], deploymentEvents: [] }));
        expect(react_1.screen.queryByTestId('deployment-overlays')).not.toBeInTheDocument();
    });
});
describe('SeverityBreakdownWidget', () => {
    it('renders severity rows', () => {
        const breakdown = [
            { severity: 'critical', count: 5 },
            { severity: 'error', count: 20 },
        ];
        (0, react_1.render)((0, jsx_runtime_1.jsx)(SeverityBreakdownWidget_1.SeverityBreakdownWidget, { breakdown: breakdown }));
        expect(react_1.screen.getAllByTestId('severity-row')).toHaveLength(2);
    });
    it('shows empty state when no data', () => {
        (0, react_1.render)((0, jsx_runtime_1.jsx)(SeverityBreakdownWidget_1.SeverityBreakdownWidget, { breakdown: [] }));
        expect(react_1.screen.getByTestId('severity-empty')).toBeInTheDocument();
    });
});
describe('summarizeSemanticGroupsForToday', () => {
    it('prefers semantic group names and falls back for JSON-format errors', () => {
        const rows = [
            { error: 'LLM output was not valid JSON', error_group_name: 'JSON format error' },
            { error: 'LLM output was not valid JSON' },
            { error: 'File not found: uploads/missing.txt' },
        ];
        expect((0, Dashboard_1.normalizeSemanticGroupName)(rows[1])).toBe('JSON format error');
        expect((0, Dashboard_1.summarizeSemanticGroupsForToday)(rows)).toEqual([
            { name: 'JSON format error', value: 2 },
            { name: 'File not found', value: 1 },
        ]);
    });
    it('keeps the semantic group id when present', () => {
        const rows = [
            { project: 'fm_structuring', error: 'Syntax & Parsing error', error_group_name: 'Syntax & Parsing', error_group_id: 'group-123' },
            { project: 'fm_structuring', error: 'Syntax & Parsing error', error_group_name: 'Syntax & Parsing', error_group_id: 'group-123' },
        ];
        expect((0, Dashboard_1.summarizeSemanticGroupsForToday)(rows, 'fm_structuring')).toEqual([
            { id: 'group-123', name: 'Syntax & Parsing', value: 2 },
        ]);
    });
    it('filters the summary to the selected project', () => {
        const rows = [
            { project: 'Alpha', error: 'LLM output was not valid JSON' },
            { project: 'Alpha', error: 'File not found: uploads/missing.txt' },
            { project: 'Beta', error: 'LLM output was not valid JSON' },
        ];
        expect((0, Dashboard_1.summarizeSemanticGroupsForToday)(rows, 'Alpha')).toEqual([
            { name: 'File not found', value: 1 },
            { name: 'JSON format error', value: 1 },
        ]);
    });
});
//# sourceMappingURL=dashboard.test.js.map