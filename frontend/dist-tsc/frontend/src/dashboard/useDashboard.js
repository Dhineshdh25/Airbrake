"use strict";
/**
 * Dashboard data hook — fetches all dashboard aggregation data from the REST API.
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.useDashboard = useDashboard;
const react_1 = require("react");
const api_1 = require("../lib/api");
const EMPTY = {
    breakCounts: { last24h: 0, last7d: 0 },
    errorRateTrend: [],
    topServices: [],
    timeSeries: [],
    severityBreakdown: [],
    deploymentEvents: [],
    airbrakeUnreachable: false,
};
function useDashboard(apiBase = '/api') {
    const [data, setData] = (0, react_1.useState)(EMPTY);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [error, setError] = (0, react_1.useState)(null);
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        async function fetchAll() {
            setLoading(true);
            setError(null);
            try {
                const res = await (0, api_1.apiFetch)(`${apiBase}/dashboard`);
                const json = await res.json();
                if (!cancelled)
                    setData(json);
            }
            catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : 'Unknown error');
                    setData((prev) => ({ ...prev, airbrakeUnreachable: true }));
                }
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        }
        void fetchAll();
        return () => { cancelled = true; };
    }, [apiBase]);
    return { data, loading, error };
}
//# sourceMappingURL=useDashboard.js.map