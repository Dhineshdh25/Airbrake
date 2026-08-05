"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BreakCountWidget = BreakCountWidget;
const jsx_runtime_1 = require("react/jsx-runtime");
function BreakCountWidget({ data }) {
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "break-count-widget", style: { display: 'flex', gap: 24 }, children: [(0, jsx_runtime_1.jsxs)("div", { "data-testid": "break-count-24h", style: { textAlign: 'center' }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 36, fontWeight: 700, color: '#f87171' }, children: data.last24h }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, opacity: 0.6, marginTop: 4 }, children: "Last 24h" })] }), (0, jsx_runtime_1.jsxs)("div", { "data-testid": "break-count-7d", style: { textAlign: 'center' }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 36, fontWeight: 700, color: '#fb923c' }, children: data.last7d }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, opacity: 0.6, marginTop: 4 }, children: "Last 7 days" })] })] }));
}
//# sourceMappingURL=BreakCountWidget.js.map