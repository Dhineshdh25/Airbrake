"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JiraOverview = JiraOverview;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * JiraOverview — Jira tickets dashboard.
 *
 * Fetches all Jira issues visible to the connected account via
 * GET /api/jira/search?jql=...
 * Reuses existing OAuth integration — no new auth logic.
 *
 * Columns: Issue Key | Summary | Project | Status | Priority | Assignee | Created | Updated | Actions
 */
const react_1 = require("react");
const api_1 = require("../lib/api");
const PaginationControls_1 = require("../components/PaginationControls");
const PRIORITY_ORDER = {
    Highest: 0, Critical: 0,
    High: 1,
    Medium: 2,
    Low: 3,
    Lowest: 4, Trivial: 4,
};
const TERMINAL_STATUSES = new Set(['done', 'closed', 'resolved', 'fixed', 'complete', 'completed']);
// 30-second in-memory cache — keyed by JQL string
const _cache = new Map();
const CACHE_TTL_MS = 30000;
// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtDate(iso) {
    if (!iso)
        return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime()))
        return iso;
    return d.toLocaleString([], {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
    });
}
function statusColor(name) {
    const n = (name ?? '').toLowerCase();
    if (TERMINAL_STATUSES.has(n))
        return '#34d399';
    if (['in progress', 'in review', 'in development'].some(s => n.includes(s)))
        return '#fbbf24';
    return '#818cf8';
}
function priorityColor(name) {
    const n = (name ?? '').toLowerCase();
    if (n.includes('highest') || n.includes('critical'))
        return '#ef4444';
    if (n.includes('high'))
        return '#f87171';
    if (n.includes('medium'))
        return '#fbbf24';
    if (n.includes('low'))
        return '#60a5fa';
    return 'var(--text-muted)';
}
function browseUrl(issue, siteUrl) {
    if (!siteUrl || !issue.key) {
        console.warn('[Jira] Missing siteUrl or issue.key:', { siteUrl, key: issue.key });
        return `#${issue.key || 'unknown'}`;
    }
    // Remove trailing slash from siteUrl if present
    const baseUrl = siteUrl.replace(/\/$/, '');
    return `${baseUrl}/browse/${issue.key}`;
}
// ── Shared styles ─────────────────────────────────────────────────────────────
const SELECT_STYLE = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 6,
    color: 'var(--text)',
    padding: '7px 10px',
    fontSize: 12,
    outline: 'none',
    cursor: 'pointer',
};
const INPUT_STYLE = {
    ...SELECT_STYLE,
    minWidth: 200,
};
const TH_STYLE = {
    padding: '10px 14px',
    textAlign: 'left',
    fontSize: 11,
    fontWeight: 700,
    color: 'var(--text-muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    whiteSpace: 'nowrap',
    borderBottom: '1px solid var(--card-border)',
    background: 'var(--surface)',
};
const TD_STYLE = {
    padding: '10px 14px',
    fontSize: 13,
    verticalAlign: 'middle',
    borderBottom: '1px solid var(--card-border)',
};
// ── Component ─────────────────────────────────────────────────────────────────
function JiraOverview() {
    // ── Remote data ──────────────────────────────────────────────────────────
    const [issues, setIssues] = (0, react_1.useState)([]);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [loadError, setLoadError] = (0, react_1.useState)(null);
    const [notConnected, setNotConnected] = (0, react_1.useState)(false);
    const [jiraSiteUrl, setJiraSiteUrl] = (0, react_1.useState)('');
    const [reloadTick, setReloadTick] = (0, react_1.useState)(0);
    const bypassCache = (0, react_1.useRef)(false);
    // ── Poll-sync state ───────────────────────────────────────────────────────
    const [syncing, setSyncing] = (0, react_1.useState)(false);
    const [syncResult, setSyncResult] = (0, react_1.useState)(null);
    // Run poll-sync automatically when the Jira page loads and after every manual refresh
    (0, react_1.useEffect)(() => {
        (0, api_1.apiFetch)('/api/jira/poll-sync', { method: 'POST' })
            .then(r => r.json())
            .then((d) => {
            if (d.synced > 0) {
                // Some tickets were synced — refresh the issue list to reflect new statuses
                bypassCache.current = true;
                setReloadTick(t => t + 1);
            }
            setSyncResult(d);
        })
            .catch(() => { });
    }, []);
    async function handleSyncNow() {
        setSyncing(true);
        setSyncResult(null);
        try {
            const r = await (0, api_1.apiFetch)('/api/jira/poll-sync', { method: 'POST' });
            const d = await r.json();
            setSyncResult(d);
            if (d.synced > 0) {
                bypassCache.current = true;
                setReloadTick(t => t + 1);
            }
        }
        catch {
            /* non-fatal */
        }
        finally {
            setSyncing(false);
        }
    }
    // ── Filter / sort / search state ─────────────────────────────────────────
    const [search, setSearch] = (0, react_1.useState)('');
    const [projectFilter, setProjectFilter] = (0, react_1.useState)('');
    const [statusFilter, setStatusFilter] = (0, react_1.useState)('');
    const [priorityFilter, setPriorityFilter] = (0, react_1.useState)('');
    const [assigneeFilter, setAssigneeFilter] = (0, react_1.useState)('');
    const [page, setPage] = (0, react_1.useState)(1);
    const [sortKey, setSortKey] = (0, react_1.useState)('updated');
    const [sortDir, setSortDir] = (0, react_1.useState)('desc');
    // ── Derived filter options ────────────────────────────────────────────────
    const projectOptions = (0, react_1.useMemo)(() => [...new Set(issues.map(i => i.fields?.project?.name ?? '').filter(Boolean))].sort(), [issues]);
    const statusOptions = (0, react_1.useMemo)(() => [...new Set(issues.map(i => i.fields?.status?.name ?? '').filter(Boolean))].sort(), [issues]);
    const priorityOptions = (0, react_1.useMemo)(() => [...new Set(issues.map(i => i.fields?.priority?.name ?? '').filter(Boolean))].sort(), [issues]);
    const assigneeOptions = (0, react_1.useMemo)(() => [...new Set(issues.map(i => i.fields?.assignee?.displayName ?? '').filter(Boolean))].sort(), [issues]);
    // ── Filtered + sorted rows ────────────────────────────────────────────────
    const pageSize = 5;
    const visible = (0, react_1.useMemo)(() => {
        console.log('[Jira useMemo] Computing visible rows from', issues.length, 'issues');
        let rows = [...issues]; // Create a copy to avoid mutating original
        const q = search.toLowerCase().trim();
        if (q)
            rows = rows.filter(i => i.key.toLowerCase().includes(q) ||
                (i.fields?.summary ?? '').toLowerCase().includes(q));
        if (projectFilter)
            rows = rows.filter(i => (i.fields?.project?.name ?? '') === projectFilter);
        if (statusFilter)
            rows = rows.filter(i => (i.fields?.status?.name ?? '') === statusFilter);
        if (priorityFilter)
            rows = rows.filter(i => (i.fields?.priority?.name ?? '') === priorityFilter);
        if (assigneeFilter)
            rows = rows.filter(i => (i.fields?.assignee?.displayName ?? '') === assigneeFilter);
        rows = rows.sort((a, b) => {
            let cmp = 0;
            if (sortKey === 'updated') {
                cmp = (a.fields?.updated ?? '') < (b.fields?.updated ?? '') ? -1 : 1;
            }
            else if (sortKey === 'created') {
                cmp = (a.fields?.created ?? '') < (b.fields?.created ?? '') ? -1 : 1;
            }
            else if (sortKey === 'status') {
                cmp = (a.fields?.status?.name ?? '') < (b.fields?.status?.name ?? '') ? -1 : 1;
            }
            else if (sortKey === 'priority') {
                const pa = PRIORITY_ORDER[a.fields?.priority?.name ?? ''] ?? 99;
                const pb = PRIORITY_ORDER[b.fields?.priority?.name ?? ''] ?? 99;
                cmp = pa - pb;
            }
            return sortDir === 'asc' ? cmp : -cmp;
        });
        const start = (page - 1) * pageSize;
        const paged = rows.slice(start, start + pageSize);
        console.log('[Jira useMemo] Visible rows computed:', rows.length, 'page', page, 'pageSize', pageSize);
        return paged;
    }, [issues, search, projectFilter, statusFilter, priorityFilter, assigneeFilter, sortKey, sortDir, page]);
    const totalPages = (0, react_1.useMemo)(() => {
        const total = issues.filter((issue) => {
            const q = search.toLowerCase().trim();
            if (q && !(issue.key.toLowerCase().includes(q) || (issue.fields?.summary ?? '').toLowerCase().includes(q)))
                return false;
            if (projectFilter && (issue.fields?.project?.name ?? '') !== projectFilter)
                return false;
            if (statusFilter && (issue.fields?.status?.name ?? '') !== statusFilter)
                return false;
            if (priorityFilter && (issue.fields?.priority?.name ?? '') !== priorityFilter)
                return false;
            if (assigneeFilter && (issue.fields?.assignee?.displayName ?? '') !== assigneeFilter)
                return false;
            return true;
        }).length;
        return Math.max(1, Math.ceil(total / pageSize));
    }, [issues, search, projectFilter, statusFilter, priorityFilter, assigneeFilter]);
    (0, react_1.useEffect)(() => {
        setPage(1);
    }, [search, projectFilter, statusFilter, priorityFilter, assigneeFilter]);
    (0, react_1.useEffect)(() => {
        if (page > totalPages)
            setPage(totalPages);
    }, [page, totalPages]);
    // ── Fetch ─────────────────────────────────────────────────────────────────
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        setLoading(true);
        setLoadError(null);
        setNotConnected(false);
        const cacheKey = 'default-search';
        const cached = _cache.get(cacheKey);
        const useCache = !bypassCache.current && cached && (Date.now() - cached.ts < CACHE_TTL_MS);
        bypassCache.current = false;
        const doFetch = useCache
            ? Promise.resolve(cached.data)
            : (0, api_1.apiFetch)('/api/jira/search?maxResults=200')
                .then(r => r.json())
                .then(data => { _cache.set(cacheKey, { ts: Date.now(), data }); return data; });
        doFetch
            .then((data) => {
            console.log('[Jira] Raw API response:', data);
            if (cancelled)
                return;
            if (data.needs_auth || data.error?.toLowerCase().includes('not connected')) {
                console.log('[Jira] Auth required or not connected');
                setNotConnected(true);
                setIssues([]);
                return;
            }
            if (data.error) {
                console.log('[Jira] Error in response:', data.error);
                setLoadError(data.error);
                setIssues([]);
                return;
            }
            // Handle message (e.g., "no accessible projects")
            const issuesArray = data.issues ?? [];
            if (data.message && issuesArray.length === 0) {
                console.log('[Jira] Message with no issues:', data.message);
                setLoadError(data.message);
                setIssues([]);
                return;
            }
            const list = issuesArray;
            console.log('[Jira] Setting issues state:', list.length, 'issues');
            console.log('[Jira] First issue sample:', list[0]);
            // Store Jira site URL from API response
            if (data.site_url) {
                setJiraSiteUrl(data.site_url);
                console.log('[Jira] Jira site URL from API:', data.site_url);
            }
            else {
                console.warn('[Jira] No site_url in API response');
            }
            console.log('[Jira] About to call setIssues with', list.length, 'issues');
            setIssues(list);
        })
            .catch((err) => {
            if (cancelled)
                return;
            const msg = String(err?.message ?? err ?? '');
            if (msg.includes('401') || msg.includes('Unauthorized') || msg.includes('needs_auth')) {
                setNotConnected(true);
            }
            else {
                setLoadError('Unable to load Jira tickets. Check your connection in Settings.');
            }
            setIssues([]);
        })
            .finally(() => { if (!cancelled)
            setLoading(false); });
        return () => { cancelled = true; };
    }, [reloadTick]);
    // ── Column sort handler ───────────────────────────────────────────────────
    function handleSort(key) {
        if (sortKey === key) {
            setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        }
        else {
            setSortKey(key);
            setSortDir('desc');
        }
    }
    function SortArrow({ k }) {
        if (sortKey !== k)
            return (0, jsx_runtime_1.jsx)("span", { style: { opacity: 0.25 }, children: " \u2195" });
        return (0, jsx_runtime_1.jsx)("span", { style: { color: '#818cf8' }, children: sortDir === 'asc' ? ' ↑' : ' ↓' });
    }
    const resolved = issues.filter(i => TERMINAL_STATUSES.has((i.fields?.status?.name ?? '').toLowerCase())).length;
    const todo = issues.length - resolved;
    console.log('[Jira Render] State check:', {
        issuesLength: issues.length,
        loading,
        loadError,
        notConnected,
        visibleLength: visible.length,
        resolved,
        todo,
    });
    // ── Render ────────────────────────────────────────────────────────────────
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "jira-overview", style: { minHeight: '100%' }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 20 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Jira" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "All tickets from your connected Jira instance." })] }), !notConnected && !loadError && ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 18 }, children: [(0, jsx_runtime_1.jsxs)("span", { style: { padding: '7px 12px', borderRadius: 999, background: 'rgba(99,102,241,0.16)', color: '#818cf8', fontSize: 12, fontWeight: 700 }, children: ["Total: ", issues.length] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '7px 12px', borderRadius: 999, background: 'rgba(52,211,153,0.16)', color: '#34d399', fontSize: 12, fontWeight: 700 }, children: ["Resolved: ", resolved] }), (0, jsx_runtime_1.jsxs)("span", { style: { padding: '7px 12px', borderRadius: 999, background: 'rgba(248,113,113,0.16)', color: '#f87171', fontSize: 12, fontWeight: 700 }, children: ["Open: ", todo] })] })), !notConnected && ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'center' }, children: [(0, jsx_runtime_1.jsx)("input", { type: "search", placeholder: "Search key or summary\u2026", value: search, onChange: e => setSearch(e.target.value), style: INPUT_STYLE }), (0, jsx_runtime_1.jsxs)("select", { value: projectFilter, onChange: e => setProjectFilter(e.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All projects" }), projectOptions.map(p => (0, jsx_runtime_1.jsx)("option", { value: p, children: p }, p))] }), (0, jsx_runtime_1.jsxs)("select", { value: statusFilter, onChange: e => setStatusFilter(e.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All statuses" }), statusOptions.map(s => (0, jsx_runtime_1.jsx)("option", { value: s, children: s }, s))] }), (0, jsx_runtime_1.jsxs)("select", { value: priorityFilter, onChange: e => setPriorityFilter(e.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All priorities" }), priorityOptions.map(p => (0, jsx_runtime_1.jsx)("option", { value: p, children: p }, p))] }), (0, jsx_runtime_1.jsxs)("select", { value: assigneeFilter, onChange: e => setAssigneeFilter(e.target.value), style: SELECT_STYLE, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All assignees" }), assigneeOptions.map(a => (0, jsx_runtime_1.jsx)("option", { value: a, children: a }, a))] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => { bypassCache.current = true; setReloadTick(t => t + 1); }, style: { padding: '7px 14px', borderRadius: 6, border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', cursor: 'pointer', fontSize: 12 }, children: "\u21BA Refresh" }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: handleSyncNow, disabled: syncing, title: "Check all linked Jira tickets and resolve any that are Done in Jira", style: {
                            padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                            border: '1px solid rgba(99,102,241,0.4)',
                            background: syncing ? 'rgba(99,102,241,0.05)' : 'rgba(99,102,241,0.12)',
                            color: '#818cf8', cursor: syncing ? 'not-allowed' : 'pointer',
                            opacity: syncing ? 0.7 : 1,
                        }, children: syncing ? '⏳ Syncing…' : '⚡ Sync from Jira' }), syncResult && ((0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: [syncResult.synced > 0
                                ? (0, jsx_runtime_1.jsxs)("span", { style: { color: '#34d399', fontWeight: 600 }, children: ["\u2713 ", syncResult.synced, " resolved"] })
                                : (0, jsx_runtime_1.jsx)("span", { children: "No new resolutions" }), syncResult.failed > 0 && (0, jsx_runtime_1.jsxs)("span", { style: { color: '#f87171', marginLeft: 6 }, children: [syncResult.failed, " failed"] })] })), !loading && ((0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)', marginLeft: 4 }, children: [visible.length, " result", visible.length !== 1 ? 's' : ''] }))] })), notConnected ? ((0, jsx_runtime_1.jsxs)("div", { style: { padding: '24px 20px', borderRadius: 10, background: 'rgba(99,102,241,0.07)', border: '1px solid rgba(99,102,241,0.2)', fontSize: 14, color: 'var(--text-muted)' }, children: ["\uD83D\uDD17 Connect your Jira account from", ' ', (0, jsx_runtime_1.jsx)("a", { href: "/settings", style: { color: '#818cf8', textDecoration: 'none', fontWeight: 600 }, children: "Settings" }), ' ', "to view your tickets here."] })) : loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading Jira tickets\u2026" })) : loadError ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '14px 18px', borderRadius: 8, background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.2)', color: '#f87171', fontSize: 13 }, children: loadError })) : visible.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: "No tickets match the current filters." })) : (
            /* ── Table ─────────────────────────────────────────────────────── */
            (0, jsx_runtime_1.jsx)("div", { style: { overflowX: 'auto', borderRadius: 10, border: '1px solid var(--card-border)' }, children: (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse', background: 'var(--surface)' }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { style: TH_STYLE, children: "Issue Key" }), (0, jsx_runtime_1.jsx)("th", { style: { ...TH_STYLE, minWidth: 260 }, children: "Summary" }), (0, jsx_runtime_1.jsx)("th", { style: TH_STYLE, children: "Project" }), (0, jsx_runtime_1.jsxs)("th", { style: { ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }, onClick: () => handleSort('status'), children: ["Status ", (0, jsx_runtime_1.jsx)(SortArrow, { k: "status" })] }), (0, jsx_runtime_1.jsxs)("th", { style: { ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }, onClick: () => handleSort('priority'), children: ["Priority ", (0, jsx_runtime_1.jsx)(SortArrow, { k: "priority" })] }), (0, jsx_runtime_1.jsx)("th", { style: TH_STYLE, children: "Assignee" }), (0, jsx_runtime_1.jsxs)("th", { style: { ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }, onClick: () => handleSort('created'), children: ["Created ", (0, jsx_runtime_1.jsx)(SortArrow, { k: "created" })] }), (0, jsx_runtime_1.jsxs)("th", { style: { ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }, onClick: () => handleSort('updated'), children: ["Updated ", (0, jsx_runtime_1.jsx)(SortArrow, { k: "updated" })] }), (0, jsx_runtime_1.jsx)("th", { style: { ...TH_STYLE, textAlign: 'right' }, children: "Actions" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: visible.map((issue, idx) => {
                                const isLast = idx === visible.length - 1;
                                const tdStyle = {
                                    ...TD_STYLE,
                                    borderBottom: isLast ? 'none' : '1px solid var(--card-border)',
                                };
                                const url = browseUrl(issue, jiraSiteUrl);
                                const sName = issue.fields?.status?.name ?? '—';
                                const pName = issue.fields?.priority?.name;
                                return ((0, jsx_runtime_1.jsxs)("tr", { style: { transition: 'background 0.1s' }, onMouseEnter: e => (e.currentTarget.style.background = 'rgba(255,255,255,0.025)'), onMouseLeave: e => (e.currentTarget.style.background = ''), children: [(0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)("a", { href: url, target: "_blank", rel: "noreferrer", style: { color: '#818cf8', fontWeight: 700, textDecoration: 'none', fontFamily: 'ui-monospace, monospace', fontSize: 12 }, children: issue.key }) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, maxWidth: 340 }, children: (0, jsx_runtime_1.jsx)("div", { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text)' }, children: issue.fields?.summary ?? '—' }) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }, children: issue.fields?.project?.name ?? issue.fields?.project?.key ?? '—' }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)("span", { style: {
                                                    padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
                                                    background: `${statusColor(sName)}1a`,
                                                    color: statusColor(sName),
                                                    whiteSpace: 'nowrap',
                                                }, children: sName }) }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: pName ? ((0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, fontWeight: 600, color: priorityColor(pName) }, children: pName })) : (0, jsx_runtime_1.jsx)("span", { style: { color: 'var(--text-muted)' }, children: "\u2014" }) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }, children: issue.fields?.assignee?.displayName ?? ((0, jsx_runtime_1.jsx)("span", { style: { fontStyle: 'italic', opacity: 0.5 }, children: "Unassigned" })) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }, children: fmtDate(issue.fields?.created) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }, children: fmtDate(issue.fields?.updated) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, textAlign: 'right' }, children: (0, jsx_runtime_1.jsx)("a", { href: url, target: "_blank", rel: "noreferrer", style: {
                                                    padding: '5px 12px', borderRadius: 6,
                                                    border: '1px solid rgba(56,189,248,0.3)',
                                                    color: '#38bdf8', background: 'rgba(56,189,248,0.07)',
                                                    textDecoration: 'none', fontSize: 12, whiteSpace: 'nowrap',
                                                }, children: "Open in Jira \u2197" }) })] }, issue.id));
                            }) })] }) })), !notConnected && !loading && !loadError && totalPages > 1 && ((0, jsx_runtime_1.jsx)(PaginationControls_1.PaginationControls, { currentPage: page, totalPages: totalPages, onPageChange: setPage }))] }));
}
//# sourceMappingURL=JiraOverview.js.map