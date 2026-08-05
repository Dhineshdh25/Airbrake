"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TimeSeriesWidget = TimeSeriesWidget;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
function TimeSeriesWidget({ timeSeries, deploymentEvents }) {
    const [granularity, setGranularity] = (0, react_1.useState)('hourly');
    const btnStyle = (active) => ({
        padding: '4px 12px', fontSize: 12, borderRadius: 4, border: 'none', cursor: 'pointer',
        background: active ? '#3b82f6' : 'rgba(255,255,255,0.1)',
        color: active ? '#fff' : 'inherit',
    });
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "time-series-widget", children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 8, marginBottom: 12 }, children: [(0, jsx_runtime_1.jsx)("button", { "data-testid": "granularity-hourly", style: btnStyle(granularity === 'hourly'), onClick: () => setGranularity('hourly'), "aria-pressed": granularity === 'hourly', children: "Hourly" }), (0, jsx_runtime_1.jsx)("button", { "data-testid": "granularity-daily", style: btnStyle(granularity === 'daily'), onClick: () => setGranularity('daily'), "aria-pressed": granularity === 'daily', children: "Daily" })] }), timeSeries.length === 0 ? ((0, jsx_runtime_1.jsx)("p", { style: { opacity: 0.4, fontSize: 13 }, children: "No time-series data available" })) : ((0, jsx_runtime_1.jsx)("div", { "data-testid": "time-series-points", style: { display: 'flex', flexDirection: 'column', gap: 4 }, children: timeSeries.map((point) => ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "ts-point", style: { display: 'flex', justifyContent: 'space-between', fontSize: 13 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { opacity: 0.6 }, children: point.timestamp }), (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 600 }, children: point.count })] }, point.timestamp))) })), deploymentEvents.length > 0 && ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "deployment-overlays", style: { marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 10 }, children: [(0, jsx_runtime_1.jsx)("p", { style: { fontSize: 11, opacity: 0.5, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1 }, children: "Deployments" }), deploymentEvents.map((ev) => ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "deployment-event", style: { fontSize: 12, opacity: 0.7 }, children: ["\uD83D\uDE80 ", ev.version, " \u2014 ", ev.service, " @ ", new Date(ev.timestamp).toLocaleString()] }, `${ev.timestamp}-${ev.version}`)))] }))] }));
}
//# sourceMappingURL=TimeSeriesWidget.js.map