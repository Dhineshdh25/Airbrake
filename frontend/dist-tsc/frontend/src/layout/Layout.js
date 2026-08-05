"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Layout = Layout;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_router_dom_1 = require("react-router-dom");
const ThemeContext_1 = require("../theme/ThemeContext");
const NAV_LINKS = [
    { to: '/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/logs', label: 'Log Stream', icon: '≡' },
    { to: '/breaks', label: 'Breaks', icon: '⚡' },
    { to: '/settings', label: 'Settings', icon: '⚙' },
];
function Layout({ children }) {
    const { theme, setTheme } = (0, ThemeContext_1.useTheme)();
    const location = (0, react_router_dom_1.useLocation)();
    const isDark = theme === 'dark';
    return ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font)' }, children: [(0, jsx_runtime_1.jsxs)("nav", { style: {
                    width: 220,
                    background: 'var(--sidebar-bg)',
                    borderRight: '1px solid var(--sidebar-border)',
                    display: 'flex',
                    flexDirection: 'column',
                    flexShrink: 0,
                    position: 'sticky',
                    top: 0,
                    height: '100vh',
                }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                            padding: '20px 20px 18px',
                            borderBottom: '1px solid var(--sidebar-border)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 20 }, children: "\uD83D\uDD25" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: 0.3 }, children: "Airbrake" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 0.5, textTransform: 'uppercase' }, children: "Portal" })] })] }), (0, jsx_runtime_1.jsx)("div", { style: { flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }, children: NAV_LINKS.map(({ to, label, icon }) => {
                            const active = location.pathname === to || location.pathname.startsWith(to + '/');
                            return ((0, jsx_runtime_1.jsxs)(react_router_dom_1.Link, { to: to, style: {
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: '9px 12px',
                                    borderRadius: 'var(--radius-sm)',
                                    color: active ? '#fff' : 'rgba(255,255,255,0.5)',
                                    fontWeight: active ? 600 : 400,
                                    fontSize: 13.5,
                                    background: active ? 'var(--accent-glow)' : 'transparent',
                                    boxShadow: active ? 'inset 0 0 0 1px rgba(99,102,241,0.3)' : 'none',
                                    transition: 'all var(--transition)',
                                    textDecoration: 'none',
                                }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 14, opacity: active ? 1 : 0.6, width: 18, textAlign: 'center' }, children: icon }), label, active && ((0, jsx_runtime_1.jsx)("span", { style: {
                                            marginLeft: 'auto',
                                            width: 6,
                                            height: 6,
                                            borderRadius: '50%',
                                            background: 'var(--accent)',
                                            boxShadow: '0 0 6px var(--accent)',
                                        } }))] }, to));
                        }) }), (0, jsx_runtime_1.jsx)("div", { style: { padding: '14px 10px', borderTop: '1px solid var(--sidebar-border)' }, children: (0, jsx_runtime_1.jsxs)("button", { onClick: () => setTheme(isDark ? 'light' : 'dark'), style: {
                                width: '100%',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                padding: '8px 12px',
                                background: 'rgba(255,255,255,0.05)',
                                border: '1px solid rgba(255,255,255,0.08)',
                                borderRadius: 'var(--radius-sm)',
                                color: 'rgba(255,255,255,0.6)',
                                cursor: 'pointer',
                                fontSize: 12.5,
                                transition: 'all var(--transition)',
                            }, children: [(0, jsx_runtime_1.jsx)("span", { children: isDark ? '☀️' : '🌙' }), isDark ? 'Light mode' : 'Dark mode'] }) })] }), (0, jsx_runtime_1.jsx)("main", { style: { flex: 1, padding: '32px 36px', overflowY: 'auto', minWidth: 0 }, children: children })] }));
}
//# sourceMappingURL=Layout.js.map