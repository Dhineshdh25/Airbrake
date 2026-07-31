"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BreaksList = BreaksList;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const api_1 = require("../lib/api");
// ── Constants ─────────────────────────────────────────────────────────────────
const LIMIT = 20;
// ── Shared styles ─────────────────────────────────────────────────────────────
const selectStyle = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 6,
    color: 'var(--text)',
    padding: '7px 28px 7px 11px',
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
    appearance: 'none',
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' fill='none'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2364748b' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 10px center',
};
const inputStyle = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 6,
    color: 'var(--text)',
    padding: '7px 11px',
    fontSize: 13,
    outline: 'none',
};
// ── Sub-components ────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
    const styles = {
        new: { bg: 'rgba(99,102,241,0.15)', color: '#818cf8', border: 'rgba(99,102,241,0.3)', label: '● New' },
        existing: { bg: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: 'rgba(245,158,11,0.3)', label: '◎ Existing' },
        regression: { bg: 'rgba(239,68,68,0.15)', color: '#f87171', border: 'rgba(239,68,68,0.3)', label: '⚠ Regression' },
    };
    const s = styles[status] ?? styles.new;
    return ((0, jsx_runtime_1.jsx)("span", { style: {
            padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
            background: s.bg, color: s.color, border: `1px solid ${s.border}`, flexShrink: 0,
        }, children: s.label }));
}
function GroupBadge({ name, active, onClick }) {
    return ((0, jsx_runtime_1.jsxs)("button", { onClick: onClick, title: name, style: {
            padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 600,
            background: active ? 'rgba(56,189,248,0.18)' : 'rgba(56,189,248,0.07)',
            color: active ? '#38bdf8' : 'var(--text-muted)',
            border: `1px solid ${active ? 'rgba(56,189,248,0.5)' : 'rgba(56,189,248,0.2)'}`,
            cursor: 'pointer', whiteSpace: 'nowrap', maxWidth: 180,
            overflow: 'hidden', textOverflow: 'ellipsis',
            transition: 'all 0.15s',
        }, children: [active ? '✕ ' : '', name] }));
}
function fmt(ts) {
    if (!ts)
        return '—';
    return new Date(ts).toLocaleString([], {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
    });
}
// ── Main component ────────────────────────────────────────────────────────────
function BreaksList() {
    const navigate = (0, react_router_dom_1.useNavigate)();
    // ── Filter state ─────────────────────────────────────────────────────────
    const [page, setPage] = (0, react_1.useState)(1);
    const [statusFilter, setStatusFilter] = (0, react_1.useState)('');
    const [projectFilter, setProjectFilter] = (0, react_1.useState)('');
    const [groupFilter, setGroupFilter] = (0, react_1.useState)(''); // error_group_id
    const [fromDate, setFromDate] = (0, react_1.useState)('');
    const [toDate, setToDate] = (0, react_1.useState)('');
    const [appliedFrom, setAppliedFrom] = (0, react_1.useState)('');
    const [appliedTo, setAppliedTo] = (0, react_1.useState)('');
    // ── Remote data ───────────────────────────────────────────────────────────
    const [result, setResult] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [loadError, setLoadError] = (0, react_1.useState)(null);
    const [retryTick, setRetryTick] = (0, react_1.useState)(0);
    // ── Semantic groups ───────────────────────────────────────────────────────
    const [semanticGroups, setSemanticGroups] = (0, react_1.useState)([]);
    const [groupsLoading, setGroupsLoading] = (0, react_1.useState)(false);
    const [showGroupPanel, setShowGroupPanel] = (0, react_1.useState)(false);
    // ── Projects list (for filter dropdown) ──────────────────────────────────
    const [projects, setProjects] = (0, react_1.useState)([]);
    // ── Fetch project list ────────────────────────────────────────────────────
    (0, react_1.useEffect)(() => {
        (0, api_1.apiFetch)('/api/projects')
            .then(r => r.json())
            .then((rows) => setProjects(rows.map(r => r.name).sort()))
            .catch(e => console.error('[Breaks] failed to load project list:', e));
    }, []);
    // ── Fetch semantic groups ─────────────────────────────────────────────────
    (0, react_1.useEffect)(() => {
        if (!showGroupPanel)
            return;
        setGroupsLoading(true);
        const qs = projectFilter ? `?project_name=${encodeURIComponent(projectFilter)}` : '';
        (0, api_1.apiFetch)(`/api/error-groups${qs}`)
            .then(r => r.json())
            .then(d => setSemanticGroups((d.groups ?? [])))
            .catch(e => console.error('[Breaks] failed to load semantic groups:', e))
            .finally(() => setGroupsLoading(false));
    }, [showGroupPanel, projectFilter]);
    // ── Fetch breaks ──────────────────────────────────────────────────────────
    (0, react_1.useEffect)(() => {
        let cancelled = false;
        setLoading(true);
        setLoadError(null);
        const params = new URLSearchParams({
            page: String(page),
            limit: String(LIMIT),
            ...(statusFilter ? { status: statusFilter } : {}),
            ...(projectFilter ? { project: projectFilter } : {}),
            ...(groupFilter ? { semantic_group: groupFilter } : {}),
            ...(appliedFrom ? { from: appliedFrom } : {}),
            ...(appliedTo ? { to: appliedTo } : {}),
        });
        (0, api_1.apiFetch)(`/api/breaks/grouped?${params}`)
            .then(r => r.json())
            .then(d => {
            if (!cancelled) {
                if (d.error && !d.data)
                    setLoadError(`Failed to load grouped breaks: ${d.error}`);
                else
                    setResult(d);
                setLoading(false);
            }
        })
            .catch(e => {
            if (!cancelled) {
                console.error('[Breaks] grouped fetch failed:', e);
                setLoadError('Unable to load grouped breaks. Please try again.');
                setLoading(false);
            }
        });
        return () => { cancelled = true; };
    }, [page, statusFilter, projectFilter, groupFilter, appliedFrom, appliedTo, retryTick]);
    const totalPages = result ? Math.ceil(result.total / LIMIT) : 1;
    function applyDateFilter() {
        setAppliedFrom(fromDate ? `${fromDate}T00:00:00Z` : '');
        setAppliedTo(toDate ? `${toDate}T23:59:59Z` : '');
        setPage(1);
    }
    function clearDateFilter() {
        setFromDate('');
        setToDate('');
        setAppliedFrom('');
        setAppliedTo('');
        setPage(1);
    }
    // Active group label for display
    const activeGroup = semanticGroups.find(g => g.error_group_id === groupFilter);
    const activeGroupLabel = activeGroup?.error_group_name || groupFilter;
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "breaks-list", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 24 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Breaks" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Grouped error occurrences across all projects \u2014 New vs Existing" })] }), (0, jsx_runtime_1.jsxs)("div", { "data-testid": "breaks-filters", style: {
                    display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap',
                    padding: '12px 14px',
                    background: 'var(--surface)', border: '1px solid var(--card-border)', borderRadius: 8,
                    alignItems: 'center',
                }, children: [(0, jsx_runtime_1.jsxs)("select", { value: projectFilter, onChange: e => { setProjectFilter(e.target.value); setPage(1); }, "aria-label": "Project", style: selectStyle, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All Projects" }), projects.map(p => (0, jsx_runtime_1.jsx)("option", { value: p, children: p }, p))] }), (0, jsx_runtime_1.jsxs)("select", { "data-testid": "filter-status", value: statusFilter, onChange: e => { setStatusFilter(e.target.value); setPage(1); }, "aria-label": "Status", style: selectStyle, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All Statuses" }), (0, jsx_runtime_1.jsx)("option", { value: "new", children: "New" }), (0, jsx_runtime_1.jsx)("option", { value: "existing", children: "Existing" }), (0, jsx_runtime_1.jsx)("option", { value: "regression", children: "Regression" })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => setShowGroupPanel(p => !p), title: "Filter by AI semantic error group", style: {
                            padding: '7px 12px', borderRadius: 6, fontSize: 13, fontWeight: 600,
                            background: (showGroupPanel || groupFilter) ? 'rgba(56,189,248,0.15)' : 'var(--input-bg)',
                            color: (showGroupPanel || groupFilter) ? '#38bdf8' : 'var(--text-muted)',
                            border: `1px solid ${(showGroupPanel || groupFilter) ? 'rgba(56,189,248,0.4)' : 'var(--input-border)'}`,
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                        }, children: ["\uD83E\uDDE0 ", groupFilter ? `Group: ${activeGroupLabel.slice(0, 22)}${activeGroupLabel.length > 22 ? '…' : ''}` : 'Semantic Group', groupFilter && ((0, jsx_runtime_1.jsx)("span", { onClick: e => { e.stopPropagation(); setGroupFilter(''); setPage(1); }, style: { marginLeft: 4, opacity: 0.7, fontWeight: 700 }, children: "\u2715" }))] }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }, children: "From:" }), (0, jsx_runtime_1.jsx)("input", { type: "date", value: fromDate, onChange: e => setFromDate(e.target.value), style: inputStyle }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: "To:" }), (0, jsx_runtime_1.jsx)("input", { type: "date", value: toDate, onChange: e => setToDate(e.target.value), style: inputStyle }), (0, jsx_runtime_1.jsx)("button", { onClick: applyDateFilter, style: {
                            padding: '7px 16px', borderRadius: 6, fontSize: 13, fontWeight: 600,
                            background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer',
                        }, children: "Apply" }), (appliedFrom || appliedTo) && ((0, jsx_runtime_1.jsx)("button", { onClick: clearDateFilter, style: {
                            padding: '7px 12px', borderRadius: 6, fontSize: 13,
                            background: 'transparent', color: 'var(--text-muted)',
                            border: '1px solid var(--card-border)', cursor: 'pointer',
                        }, children: "Clear" })), result && ((0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }, children: [result.total, " break", result.total !== 1 ? 's' : '', " found"] }))] }), showGroupPanel && ((0, jsx_runtime_1.jsxs)("div", { style: {
                    padding: '12px 14px', marginBottom: 10,
                    background: 'var(--surface)', border: '1px solid rgba(56,189,248,0.2)',
                    borderRadius: 8,
                }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                            fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                            letterSpacing: '0.07em', color: '#38bdf8', marginBottom: 8,
                        }, children: ["\uD83E\uDDE0 Semantic Error Groups", (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8, textTransform: 'none' }, children: "\u2014 AI-classified root causes, cross-project" })] }), groupsLoading ? ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: "Loading groups\u2026" })) : semanticGroups.length === 0 ? ((0, jsx_runtime_1.jsxs)("div", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: ["No groups yet. Errors are classified automatically after each ingest, or run", (0, jsx_runtime_1.jsx)("code", { style: { marginLeft: 4, padding: '1px 5px', borderRadius: 3, background: 'rgba(255,255,255,0.06)' }, children: "POST /api/error-groups/backfill" }), " to classify existing errors."] })) : ((0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 6 }, children: semanticGroups.map(g => ((0, jsx_runtime_1.jsx)(GroupBadge, { name: `${g.error_group_name || 'Unnamed'} (${g.occurrence_count})`, active: groupFilter === g.error_group_id, onClick: () => {
                                setGroupFilter(prev => prev === g.error_group_id ? '' : g.error_group_id);
                                setPage(1);
                            } }, g.error_group_id))) }))] })), loading ? ((0, jsx_runtime_1.jsx)("div", { "data-testid": "breaks-loading", style: { padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading\u2026" })) : loadError ? ((0, jsx_runtime_1.jsxs)("div", { style: {
                    padding: '24px 20px', borderRadius: 8, fontSize: 13, textAlign: 'center',
                    background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                    color: '#f87171',
                }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 12 }, children: ["\u26A0 ", loadError] }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setRetryTick(t => t + 1), style: {
                            padding: '6px 16px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                            background: 'rgba(239,68,68,0.15)', color: '#f87171',
                            border: '1px solid rgba(239,68,68,0.3)', cursor: 'pointer',
                        }, children: "Retry" })] })) : ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("div", { style: { background: 'var(--surface)', border: '1px solid var(--card-border)', borderRadius: 8, overflow: 'hidden' }, children: (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse', fontSize: 13 }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsx)("tr", { style: { background: 'var(--input-bg)' }, children: ['Project', 'Error Message', 'Group', 'Occurrences', 'First Seen', 'Last Seen', 'Status'].map(h => ((0, jsx_runtime_1.jsx)("th", { style: {
                                                padding: '10px 16px', textAlign: 'left', fontWeight: 600,
                                                color: 'var(--text-muted)', borderBottom: '1px solid var(--card-border)',
                                                fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, whiteSpace: 'nowrap',
                                            }, children: h }, h))) }) }), (0, jsx_runtime_1.jsx)("tbody", { children: (result?.data ?? []).length === 0 ? ((0, jsx_runtime_1.jsx)("tr", { children: (0, jsx_runtime_1.jsx)("td", { colSpan: 7, style: { padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }, children: "No breaks found" }) })) : (result?.data ?? []).map((b, i) => ((0, jsx_runtime_1.jsxs)("tr", { "data-testid": "break-item", "data-status": b.status, onClick: () => navigate(`/breaks/${b.error_hash}?project_name=${encodeURIComponent(b.project_name)}`, {
                                            state: {
                                                project: b.project_name,
                                                file_name: null,
                                                error: b.error_message,
                                                error_hash: b.error_hash,
                                                error_detail: null,
                                                timestamp: b.first_seen,
                                                representative_id: b.representative_id ?? null,
                                            },
                                        }), style: {
                                            borderBottom: '1px solid var(--card-border)',
                                            background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                                            cursor: 'pointer',
                                        }, children: [(0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', whiteSpace: 'nowrap' }, children: (0, jsx_runtime_1.jsx)("span", { style: {
                                                        fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                                                        background: '#6366f120', color: '#818cf8',
                                                    }, children: b.project_name }) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', color: '#f87171', fontFamily: 'ui-monospace, monospace', fontSize: 12, maxWidth: 300, wordBreak: 'break-word' }, children: b.error_message }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', maxWidth: 180 }, children: b.error_group_name ? ((0, jsx_runtime_1.jsx)("button", { onClick: e => {
                                                        e.stopPropagation();
                                                        setGroupFilter(prev => prev === b.error_group_id ? '' : b.error_group_id);
                                                        setShowGroupPanel(true);
                                                        setPage(1);
                                                    }, title: `Filter by group: ${b.error_group_name}`, style: {
                                                        padding: '2px 8px', borderRadius: 99, fontSize: 11, fontWeight: 600,
                                                        background: groupFilter === b.error_group_id ? 'rgba(56,189,248,0.2)' : 'rgba(56,189,248,0.07)',
                                                        color: '#38bdf8',
                                                        border: '1px solid rgba(56,189,248,0.25)',
                                                        cursor: 'pointer', whiteSpace: 'nowrap',
                                                        maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis',
                                                        display: 'block',
                                                    }, children: b.error_group_name })) : ((0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }, children: "\u2014" })) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', textAlign: 'center' }, children: (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 700, fontSize: 13, color: b.occurrence_count > 1 ? '#fbbf24' : '#818cf8' }, children: b.occurrence_count }), b.representative_occurrence_number != null && ((0, jsx_runtime_1.jsxs)("span", { style: {
                                                                fontSize: 11, fontWeight: 700, color: 'var(--text)',
                                                                background: 'rgba(99,102,241,0.12)', padding: '4px 8px', borderRadius: 999,
                                                                border: '1px solid rgba(99,102,241,0.18)'
                                                            }, children: ["#", b.representative_occurrence_number] }))] }) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', color: 'var(--text-muted)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 11 }, children: fmt(b.first_seen) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px', color: 'var(--text-muted)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 11 }, children: b.status === 'new' ? (0, jsx_runtime_1.jsx)("span", { style: { color: '#475569' }, children: "\u2014" }) : fmt(b.last_seen) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '11px 16px' }, children: (0, jsx_runtime_1.jsx)(StatusBadge, { status: b.status }) })] }, i))) })] }) }), (0, jsx_runtime_1.jsxs)("div", { "data-testid": "pagination", style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, marginTop: 20 }, children: [(0, jsx_runtime_1.jsx)("button", { "data-testid": "prev-page", disabled: page <= 1, onClick: () => setPage(p => p - 1), style: {
                                    padding: '7px 16px', background: 'var(--surface)',
                                    border: '1px solid var(--card-border)', borderRadius: 6,
                                    color: page <= 1 ? 'var(--text-muted)' : 'var(--text)',
                                    cursor: page <= 1 ? 'not-allowed' : 'pointer', fontSize: 13, opacity: page <= 1 ? 0.5 : 1,
                                }, children: "\u2190 Previous" }), (0, jsx_runtime_1.jsxs)("span", { "data-testid": "page-info", style: { fontSize: 13, color: 'var(--text-muted)' }, children: ["Page ", page, " of ", totalPages] }), (0, jsx_runtime_1.jsx)("button", { "data-testid": "next-page", disabled: page >= totalPages, onClick: () => setPage(p => p + 1), style: {
                                    padding: '7px 16px', background: 'var(--surface)',
                                    border: '1px solid var(--card-border)', borderRadius: 6,
                                    color: page >= totalPages ? 'var(--text-muted)' : 'var(--text)',
                                    cursor: page >= totalPages ? 'not-allowed' : 'pointer', fontSize: 13, opacity: page >= totalPages ? 0.5 : 1,
                                }, children: "Next \u2192" })] })] }))] }));
}
//# sourceMappingURL=BreaksList.js.map