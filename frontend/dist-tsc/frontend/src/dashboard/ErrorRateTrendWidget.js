"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ErrorRateTrendWidget = ErrorRateTrendWidget;
const jsx_runtime_1 = require("react/jsx-runtime");
function ErrorRateTrendWidget({ trend }) {
    if (trend.length === 0) {
        return (0, jsx_runtime_1.jsx)("p", { "data-testid": "trend-empty", style: { opacity: 0.4, fontSize: 13 }, children: "No data available" });
    }
    return ((0, jsx_runtime_1.jsx)("ul", { "data-testid": "error-rate-trend-widget", style: { listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }, children: trend.map((point) => ((0, jsx_runtime_1.jsxs)("li", { "data-testid": "trend-point", style: { display: 'flex', justifyContent: 'space-between', fontSize: 13 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { opacity: 0.6 }, children: new Date(point.timestamp).toLocaleTimeString() }), (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 600 }, children: point.count })] }, point.timestamp))) }));
}
//# sourceMappingURL=ErrorRateTrendWidget.js.map