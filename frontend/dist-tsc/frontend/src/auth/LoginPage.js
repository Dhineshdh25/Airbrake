"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LoginPage = LoginPage;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const uuid_1 = require("../lib/uuid");
const ROLES = ['admin', 'developer', 'viewer'];
function LoginPage() {
    const [role, setRole] = (0, react_1.useState)('admin');
    const navigate = (0, react_router_dom_1.useNavigate)();
    const [params] = (0, react_router_dom_1.useSearchParams)();
    const handleLogin = () => {
        // Session token identifies the role for this session.
        // Kept as a fixed pattern so the backend can resolve it.
        const token = `dev-token-${role}`;
        localStorage.setItem('session_token', token);
        localStorage.setItem('session_role', role);
        // device_id is a stable, permanent identity for this browser profile.
        // It is generated once and never rotated — survives logout/login cycles.
        // This is what the backend uses as the Jira token store key, so the
        // user only needs to connect Jira once regardless of how many times
        // they log out and back in.
        if (!localStorage.getItem('device_id')) {
            localStorage.setItem('device_id', (0, uuid_1.getSafeUUID)().replace(/-/g, '').slice(0, 16));
        }
        const redirect = params.get('redirect_uri') ?? '/dashboard';
        navigate(decodeURIComponent(redirect), { replace: true });
    };
    return ((0, jsx_runtime_1.jsx)("div", { style: {
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--bg)',
            fontFamily: 'var(--font)',
        }, children: (0, jsx_runtime_1.jsxs)("div", { style: {
                width: 360,
                background: 'var(--surface)',
                border: '1px solid var(--card-border)',
                borderRadius: 'var(--radius-lg)',
                padding: '36px 32px',
                boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
            }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', marginBottom: 28 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 36, marginBottom: 10 }, children: "\uD83D\uDD25" }), (0, jsx_runtime_1.jsx)("h1", { style: { fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }, children: "Airbrake Portal" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Dev login \u2014 pick a role to continue" })] }), (0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 16 }, children: [(0, jsx_runtime_1.jsx)("label", { htmlFor: "role-select", style: { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }, children: "Role" }), (0, jsx_runtime_1.jsx)("select", { id: "role-select", value: role, onChange: (e) => setRole(e.target.value), style: {
                                width: '100%',
                                padding: '10px 12px',
                                background: 'var(--input-bg)',
                                border: '1px solid var(--input-border)',
                                borderRadius: 'var(--radius-sm)',
                                color: 'var(--text)',
                                fontSize: 14,
                                outline: 'none',
                                cursor: 'pointer',
                            }, children: ROLES.map((r) => ((0, jsx_runtime_1.jsx)("option", { value: r, children: r.charAt(0).toUpperCase() + r.slice(1) }, r))) })] }), (0, jsx_runtime_1.jsx)("button", { onClick: handleLogin, style: {
                        width: '100%',
                        padding: '11px',
                        background: 'var(--accent)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'background var(--transition)',
                    }, children: "Sign in" })] }) }));
}
//# sourceMappingURL=LoginPage.js.map