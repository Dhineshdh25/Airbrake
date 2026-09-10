"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LoginPage = LoginPage;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const AuthContext_1 = require("./AuthContext");
function LoginPage() {
    const [params] = (0, react_router_dom_1.useSearchParams)();
    const navigate = (0, react_router_dom_1.useNavigate)();
    const { login, initializationError } = (0, AuthContext_1.useAuth)();
    const [username, setUsername] = (0, react_1.useState)('');
    const [password, setPassword] = (0, react_1.useState)('');
    const [showPassword, setShowPassword] = (0, react_1.useState)(false);
    const [rememberMe, setRememberMe] = (0, react_1.useState)(false);
    const [submitting, setSubmitting] = (0, react_1.useState)(false);
    const [loginError, setLoginError] = (0, react_1.useState)(null);
    // auth_error query param covers server-side redirects (e.g. jira errors)
    const authError = params.get('auth_error');
    const AUTH_ERROR_MESSAGES = {
        authentication_failed: 'Authentication failed. Please try again.',
        session_expired: 'Your session has expired. Please sign in again.',
    };
    const paramErrorMessage = authError
        ? AUTH_ERROR_MESSAGES[authError] ?? 'Authentication failed. Please try again.'
        : null;
    const displayError = loginError ?? paramErrorMessage ?? initializationError;
    const handleSubmit = async (e) => {
        e.preventDefault();
        if (submitting)
            return;
        setLoginError(null);
        setSubmitting(true);
        try {
            const redirectUri = params.get('redirect_uri') ?? '/dashboard';
            const ok = await login(username, password);
            if (ok) {
                navigate(redirectUri, { replace: true });
            }
            else {
                setLoginError('Invalid username or password.');
            }
        }
        catch {
            setLoginError('Unable to connect. Please try again.');
        }
        finally {
            setSubmitting(false);
        }
    };
    return ((0, jsx_runtime_1.jsxs)("div", { style: {
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#0a0f1e',
            fontFamily: 'var(--font, system-ui, sans-serif)',
            position: 'relative',
            overflow: 'hidden',
        }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                    position: 'absolute',
                    inset: 0,
                    backgroundImage: 'radial-gradient(circle, rgba(99,102,241,0.15) 1px, transparent 1px)',
                    backgroundSize: '28px 28px',
                    pointerEvents: 'none',
                } }), (0, jsx_runtime_1.jsxs)("div", { style: {
                    position: 'relative',
                    width: 420,
                    maxWidth: 'calc(100vw - 32px)',
                    background: 'rgba(15,23,42,0.95)',
                    border: '1px solid rgba(99,102,241,0.25)',
                    borderRadius: 16,
                    padding: '44px 40px 40px',
                    boxShadow: '0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(99,102,241,0.1)',
                    backdropFilter: 'blur(12px)',
                }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', marginBottom: 32 }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    width: 52,
                                    height: 52,
                                    borderRadius: 14,
                                    background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                                    marginBottom: 16,
                                    boxShadow: '0 8px 24px rgba(99,102,241,0.4)',
                                }, children: (0, jsx_runtime_1.jsx)("svg", { width: "26", height: "26", viewBox: "0 0 24 24", fill: "none", children: (0, jsx_runtime_1.jsx)("path", { d: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5", stroke: "#fff", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }) }) }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, fontWeight: 600, letterSpacing: '0.1em',
                                    color: '#6366f1', textTransform: 'uppercase', marginBottom: 8 }, children: "MPS Labs" }), (0, jsx_runtime_1.jsx)("h1", { style: {
                                    fontSize: 22,
                                    fontWeight: 700,
                                    color: '#f1f5f9',
                                    margin: 0,
                                    marginBottom: 8,
                                    letterSpacing: '-0.3px',
                                }, children: "Airbrake Dashboard" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 14, color: '#94a3b8', margin: 0 }, children: "Sign in to your account" })] }), displayError && ((0, jsx_runtime_1.jsx)("div", { role: "alert", style: {
                            marginBottom: 20,
                            padding: '10px 14px',
                            background: 'rgba(239,68,68,0.12)',
                            border: '1px solid rgba(239,68,68,0.35)',
                            borderRadius: 8,
                            fontSize: 13,
                            color: '#fca5a5',
                            lineHeight: 1.5,
                        }, children: displayError })), (0, jsx_runtime_1.jsxs)("form", { onSubmit: handleSubmit, noValidate: true, children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 18 }, children: [(0, jsx_runtime_1.jsx)("label", { htmlFor: "login-username", style: {
                                            display: 'block',
                                            fontSize: 13,
                                            fontWeight: 500,
                                            color: '#cbd5e1',
                                            marginBottom: 7,
                                        }, children: "Username" }), (0, jsx_runtime_1.jsx)("input", { id: "login-username", type: "text", autoComplete: "username", autoCapitalize: "none", autoCorrect: "off", spellCheck: false, placeholder: "Enter your username", value: username, onChange: e => setUsername(e.target.value), disabled: submitting, required: true, style: {
                                            width: '100%',
                                            padding: '11px 14px',
                                            background: 'rgba(30,41,59,0.8)',
                                            border: '1px solid rgba(99,102,241,0.3)',
                                            borderRadius: 8,
                                            fontSize: 14,
                                            color: '#f1f5f9',
                                            outline: 'none',
                                            boxSizing: 'border-box',
                                            transition: 'border-color 0.2s',
                                        }, onFocus: e => { e.target.style.borderColor = 'rgba(99,102,241,0.7)'; }, onBlur: e => { e.target.style.borderColor = 'rgba(99,102,241,0.3)'; } })] }), (0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 20 }, children: [(0, jsx_runtime_1.jsx)("label", { htmlFor: "login-password", style: {
                                            display: 'block',
                                            fontSize: 13,
                                            fontWeight: 500,
                                            color: '#cbd5e1',
                                            marginBottom: 7,
                                        }, children: "Password" }), (0, jsx_runtime_1.jsxs)("div", { style: { position: 'relative' }, children: [(0, jsx_runtime_1.jsx)("input", { id: "login-password", type: showPassword ? 'text' : 'password', autoComplete: "current-password", placeholder: "Enter your password", value: password, onChange: e => setPassword(e.target.value), disabled: submitting, required: true, style: {
                                                    width: '100%',
                                                    padding: '11px 44px 11px 14px',
                                                    background: 'rgba(30,41,59,0.8)',
                                                    border: '1px solid rgba(99,102,241,0.3)',
                                                    borderRadius: 8,
                                                    fontSize: 14,
                                                    color: '#f1f5f9',
                                                    outline: 'none',
                                                    boxSizing: 'border-box',
                                                    transition: 'border-color 0.2s',
                                                }, onFocus: e => { e.target.style.borderColor = 'rgba(99,102,241,0.7)'; }, onBlur: e => { e.target.style.borderColor = 'rgba(99,102,241,0.3)'; } }), (0, jsx_runtime_1.jsx)("button", { type: "button", "aria-label": showPassword ? 'Hide password' : 'Show password', onClick: () => setShowPassword(v => !v), style: {
                                                    position: 'absolute',
                                                    right: 12,
                                                    top: '50%',
                                                    transform: 'translateY(-50%)',
                                                    background: 'none',
                                                    border: 'none',
                                                    padding: 4,
                                                    cursor: 'pointer',
                                                    color: '#64748b',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                }, children: showPassword ? (
                                                /* Eye-off */
                                                (0, jsx_runtime_1.jsxs)("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [(0, jsx_runtime_1.jsx)("path", { d: "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" }), (0, jsx_runtime_1.jsx)("path", { d: "M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" }), (0, jsx_runtime_1.jsx)("line", { x1: "1", y1: "1", x2: "23", y2: "23" })] })) : (
                                                /* Eye */
                                                (0, jsx_runtime_1.jsxs)("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [(0, jsx_runtime_1.jsx)("path", { d: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" }), (0, jsx_runtime_1.jsx)("circle", { cx: "12", cy: "12", r: "3" })] })) })] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }, children: [(0, jsx_runtime_1.jsx)("input", { id: "remember-me", type: "checkbox", checked: rememberMe, onChange: e => setRememberMe(e.target.checked), style: { width: 15, height: 15, accentColor: '#6366f1', cursor: 'pointer' } }), (0, jsx_runtime_1.jsx)("label", { htmlFor: "remember-me", style: {
                                            fontSize: 13,
                                            color: '#94a3b8',
                                            cursor: 'pointer',
                                            userSelect: 'none',
                                        }, children: "Remember me" })] }), (0, jsx_runtime_1.jsx)("button", { type: "submit", disabled: submitting || !username || !password, style: {
                                    width: '100%',
                                    padding: '12px',
                                    background: submitting || !username || !password
                                        ? 'rgba(99,102,241,0.4)'
                                        : 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                                    color: '#fff',
                                    border: 'none',
                                    borderRadius: 8,
                                    fontSize: 15,
                                    fontWeight: 600,
                                    cursor: submitting || !username || !password ? 'not-allowed' : 'pointer',
                                    transition: 'opacity 0.2s, background 0.2s',
                                    letterSpacing: '0.02em',
                                    boxShadow: submitting || !username || !password
                                        ? 'none'
                                        : '0 4px 16px rgba(99,102,241,0.4)',
                                }, children: submitting ? 'Signing in…' : 'Sign In' })] })] })] }));
}
//# sourceMappingURL=LoginPage.js.map