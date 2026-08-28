"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Layout = Layout;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const ThemeContext_1 = require("../theme/ThemeContext");
const AuthContext_1 = require("../auth/AuthContext");
const api_1 = require("../lib/api");
// Plain nav links rendered before the Jira connection-aware button.
// Order: Dashboard → Log Stream → Breaks → [Jira button] → Settings
const PLAIN_NAV_LINKS_BEFORE_JIRA = [
    { to: '/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/logs', label: 'Log Stream', icon: '≡' },
    { to: '/breaks', label: 'Breaks', icon: '⚡' },
];
const PLAIN_NAV_LINKS_AFTER_JIRA = [
    { to: '/settings', label: 'Settings', icon: '⚙' },
];
function Layout({ children }) {
    const { theme, setTheme } = (0, ThemeContext_1.useTheme)();
    const { user, logout } = (0, AuthContext_1.useAuth)();
    const navigate = (0, react_router_dom_1.useNavigate)();
    const location = (0, react_router_dom_1.useLocation)();
    const isDark = theme === 'dark';
    // Cache the last-known Jira connection status so repeated clicks don't
    // fire an extra network request. Invalidated after 60 s.
    const jiraStatusCache = (0, react_1.useRef)(null);
    const handleLogout = async () => {
        await logout();
        navigate('/auth/login', { replace: true });
    };
    /**
     * Jira nav click handler.
     *
     * 1. If the user has no Airbrake session yet → do nothing special; the
     *    ProtectedRoute will redirect to login. This path should never happen
     *    in practice because Layout is rendered inside ProtectedRoute.
     *
     * 2. If Jira IS connected → navigate to /jira normally.
     *
     * 3. If Jira is NOT connected → navigate to /settings and scroll to the
     *    Jira Integration section.  Do NOT start Google OAuth.
     *
     * We call /api/jira/status (already called by JiraSettings on mount, so
     * the Lambda response is usually cached at the CDN level and is fast).
     */
    const handleJiraClick = (0, react_1.useCallback)(async (e) => {
        e.preventDefault();
        // No user session — let the normal ProtectedRoute handle it
        if (!user) {
            navigate('/jira');
            return;
        }
        // Use cached result if fresh (< 60 s)
        const now = Date.now();
        if (jiraStatusCache.current && now - jiraStatusCache.current.ts < 60000) {
            if (jiraStatusCache.current.connected) {
                navigate('/jira');
            }
            else {
                navigate('/settings?jira_section=1', { replace: false });
            }
            return;
        }
        // Fetch fresh status
        try {
            const r = await (0, api_1.apiFetch)('/api/jira/status');
            const d = await r.json();
            jiraStatusCache.current = { connected: d.connected, ts: Date.now() };
            if (d.connected) {
                navigate('/jira');
            }
            else {
                // Redirect to Settings → Jira Integration section.
                // Do NOT navigate to /auth/login or start Google OAuth.
                navigate('/settings?jira_section=1', { replace: false });
            }
        }
        catch {
            // Network error — fall through to /jira which shows its own error state
            navigate('/jira');
        }
    }, [user, navigate]);
    // Shared nav item styles
    function navItemStyle(active) {
        return {
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
            cursor: 'pointer',
            border: 'none',
            width: '100%',
            textAlign: 'left',
        };
    }
    const jiraActive = location.pathname === '/jira' || location.pathname.startsWith('/jira/');
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
                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 20 }, children: "\uD83D\uDD25" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: 0.3 }, children: "Airbrake" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 0.5, textTransform: 'uppercase' }, children: "Portal" })] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }, children: [PLAIN_NAV_LINKS_BEFORE_JIRA.map(({ to, label, icon }) => {
                                const active = location.pathname === to || location.pathname.startsWith(to + '/');
                                return ((0, jsx_runtime_1.jsxs)(react_router_dom_1.Link, { to: to, style: navItemStyle(active), children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 14, opacity: active ? 1 : 0.6, width: 18, textAlign: 'center' }, children: icon }), label, active && ((0, jsx_runtime_1.jsx)("span", { style: {
                                                marginLeft: 'auto',
                                                width: 6,
                                                height: 6,
                                                borderRadius: '50%',
                                                background: 'var(--accent)',
                                                boxShadow: '0 0 6px var(--accent)',
                                            } }))] }, to));
                            }), (0, jsx_runtime_1.jsxs)("button", { onClick: handleJiraClick, style: navItemStyle(jiraActive), "aria-current": jiraActive ? 'page' : undefined, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 14, opacity: jiraActive ? 1 : 0.6, width: 18, textAlign: 'center' }, children: "\uD83D\uDD17" }), "Jira", jiraActive && ((0, jsx_runtime_1.jsx)("span", { style: {
                                            marginLeft: 'auto',
                                            width: 6,
                                            height: 6,
                                            borderRadius: '50%',
                                            background: 'var(--accent)',
                                            boxShadow: '0 0 6px var(--accent)',
                                        } }))] }), PLAIN_NAV_LINKS_AFTER_JIRA.map(({ to, label, icon }) => {
                                const active = location.pathname === to || location.pathname.startsWith(to + '/');
                                return ((0, jsx_runtime_1.jsxs)(react_router_dom_1.Link, { to: to, style: navItemStyle(active), children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 14, opacity: active ? 1 : 0.6, width: 18, textAlign: 'center' }, children: icon }), label, active && ((0, jsx_runtime_1.jsx)("span", { style: {
                                                marginLeft: 'auto',
                                                width: 6,
                                                height: 6,
                                                borderRadius: '50%',
                                                background: 'var(--accent)',
                                                boxShadow: '0 0 6px var(--accent)',
                                            } }))] }, to));
                            })] }), (0, jsx_runtime_1.jsxs)("div", { style: { padding: '14px 10px', borderTop: '1px solid var(--sidebar-border)' }, children: [user && ((0, jsx_runtime_1.jsx)("div", { style: {
                                    marginBottom: 8,
                                    padding: '6px 12px',
                                    fontSize: 11.5,
                                    color: 'rgba(255,255,255,0.5)',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                }, children: user.email })), (0, jsx_runtime_1.jsxs)("button", { onClick: handleLogout, style: {
                                    width: '100%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 8,
                                    padding: '8px 12px',
                                    marginBottom: 6,
                                    background: 'rgba(239,68,68,0.08)',
                                    border: '1px solid rgba(239,68,68,0.15)',
                                    borderRadius: 'var(--radius-sm)',
                                    color: 'rgba(255,255,255,0.6)',
                                    cursor: 'pointer',
                                    fontSize: 12.5,
                                    transition: 'all var(--transition)',
                                }, children: [(0, jsx_runtime_1.jsx)("span", { children: "\u21AA" }), "Sign out"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => setTheme(isDark ? 'light' : 'dark'), style: {
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
                                }, children: [(0, jsx_runtime_1.jsx)("span", { children: isDark ? '☀️' : '🌙' }), isDark ? 'Light mode' : 'Dark mode'] })] })] }), (0, jsx_runtime_1.jsx)("main", { style: { flex: 1, padding: '32px 36px', overflowY: 'auto', minWidth: 0 }, children: children })] }));
}
//# sourceMappingURL=Layout.js.map