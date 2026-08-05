"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ProtectedRoute = ProtectedRoute;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_router_dom_1 = require("react-router-dom");
const SESSION_TOKEN_KEY = 'session_token';
function ProtectedRoute({ children }) {
    const location = (0, react_router_dom_1.useLocation)();
    const token = localStorage.getItem(SESSION_TOKEN_KEY);
    if (!token) {
        const redirectUri = encodeURIComponent(location.pathname + location.search);
        return (0, jsx_runtime_1.jsx)(react_router_dom_1.Navigate, { to: `/auth/login?redirect_uri=${redirectUri}`, replace: true });
    }
    // Ensure every authenticated browser session has a stable device_id.
    // This runs on every page load so already-logged-in users get one
    // immediately without needing to log out and back in.
    if (!localStorage.getItem('device_id')) {
        localStorage.setItem('device_id', crypto.randomUUID().replace(/-/g, '').slice(0, 16));
    }
    return (0, jsx_runtime_1.jsx)(jsx_runtime_1.Fragment, { children: children });
}
//# sourceMappingURL=ProtectedRoute.js.map