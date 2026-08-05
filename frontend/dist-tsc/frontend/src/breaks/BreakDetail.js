"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BreakDetail = BreakDetail;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * Break Detail view — full context including stack trace, request data, correlated logs.
 * Requirements: 4.1, 4.2, 4.3, 4.4
 */
const react_1 = require("react");
const api_1 = require("../lib/api");
function BreakDetail({ breakId }) {
    const [data, setData] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [notFound, setNotFound] = (0, react_1.useState)(false);
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        setLoading(true);
        (0, api_1.apiFetch)(`/api/breaks/${breakId}`)
            .then((r) => r.json())
            .then((d) => {
            if (!cancelled && d) {
                setData(d);
                setLoading(false);
            }
            else if (!cancelled)
                setLoading(false);
        })
            .catch((err) => {
            if (!cancelled) {
                // 404 from ApiError means the break doesn't exist
                if (err && typeof err === 'object' && 'status' in err && err.status === 404) {
                    setNotFound(true);
                }
                setLoading(false);
            }
        });
        return () => { cancelled = true; };
    }, [breakId]);
    if (loading)
        return (0, jsx_runtime_1.jsx)("div", { "data-testid": "break-detail-loading", children: "Loading\u2026" });
    if (notFound || !data)
        return (0, jsx_runtime_1.jsx)("div", { "data-testid": "break-not-found", children: "Break not found." });
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "break-detail", children: [(0, jsx_runtime_1.jsx)("h1", { "data-testid": "break-error-message", children: data.errorMessage }), (0, jsx_runtime_1.jsx)("pre", { "data-testid": "break-stack-trace", children: data.stackTrace }), (0, jsx_runtime_1.jsx)("div", { "data-testid": "break-endpoint", children: data.endpoint ?? (0, jsx_runtime_1.jsx)("em", { "data-testid": "endpoint-unavailable", children: "Data not available" }) }), (0, jsx_runtime_1.jsxs)("div", { "data-testid": "break-lifecycle", children: [(0, jsx_runtime_1.jsx)("span", { "data-testid": "first-occurrence", children: data.firstOccurrence }), (0, jsx_runtime_1.jsx)("span", { "data-testid": "last-occurrence", children: data.lastOccurrence }), (0, jsx_runtime_1.jsx)("span", { "data-testid": "occurrence-count", children: data.occurrenceCount }), (0, jsx_runtime_1.jsx)("span", { "data-testid": "break-status", children: data.status })] }), (0, jsx_runtime_1.jsx)("div", { "data-testid": "break-request-payload", children: data.requestPayload !== null && data.requestPayload !== undefined ? ((0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(data.requestPayload, null, 2) })) : ((0, jsx_runtime_1.jsx)("em", { "data-testid": "request-payload-unavailable", children: "Data not available" })) }), (0, jsx_runtime_1.jsx)("div", { "data-testid": "break-user-session", children: data.userSession !== null && data.userSession !== undefined ? ((0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(data.userSession, null, 2) })) : ((0, jsx_runtime_1.jsx)("em", { "data-testid": "user-session-unavailable", children: "Data not available" })) }), (0, jsx_runtime_1.jsx)("div", { "data-testid": "correlated-logs", children: data.correlatedLogs.length === 0 ? ((0, jsx_runtime_1.jsx)("span", { "data-testid": "no-correlated-logs", children: "No correlated logs" })) : ((0, jsx_runtime_1.jsx)("ul", { children: data.correlatedLogs.map((log) => ((0, jsx_runtime_1.jsxs)("li", { "data-testid": "correlated-log-entry", children: ["[", log.severity, "] ", log.message] }, log.id))) })) })] }));
}
//# sourceMappingURL=BreakDetail.js.map