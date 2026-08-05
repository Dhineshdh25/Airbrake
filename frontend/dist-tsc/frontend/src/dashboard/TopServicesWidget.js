"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TopServicesWidget = TopServicesWidget;
const jsx_runtime_1 = require("react/jsx-runtime");
function TopServicesWidget({ services }) {
    if (services.length === 0) {
        return (0, jsx_runtime_1.jsx)("p", { "data-testid": "services-empty", style: { opacity: 0.4, fontSize: 13 }, children: "No data available" });
    }
    const max = services[0]?.count ?? 1;
    return ((0, jsx_runtime_1.jsx)("ol", { "data-testid": "top-services-widget", style: { listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }, children: services.map((s) => ((0, jsx_runtime_1.jsxs)("li", { "data-testid": "service-row", children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 3 }, children: [(0, jsx_runtime_1.jsx)("span", { children: s.service }), (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 600 }, children: s.count })] }), (0, jsx_runtime_1.jsx)("div", { style: { height: 4, background: 'rgba(255,255,255,0.1)', borderRadius: 2 }, children: (0, jsx_runtime_1.jsx)("div", { style: { height: '100%', width: `${(s.count / max) * 100}%`, background: '#f87171', borderRadius: 2 } }) })] }, s.service))) }));
}
//# sourceMappingURL=TopServicesWidget.js.map