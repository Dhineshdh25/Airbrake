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
const api_1 = require("../lib/api");
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
function JiraSettings() {
    const [status, setStatus] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [busy, setBusy] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
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
            // Re-check status after successful OAuth round-trip
            (0, api_1.apiFetch)('/api/jira/status')
                .then(r => r.json())
                .then((j) => { setStatus(j); setLoading(false); })
                .catch(() => { setStatus({ connected: false, email: '', account_id: '' }); setLoading(false); });
            // Clean up the query param without a page reload
            const clean = window.location.pathname + window.location.hash;
            window.history.replaceState({}, '', clean);
        }
        if (params.get('jira_error')) {
            const code = params.get('jira_error') ?? 'unknown';
            const messages = {
                invalid_state: 'OAuth session expired or ran in a different server — please try again.',
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
        try {
            const r = await (0, api_1.apiFetch)('/api/jira/initiate', { method: 'POST' });
            const j = await r.json();
            if (j.redirect_url) {
                window.location.href = j.redirect_url; // navigate to Atlassian — no credentials in URL
            }
            else {
                setError('Could not start Jira connection. Please try again.');
                setBusy(false);
            }
        }
        catch {
            setError('Could not start Jira connection. Please try again.');
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
    return ((0, jsx_runtime_1.jsxs)("section", { style: cardStyle, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 20 }, children: "\uD83C\uDFAB" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, fontWeight: 700 }, children: "Jira Integration" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }, children: "Connect your Jira account to create tickets directly from error details." })] })] }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Checking connection\u2026" })) : status?.connected ? (
            /* ── Connected state ─────────────────────────────────────────────── */
            (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                            display: 'inline-flex', alignItems: 'center', gap: 8,
                            padding: '8px 14px', borderRadius: 8,
                            background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { color: '#34d399', fontWeight: 700, fontSize: 13 }, children: "\u2713 Connected" }), status.email && ((0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: ["as ", (0, jsx_runtime_1.jsx)("strong", { style: { color: 'var(--text)' }, children: status.email })] }))] }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }, children: "Tickets you create from Error Details will appear in Jira under your account." }), (0, jsx_runtime_1.jsx)("div", { children: (0, jsx_runtime_1.jsx)("button", { onClick: handleDisconnect, disabled: busy, style: { ...btnDanger, opacity: busy ? 0.6 : 1 }, children: busy ? 'Disconnecting…' : 'Disconnect Jira' }) })] })) : (
            /* ── Not connected state ─────────────────────────────────────────── */
            (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }, children: "You haven't connected your Jira account yet. Click below to authorise Airbrake to create tickets on your behalf. You only need to do this once." }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: handleConnect, style: btnPrimary, children: "Connect Jira" }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, color: 'var(--text-muted)' }, children: "You'll be redirected to Atlassian to sign in and grant access." })] })] })), error && ((0, jsx_runtime_1.jsx)("div", { style: {
                    marginTop: 10, fontSize: 12, color: '#f87171',
                    padding: '8px 12px', borderRadius: 6,
                    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                }, children: error }))] }));
}
//# sourceMappingURL=JiraSettings.js.map