"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JiraSettings = JiraSettings;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * JiraSettings — per-user Jira OAuth connection panel.
 *
 * Shown inside the Settings page.
 * Each developer connects their own Jira account here (one-time).
 * After connecting, every "Create Jira Ticket" click uses their identity.
 *
 * No Client ID / Client Secret is exposed here — those are administrator
 * environment variables, invisible to developers.
 */
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const api_1 = require("../lib/api");
const AuthContext_1 = require("../auth/AuthContext");
const cardStyle = {
    background: 'var(--surface)',
    border: '1px solid var(--card-border)',
    borderRadius: 10,
    padding: 20,
};
const btnPrimary = {
    padding: '8px 18px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 600,
    background: '#6366f1',
    color: '#fff',
    border: 'none',
    cursor: 'pointer',
};
const btnDanger = {
    padding: '8px 18px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 600,
    background: 'rgba(239,68,68,0.1)',
    color: '#f87171',
    border: '1px solid rgba(239,68,68,0.25)',
    cursor: 'pointer',
};
// ─── Fetch a fresh CSRF token from the server when the in-memory one is gone ──
// This happens after a full page refresh — the session cookie is still valid
// but the in-memory CSRF token (stored by AuthContext) is gone.
async function ensureCsrfToken() {
    const current = (0, AuthContext_1.getCsrfToken)();
    if (current)
        return current;
    try {
        const res = await fetch(`${api_1.API_BASE_URL}/api/auth/csrf`, {
            credentials: 'include',
        });
        if (!res.ok)
            throw new Error(`csrf endpoint returned ${res.status}`);
        const data = await res.json();
        if (data.csrf_token) {
            // Store in the module-level memory so subsequent apiFetch calls use it.
            (0, AuthContext_1.setCsrfTokenMemory)(data.csrf_token);
            return data.csrf_token;
        }
    }
    catch {
        // Fall through — we'll get a 403 from the server if still missing,
        // which we translate into a helpful message below.
    }
    return '';
}
function JiraSettings() {
    const [status, setStatus] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [busy, setBusy] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
    const sectionRef = (0, react_1.useRef)(null);
    const location = (0, react_router_dom_1.useLocation)();
    // ── Scroll into view when redirected from Jira nav (not connected) ────────
    (0, react_1.useEffect)(() => {
        // With HashRouter, navigate('/settings?jira_section=1') puts the query
        // string inside the hash — React Router exposes it via location.search.
        const params = new URLSearchParams(location.search);
        if (params.get('jira_section') === '1' && sectionRef.current) {
            setTimeout(() => {
                sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 120);
        }
    }, [location.search]);
    // ── Check connection status on mount ──────────────────────────────────────
    (0, react_1.useEffect)(() => {
        (0, api_1.apiFetch)('/api/jira/status')
            .then(r => r.json())
            .then((j) => { setStatus(j); setLoading(false); })
            .catch(() => { setStatus({ connected: false, email: '', account_id: '' }); setLoading(false); });
    }, []);
    // ── Handle post-OAuth redirect params ────────────────────────────────────
    (0, react_1.useEffect)(() => {
        const params = new URLSearchParams(window.location.search);
        if (params.get('jira_connected') === 'true') {
            (0, api_1.apiFetch)('/api/jira/status')
                .then(r => r.json())
                .then((j) => { setStatus(j); setLoading(false); })
                .catch(() => { setStatus({ connected: false, email: '', account_id: '' }); setLoading(false); });
            const clean = window.location.pathname + window.location.hash;
            window.history.replaceState({}, '', clean);
        }
        if (params.get('jira_error')) {
            const code = params.get('jira_error') ?? 'unknown';
            const messages = {
                invalid_state: 'OAuth session expired — please try again.',
                token_exchange_failed: 'Atlassian rejected the token exchange. Check your Client ID and Secret.',
                no_accessible_resources: 'No Jira sites found on your Atlassian account.',
                missing_params: 'OAuth callback was missing required parameters.',
                unexpected: 'An unexpected error occurred. Check Lambda logs for details.',
                access_denied: 'You denied access to Jira. Click Connect Jira to try again.',
            };
            setError(`Jira connection failed: ${messages[code] ?? code}`);
            setLoading(false);
            const clean = window.location.pathname + window.location.hash;
            window.history.replaceState({}, '', clean);
        }
    }, []);
    async function handleConnect() {
        setBusy(true);
        setError('');
        // Ensure we have a CSRF token before sending the POST.
        // After a page refresh the in-memory token is gone; we fetch a fresh one
        // from /api/auth/csrf without forcing a full re-login.
        const csrf = await ensureCsrfToken();
        if (!csrf) {
            setError('Could not obtain a security token. Please refresh the page and try again.');
            setBusy(false);
            return;
        }
        try {
            const r = await fetch(`${api_1.API_BASE_URL}/api/jira/initiate`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrf,
                },
            });
            if (r.status === 401) {
                setError('Your session has expired. Please log in again.');
                setBusy(false);
                return;
            }
            if (r.status === 403) {
                let msg = 'Permission denied. Please refresh the page and try again.';
                try {
                    const body = await r.json();
                    if (body?.message)
                        msg = body.message;
                }
                catch { /* ignore parse error */ }
                setError(msg);
                setBusy(false);
                return;
            }
            if (!r.ok) {
                let msg = `Server error (${r.status}). Please try again or contact support.`;
                try {
                    const body = await r.json();
                    // Show config errors safely — never expose raw exception text
                    if (r.status === 500 && body?.error === 'Configuration error') {
                        msg = body.message ?? msg;
                    }
                }
                catch { /* ignore parse error */ }
                setError(msg);
                setBusy(false);
                return;
            }
            const j = await r.json();
            if (j.redirect_url) {
                // Redirect to Atlassian — the session cookie travels with the browser
                // automatically; no token appears in the URL.
                window.location.href = j.redirect_url;
            }
            else {
                setError('Could not start Jira connection — no redirect URL returned.');
                setBusy(false);
            }
        }
        catch {
            setError('Network error. Please check your connection and try again.');
            setBusy(false);
        }
    }
    async function handleDisconnect() {
        if (!window.confirm('Disconnect your Jira account? You can reconnect at any time.'))
            return;
        setBusy(true);
        setError('');
        try {
            await (0, api_1.apiFetch)('/api/jira/disconnect', { method: 'POST' });
            setStatus({ connected: false, email: '', account_id: '' });
        }
        catch {
            setError('Failed to disconnect. Please try again.');
        }
        finally {
            setBusy(false);
        }
    }
    // ── Render ────────────────────────────────────────────────────────────────
    return ((0, jsx_runtime_1.jsxs)("section", { ref: sectionRef, style: cardStyle, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 20 }, children: "\uD83C\uDFAB" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, fontWeight: 700 }, children: "Jira Integration" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }, children: "Connect your Jira account to create tickets directly from error details." })] })] }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Checking connection\u2026" })) : status?.connected ? (
            /* ── Connected state ─────────────────────────────────────────────── */
            (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                            display: 'inline-flex', alignItems: 'center', gap: 8,
                            padding: '8px 14px', borderRadius: 8,
                            background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { color: '#34d399', fontWeight: 700, fontSize: 13 }, children: "\u2713 Connected" }), status.email && ((0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: ["as ", (0, jsx_runtime_1.jsx)("strong", { style: { color: 'var(--text)' }, children: status.email })] }))] }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }, children: "Tickets you create from Error Details will appear in Jira under your account." }), (0, jsx_runtime_1.jsx)("div", { children: (0, jsx_runtime_1.jsx)("button", { onClick: handleDisconnect, disabled: busy, style: { ...btnDanger, opacity: busy ? 0.6 : 1 }, children: busy ? 'Disconnecting…' : 'Disconnect Jira' }) })] })) : (
            /* ── Not connected state ─────────────────────────────────────────── */
            (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }, children: "You haven't connected your Jira account yet. Click below to authorise Airbrake to create tickets on your behalf. You only need to do this once." }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: handleConnect, disabled: busy, style: { ...btnPrimary, opacity: busy ? 0.7 : 1 }, children: busy ? 'Connecting…' : 'Connect Jira' }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, color: 'var(--text-muted)' }, children: "You'll be redirected to Atlassian to sign in and grant access." })] })] })), error && ((0, jsx_runtime_1.jsx)("div", { style: {
                    marginTop: 10, fontSize: 12, color: '#f87171',
                    padding: '8px 12px', borderRadius: 6,
                    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                }, children: error }))] }));
}
//# sourceMappingURL=JiraSettings.js.map