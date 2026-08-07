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
 * With HashRouter all routes are under the hash (e.g. /#/settings) so S3
 * always serves index.html for the root path and the hash never reaches S3.
 *
 * The backend redirects to:
 *   https://airbrake.s3-website.../  ?jira_connected=true
 *
 * The SPA loads at root, this handler reads the query params, then
 * navigates to /#/settings?jira_connected=true via React Router.
 */
function OAuthRedirectHandler() {
    const navigate = (0, react_router_dom_1.useNavigate)();
    (0, react_1.useEffect)(() => {
        // Read params from the real URL query string (before the hash)
        const params = new URLSearchParams(window.location.search);
        const jiraConnected = params.get('jira_connected');
        const jiraError = params.get('jira_error');
        if (!jiraConnected && !jiraError)
            return;
        // Clean the real URL (remove query params — they're now handled by React)
        window.history.replaceState({}, '', window.location.pathname);
        // Navigate to settings within the SPA, preserving the OAuth result param
        if (jiraConnected) {
            navigate('/settings?jira_connected=true', { replace: true });
        }
        else if (jiraError) {
            navigate(`/settings?jira_error=${jiraError}`, { replace: true });
        }
    }, [navigate]);
    return null;
}
function AppShell() {
    const role = getRole();
    return ((0, jsx_runtime_1.jsxs)(Layout_1.Layout, { children: [(0, jsx_runtime_1.jsx)(OAuthRedirectHandler, {}), (0, jsx_runtime_1.jsxs)(react_router_dom_1.Routes, { children: [(0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/dashboard", element: (0, jsx_runtime_1.jsx)(Dashboard_1.Dashboard, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/logs", element: (0, jsx_runtime_1.jsx)(LogStream_1.LogStream, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/breaks", element: (0, jsx_runtime_1.jsx)(BreaksList_1.BreaksList, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/breaks/:errorHash", element: (0, jsx_runtime_1.jsx)(ErrorDetail_1.ErrorDetail, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/jira", element: (0, jsx_runtime_1.jsx)(JiraOverview_1.JiraOverview, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/settings", element: (0, jsx_runtime_1.jsx)(Settings_1.Settings, { role: role }) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/", element: (0, jsx_runtime_1.jsx)(react_router_dom_1.Navigate, { to: "/dashboard", replace: true }) })] })] }));
}
function App() {
    return ((0, jsx_runtime_1.jsx)(ThemeContext_1.ThemeProvider, { children: (0, jsx_runtime_1.jsx)(react_router_dom_1.HashRouter, { children: (0, jsx_runtime_1.jsxs)(react_router_dom_1.Routes, { children: [(0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/auth/login", element: (0, jsx_runtime_1.jsx)(LoginPage_1.LoginPage, {}) }), (0, jsx_runtime_1.jsx)(react_router_dom_1.Route, { path: "/*", element: (0, jsx_runtime_1.jsx)(ProtectedRoute_1.ProtectedRoute, { children: (0, jsx_runtime_1.jsx)(AppShell, {}) }) })] }) }) }));
}
//# sourceMappingURL=App.js.map