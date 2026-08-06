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
        sync_failed: 0,
    });
    const [statusFilter, setStatusFilter] = (0, react_1.useState)('');
    const [syncStatusFilter, setSyncStatusFilter] = (0, react_1.useState)('');
    const [projectFilter, setProjectFilter] = (0, react_1.useState)('');
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [loadError, setLoadError] = (0, react_1.useState)(null);
    const [retryMessage, setRetryMessage] = (0, react_1.useState)(null);
    const [retryingId, setRetryingId] = (0, react_1.useState)(null);
    const [reloadTick, setReloadTick] = (0, react_1.useState)(0);
    const projectOptions = (0, react_1.useMemo)(() => {
        const projects = Array.from(new Set(tickets.map((row) => row.project_name).filter(Boolean)));
        return projects.sort();
    }, [tickets]);
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        setLoading(true);
        setLoadError(null);
        setRetryMessage(null);
        const params = new URLSearchParams();
        if (projectFilter)
            params.set('project', projectFilter);
        if (statusFilter)
            params.set('status', statusFilter);
        if (syncStatusFilter)
            params.set('sync_status', syncStatusFilter);
        (0, api_1.apiFetch)(`/api/jira/tickets?${params.toString()}`)
            .then((res) => res.json())
            .then((data) => {
            if (cancelled)
                return;
            setSummary({
                total: data.total ?? 0,
                resolved: data.resolved ?? 0,
                todo: data.todo ?? 0,
                sync_failed: data.sync_failed ?? 0,
            });
            setTickets((data.tickets ?? []));
        })
            .catch((error) => {
            if (!cancelled) {
                console.error('[JiraOverview] failed to load tickets:', error);
                setLoadError('Unable to load Jira tickets right now.');
                setTickets([]);
                setSummary({ total: 0, resolved: 0, todo: 0, sync_failed: 0 });
            }
        })
            .finally(() => {
            if (!cancelled)
                setLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, [projectFilter, statusFilter, syncStatusFilter, reloadTick]);
    async function retrySync(logId, issueKey) {
        setRetryMessage(null);
        setRetryingId(logId);
        try {
            const response = await (0, api_1.apiFetch)(`/api/jira/tickets/${encodeURIComponent(logId)}/retry-sync`, {
                method: 'POST',
            });
            const data = await response.json();
            setRetryMessage(data.success
                ? `Sync retry triggered for ${issueKey}. Refreshed ${data.log_ids?.length ?? 0} log(s).`
                : `Retry failed: ${data.detail || 'unknown error'}`);
            setReloadTick((tick) => tick + 1);
        }
        catch (error) {
            console.error('[JiraOverview] retry sync failed:', error);
            setRetryMessage('Retry failed. Please try again.');
        }
        finally {
            setRetryingId(null);
        }
    }
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "jira-overview", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 24 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Jira" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Jira tickets linked to Airbrake errors, with sync status and retry controls." })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }, children: [(0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(99,102,241,0.16)', color: '#818cf8', fontSize: 12, fontWeight: 700 }, children: ["Total tickets: ", summary.total] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(52,211,153,0.16)', color: '#34d399', fontSize: 12, fontWeight: 700 }, children: ["Resolved: ", summary.resolved] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(248,113,113,0.16)', color: '#f87171', fontSize: 12, fontWeight: 700 }, children: ["Todo: ", summary.todo] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '8px 12px', borderRadius: 999, background: 'rgba(251,191,36,0.16)', color: '#fbbf24', fontSize: 12, fontWeight: 700 }, children: ["Sync failed: ", summary.sync_failed] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'grid', gap: 12, marginBottom: 20 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsxs)("select", { value: projectFilter, onChange: (event) => setProjectFilter(event.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All projects" }), projectOptions.map((project) => ((0, jsx_runtime_1.jsx)("option", { value: project, children: project }, project)))] }), (0, jsx_runtime_1.jsxs)("select", { value: statusFilter, onChange: (event) => setStatusFilter(event.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All statuses" }), (0, jsx_runtime_1.jsx)("option", { value: "resolved", children: "Resolved" }), (0, jsx_runtime_1.jsx)("option", { value: "todo", children: "Todo" })] }), (0, jsx_runtime_1.jsxs)("select", { value: syncStatusFilter, onChange: (event) => setSyncStatusFilter(event.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All sync statuses" }), (0, jsx_runtime_1.jsx)("option", { value: "synced", children: "Synced" }), (0, jsx_runtime_1.jsx)("option", { value: "sync_failed", children: "Sync Failed" }), (0, jsx_runtime_1.jsx)("option", { value: "skipped", children: "Skipped" })] })] }), retryMessage ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '12px 14px', borderRadius: 8, background: 'rgba(56,189,248,0.12)', color: '#38bdf8' }, children: retryMessage })) : null] }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading Jira tickets\u2026" })) : loadError ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '16px', borderRadius: 8, background: 'rgba(248,113,113,0.1)', color: '#f87171' }, children: loadError })) : tickets.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "No Jira tickets found for this filter." })) : ((0, jsx_runtime_1.jsx)("div", { style: { display: 'grid', gap: 12 }, children: tickets.map((ticket) => ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 18,
                        borderRadius: 12,
                        background: 'var(--surface)',
                        border: '1px solid var(--card-border)',
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1fr) auto',
                        gap: 18,
                        alignItems: 'start',
                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { minWidth: 0, display: 'grid', gap: 10 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, fontWeight: 700, color: '#fff' }, children: ticket.issue_key || 'Unknown issue' }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }, children: ticket.project_name || 'No project' }), (0, jsx_runtime_1.jsx)("div", { style: { padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ticket.jira_status?.toLowerCase() === 'resolved' ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)', color: ticket.jira_status?.toLowerCase() === 'resolved' ? '#34d399' : '#f87171' }, children: ticket.jira_status || 'Unknown' }), (0, jsx_runtime_1.jsx)("div", { style: { padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ticket.jira_sync_status?.toLowerCase() === 'sync_failed' ? 'rgba(248,113,113,0.12)' : 'rgba(99,102,241,0.12)', color: ticket.jira_sync_status?.toLowerCase() === 'sync_failed' ? '#f87171' : '#818cf8' }, children: ticket.jira_sync_status || 'Unknown sync' })] }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 }, children: ticket.error || 'No error message available.' }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 12, color: 'var(--text-muted)', fontSize: 12 }, children: [(0, jsx_runtime_1.jsxs)("span", { children: ["Updated ", formatDate(ticket.updated_at)] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Created by ", ticket.created_by || 'unknown'] })] }), ticket.jira_sync_detail ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '10px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', fontSize: 12, border: '1px solid rgba(255,255,255,0.08)' }, children: ticket.jira_sync_detail })) : null] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }, children: [(0, jsx_runtime_1.jsx)("a", { href: ticket.jira_url || `https://your-domain.atlassian.net/browse/${encodeURIComponent(ticket.issue_key)}`, target: "_blank", rel: "noreferrer", style: {
                                        padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', color: '#38bdf8', background: 'rgba(56,189,248,0.08)', textDecoration: 'none', fontSize: 13,
                                    }, children: "View in Jira" }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => retrySync(ticket.log_id, ticket.issue_key), disabled: retryingId === ticket.log_id, style: {
                                        padding: '10px 14px', borderRadius: 8, border: 'none',
                                        background: retryingId === ticket.log_id ? 'rgba(148,163,184,0.4)' : 'rgba(99,102,241,0.95)',
                                        color: '#fff', cursor: retryingId === ticket.log_id ? 'default' : 'pointer',
                                        fontSize: 13, fontWeight: 700,
                                    }, children: retryingId === ticket.log_id ? 'Retrying…' : 'Retry sync' })] })] }, ticket.log_id))) }))] }));
}
//# sourceMappingURL=JiraOverview.js.map