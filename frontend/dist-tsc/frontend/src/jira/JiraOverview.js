"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JiraOverview = JiraOverview;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const api_1 = require("../lib/api");
const SELECT_STYLE = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 6,
    color: 'var(--text)',
    padding: '8px 11px',
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
};
function formatDate(value) {
    if (!value)
        return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime()))
        return value;
    return date.toLocaleString([], {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
    });
}
function JiraOverview() {
    const [tickets, setTickets] = (0, react_1.useState)([]);
    const [summary, setSummary] = (0, react_1.useState)({
        total: 0,
        resolved: 0,
        todo: 0,
    });
    const [statusFilter, setStatusFilter] = (0, react_1.useState)('');
    const [projectFilter, setProjectFilter] = (0, react_1.useState)('');
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [loadError, setLoadError] = (0, react_1.useState)(null);
    const [reloadTick, setReloadTick] = (0, react_1.useState)(0);
    const [jiraBaseUrl, setJiraBaseUrl] = (0, react_1.useState)('https://your-domain.atlassian.net');
    const projectOptions = (0, react_1.useMemo)(() => {
        const projects = Array.from(new Set(tickets.map((row) => row.project_name).filter(Boolean)));
        return projects.sort();
    }, [tickets]);
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        setLoading(true);
        setLoadError(null);
        // If there's no session token, redirect to login and show friendly message.
        const sessionToken = localStorage.getItem('session_token');
        if (!sessionToken) {
            setLoadError('Your session has expired. Please log in again.');
            try {
                window.location.href = '/auth/login';
            }
            catch (e) { }
            setLoading(false);
            return;
        }
        // Build JQL query to search Jira directly
        const jqlParts = [];
        if (projectFilter) {
            jqlParts.push(`project = "${projectFilter}"`);
        }
        if (statusFilter === 'resolved') {
            jqlParts.push('status IN (Done, Resolved, Closed)');
        }
        else if (statusFilter === 'todo') {
            jqlParts.push('status NOT IN (Done, Resolved, Closed)');
        }
        // Build final JQL query
        const jql = jqlParts.length > 0 ? jqlParts.join(' AND ') + ' ORDER BY updated DESC' : 'ORDER BY updated DESC';
        // Query Jira directly using the new search endpoint
        (0, api_1.apiFetch)(`/api/jira/search?jql=${encodeURIComponent(jql)}&maxResults=100`)
            .then((res) => res.json())
            .then((data) => {
            if (cancelled)
                return;
            // Extract Jira base URL from the first issue's self URL if available
            if (data.issues && data.issues.length > 0 && data.issues[0].self) {
                try {
                    const url = new URL(data.issues[0].self);
                    const baseUrl = `${url.protocol}//${url.host}`;
                    setJiraBaseUrl(baseUrl);
                }
                catch (e) {
                    console.warn('[JiraOverview] Could not parse Jira URL from self link');
                }
            }
            // Transform Jira issues to our ticket format
            const issues = data.issues ?? [];
            const transformedTickets = issues.map((issue) => {
                const status = issue.fields.status?.name || 'Unknown';
                return {
                    log_id: issue.id,
                    issue_key: issue.key,
                    project_name: issue.fields.project?.name || issue.fields.project?.key || '',
                    error: issue.fields.summary || 'No summary',
                    jira_status: status,
                    jira_sync_status: 'synced',
                    jira_sync_detail: '',
                    jira_url: `${jiraBaseUrl}/browse/${issue.key}`,
                    created_by: issue.fields.reporter?.displayName || 'Unknown',
                    updated_at: issue.fields.updated || issue.fields.created || '',
                };
            });
            // Calculate summary stats
            const resolved = transformedTickets.filter(t => ['done', 'resolved', 'closed'].includes(t.jira_status.toLowerCase())).length;
            const todo = transformedTickets.length - resolved;
            setSummary({
                total: transformedTickets.length,
                resolved,
                todo,
            });
            setTickets(transformedTickets);
        })
            .catch((error) => {
            if (!cancelled) {
                console.error('[JiraOverview] failed to load tickets:', error);
                // If we received an ApiError-like object, prefer status/body for messages
                const status = error?.status;
                const body = error?.body;
                if (status === 401) {
                    // Clear session client-side already handled by apiFetch; show friendly message
                    setLoadError('Your session has expired. Please log in again.');
                }
                else if (status === 403) {
                    setLoadError('You do not have permission to view Jira tickets.');
                }
                else if (status === 404) {
                    setLoadError('Jira resource not found.');
                }
                else if (body && typeof body === 'object' && (body.error === 'Jira account not connected' || body.error === 'Jira not connected')) {
                    setLoadError('Jira not connected. Please connect your Jira account in Settings.');
                }
                else {
                    setLoadError('Unable to load Jira tickets. Make sure you have connected your Jira account.');
                }
                setTickets([]);
                setSummary({ total: 0, resolved: 0, todo: 0 });
            }
        })
            .finally(() => {
            if (!cancelled)
                setLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, [projectFilter, statusFilter, reloadTick, jiraBaseUrl]);
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "jira-overview", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 24 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Jira" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "All Jira tickets from your connected Jira instance." })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }, children: [(0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(99,102,241,0.16)', color: '#818cf8', fontSize: 12, fontWeight: 700 }, children: ["Total tickets: ", summary.total] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(52,211,153,0.16)', color: '#34d399', fontSize: 12, fontWeight: 700 }, children: ["Resolved: ", summary.resolved] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(248,113,113,0.16)', color: '#f87171', fontSize: 12, fontWeight: 700 }, children: ["Todo: ", summary.todo] })] }), (0, jsx_runtime_1.jsx)("div", { style: { display: 'grid', gap: 12, marginBottom: 20 }, children: (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsxs)("select", { value: projectFilter, onChange: (event) => setProjectFilter(event.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All projects" }), projectOptions.map((project) => ((0, jsx_runtime_1.jsx)("option", { value: project, children: project }, project)))] }), (0, jsx_runtime_1.jsxs)("select", { value: statusFilter, onChange: (event) => setStatusFilter(event.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All statuses" }), (0, jsx_runtime_1.jsx)("option", { value: "resolved", children: "Resolved" }), (0, jsx_runtime_1.jsx)("option", { value: "todo", children: "Todo" })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => setReloadTick((tick) => tick + 1), style: {
                                padding: '8px 16px',
                                borderRadius: 8,
                                border: '1px solid var(--input-border)',
                                background: 'var(--input-bg)',
                                color: 'var(--text)',
                                cursor: 'pointer',
                                fontSize: 13,
                            }, children: "Refresh" })] }) }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading Jira tickets\u2026" })) : loadError ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '16px', borderRadius: 8, background: 'rgba(248,113,113,0.1)', color: '#f87171' }, children: loadError })) : tickets.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "No Jira tickets found for this filter." })) : ((0, jsx_runtime_1.jsx)("div", { style: { display: 'grid', gap: 12 }, children: tickets.map((ticket) => ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 18,
                        borderRadius: 12,
                        background: 'var(--surface)',
                        border: '1px solid var(--card-border)',
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1fr) auto',
                        gap: 18,
                        alignItems: 'start',
                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { minWidth: 0, display: 'grid', gap: 10 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, fontWeight: 700, color: '#fff' }, children: ticket.issue_key || 'Unknown issue' }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }, children: ticket.project_name || 'No project' }), (0, jsx_runtime_1.jsx)("div", { style: { padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ['done', 'resolved', 'closed'].includes(ticket.jira_status?.toLowerCase()) ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)', color: ['done', 'resolved', 'closed'].includes(ticket.jira_status?.toLowerCase()) ? '#34d399' : '#f87171' }, children: ticket.jira_status || 'Unknown' })] }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 }, children: ticket.error || 'No error message available.' }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 12, color: 'var(--text-muted)', fontSize: 12 }, children: [(0, jsx_runtime_1.jsxs)("span", { children: ["Updated ", formatDate(ticket.updated_at)] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Created by ", ticket.created_by || 'unknown'] })] })] }), (0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }, children: (0, jsx_runtime_1.jsx)("a", { href: ticket.jira_url, target: "_blank", rel: "noreferrer", style: {
                                    padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', color: '#38bdf8', background: 'rgba(56,189,248,0.08)', textDecoration: 'none', fontSize: 13,
                                }, children: "View in Jira" }) })] }, ticket.log_id))) }))] }));
}
//# sourceMappingURL=JiraOverview.js.map