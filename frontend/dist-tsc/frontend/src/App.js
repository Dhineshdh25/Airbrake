"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.default = App;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const ProtectedRoute_1 = require("./auth/ProtectedRoute");
const LoginPage_1 = require("./auth/LoginPage");
const ThemeContext_1 = require("./theme/ThemeContext");
const Layout_1 = require("./layout/Layout");
const Dashboard_1 = require("./dashboard/Dashboard");
const LogStream_1 = require("./logs/LogStream");
const BreaksList_1 = require("./breaks/BreaksList");
const ErrorDetail_1 = require("./breaks/ErrorDetail");
const JiraOverview_1 = require("./jira/JiraOverview");
const Settings_1 = require("./settings/Settings");
function getRole() {
    const stored = localStorage.getItem('session_role');
    if (stored === 'admin' || stored === 'developer' || stored === 'viewer')
        return stored;
    return 'viewer';
}
/**
 * Handles OAuth callback redirects from the backend.
 *
 * S3 static hosting can only serve index.html at the root path. The backend
 * callback redirects to the root URL with ?redirect=/settings&jira_connected=true
 * instead of directly to /settings (which S3 would 404).
 *
 * This component runs on every page load and immediately navigates to the
 * intended path, preserving the OAuth result query params for JiraSettings.tsx.
 */
function OAuthRedirectHandler() {
    const navigate = (0, react_router_dom_1.useNavigate)();
    (0, react_1.useEffect)(() => {
        const params = new URLSearchParams(window.location.search);
        const redirectTo = params.get('redirect');
        if (!redirectTo)
            return;
        // Build destination URL with OAuth params preserved, minus the redirect param
        params.delete('redirect');
        const qs = params.toString();
        const destination = redirectTo + (qs ? `?${qs}` : '');
        // Replace current history entry so back button doesn't loop
        navigate(destination, { replace: true });
    }, [navigate]);
    return null;
}
function AppShell() {
    const role = getRole();
    return ((0, jsx_runtime_1.jsxs)(Layout_1.Layout, { children: [(0, jsx_runtime_1.jsx)(OAuthRedirectHandler, {}), (0, jsx_runtime_1.jsxs)(react_router_dom_1.Routes, { children: [(0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/dashboard", element: (0, jsx_runtime_1.jsx)(Dashboard_1.Dashboard, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/logs", element: (0, jsx_runtime_1.jsx)(LogStream_1.LogStream, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/breaks", element: (0, jsx_runtime_1.jsx)(BreaksList_1.BreaksList, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/breaks/:errorHash", element: (0, jsx_runtime_1.jsx)(ErrorDetail_1.ErrorDetail, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/jira", element: (0, jsx_runtime_1.jsx)(JiraOverview_1.JiraOverview, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/settings", element: (0, jsx_runtime_1.jsx)(Settings_1.Settings, { role: role }) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/", element: (0, jsx_runtime_1.jsx)(react_router_dom_1.Navigate, { to: "/dashboard", replace: true }) })] })] }));
}
function App() {
    return ((0, jsx_runtime_1.jsx)(ThemeContext_1.ThemeProvider, { children: (0, jsx_runtime_1.jsx)(react_router_dom_1.BrowserRouter, { children: (0, jsx_runtime_1.jsxs)(react_router_dom_1.Routes, { children: [(0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/auth/login", element: (0, jsx_runtime_1.jsx)(LoginPage_1.LoginPage, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/*", element: (0, jsx_runtime_1.jsx)(ProtectedRoute_1.ProtectedRoute, { children: (0, jsx_runtime_1.jsx)(AppShell, {}) }) })] }) }) }));
}
//# sourceMappingURL=App.js.map