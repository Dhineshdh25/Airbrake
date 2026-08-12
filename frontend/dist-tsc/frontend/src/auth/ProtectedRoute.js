"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ProtectedRoute = ProtectedRoute;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_router_dom_1 = require("react-router-dom");
const AuthContext_1 = require("./AuthContext");
function ProtectedRoute({ children }) {
    const location = (0, react_router_dom_1.useLocation)();
    const { user, loading } = (0, AuthContext_1.useAuth)();
    // Show nothing while checking the session
    if (loading) {
        return ((0, jsx_runtime_1.jsx)("div", { style: {
                minHeight: '100vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--bg)',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font)',
                fontSize: 14,
            }, children: "Loading\u2026" }));
    }
    // Not authenticated — redirect to login
    if (!user) {
        const redirectUri = encodeURIComponent(location.pathname + location.search);
        return (0, jsx_runtime_1.jsx)(react_router_dom_1.Navigate, { to: `/auth/login?redirect_uri=${redirectUri}`, replace: true });
    }
    return (0, jsx_runtime_1.jsx)(jsx_runtime_1.Fragment, { children: children });
}
//# sourceMappingURL=ProtectedRoute.js.map