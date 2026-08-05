"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SeverityBreakdownWidget = SeverityBreakdownWidget;
const jsx_runtime_1 = require("react/jsx-runtime");
const COLORS = {
    critical: '#ef4444',
    error: '#f97316',
    warning: '#eab308',
    info: '#3b82f6',
};
function SeverityBreakdownWidget({ breakdown }) {
    if (breakdown.length === 0) {
        return (0, jsx_runtime_1.jsx)("p", { "data-testid": "severity-empty", style: { opacity: 0.4, fontSize: 13 }, children: "No data available" });
    }
    return ((0, jsx_runtime_1.jsx)("ul", { "data-testid": "severity-breakdown-widget", style: { listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }, children: breakdown.map((item) => ((0, jsx_runtime_1.jsxs)("li", { "data-testid": "severity-row", style: { display: 'flex', alignItems: 'center', gap: 10 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { width: 10, height: 10, borderRadius: '50%', background: COLORS[item.severity] ?? '#888', flexShrink: 0 } }), (0, jsx_runtime_1.jsx)("span", { style: { flex: 1, fontSize: 13, textTransform: 'capitalize' }, children: item.severity }), (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 600, fontSize: 13 }, children: item.count })] }, item.severity))) }));
}
//# sourceMappingURL=SeverityBreakdownWidget.js.map