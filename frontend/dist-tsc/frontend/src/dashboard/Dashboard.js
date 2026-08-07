"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeSemanticGroupName = normalizeSemanticGroupName;
exports.summarizeSemanticGroupsForToday = summarizeSemanticGroupsForToday;
exports.Dashboard = Dashboard;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const react_router_dom_1 = require("react-router-dom");
const recharts_1 = require("recharts");
const api_1 = require("../lib/api");
const ErrorDetailModal_1 = require("../components/ErrorDetailModal");
function ProjectDrillDownModal({ projectName, comparisonPeriod, customFrom, customTo, onClose }) {
    const [logs, setLogs] = (0, react_1.useState)([]);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [stats, setStats] = (0, react_1.useState)({ total: 0, errors: 0, success: 0 });
    const navigate = (0, react_router_dom_1.useNavigate)();
    (0, react_1.useEffect)(() => {
        const { from, to } = periodToRange(comparisonPeriod, customFrom, customTo);
        setLoading(true);
        const params = new URLSearchParams();
        if (from)
            params.set('from', from);
        if (to)
            params.set('to', to);
        params.set('limit', '100');
        const qs = params.toString();
        (0, api_1.apiFetch)(`/api/projects/${encodeURIComponent(projectName)}/logs${qs ? `?${qs}` : ''}`)
            .then(r => r.json())
            .then((data) => {
            const rawLogs = data.logs || [];
            setStats({
                total: data.total || 0,
                errors: data.failure || 0,
                success: data.success || 0,
            });
            // Convert to ErrorRow format
            const errorRows = rawLogs.map((log) => ({
                project: projectName,
                file_name: log.file_name,
                error: log.error || '',
                error_detail: log.error_detail,
                timestamp: log.timestamp,
            }));
            setLogs(errorRows);
        })
            .catch((e) => {
            console.error('[DrillDown] failed:', e);
        })
            .finally(() => setLoading(false));
    }, [projectName, comparisonPeriod, customFrom, customTo]);
    return ((0, jsx_runtime_1.jsx)("div", { style: {
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
            padding: 20,
        }, onClick: onClose, children: (0, jsx_runtime_1.jsxs)("div", { style: {
                background: 'var(--card-bg)', borderRadius: 12, padding: 24,
                maxWidth: 1200, width: '100%', maxHeight: '90vh', overflow: 'auto',
                border: '1px solid var(--card-border)',
            }, onClick: e => e.stopPropagation(), children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }, children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 20, fontWeight: 700, marginBottom: 8 }, children: projectName }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 16, fontSize: 13, color: 'var(--text-muted)' }, children: [(0, jsx_runtime_1.jsxs)("span", { children: ["Total: ", (0, jsx_runtime_1.jsx)("strong", { style: { color: 'var(--text)' }, children: stats.total })] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Errors: ", (0, jsx_runtime_1.jsx)("strong", { style: { color: '#f87171' }, children: stats.errors })] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Success: ", (0, jsx_runtime_1.jsx)("strong", { style: { color: '#4ade80' }, children: stats.success })] })] })] }), (0, jsx_runtime_1.jsx)("button", { onClick: onClose, style: {
                                background: 'transparent', border: 'none', fontSize: 24,
                                color: 'var(--text-muted)', cursor: 'pointer', padding: 8,
                            }, children: "\u2715" })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 12, marginBottom: 20 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => navigate(`/logs?project=${encodeURIComponent(projectName)}`), style: {
                                padding: '8px 16px', borderRadius: 6, fontSize: 13, fontWeight: 600,
                                background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer',
                            }, children: "View Full Logs" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => navigate(`/logs?project=${encodeURIComponent(projectName)}&status=errors`), style: {
                                padding: '8px 16px', borderRadius: 6, fontSize: 13, fontWeight: 600,
                                background: 'rgba(239,68,68,0.15)', color: '#f87171',
                                border: '1px solid rgba(239,68,68,0.3)', cursor: 'pointer',
                            }, children: "View Errors Only" })] }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }, children: "Loading..." })) : ((0, jsx_runtime_1.jsx)(ErrorTable, { rows: logs, emptyMsg: `No logs found for ${projectName} in the selected time period.` }))] }) }));
}
function periodToRange(period, customFrom, customTo) {
    const now = new Date();
    if (period === 'daily') {
        const start = new Date(now);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: now.toISOString() };
    }
    if (period === 'weekly') {
        const start = new Date(now);
        start.setDate(start.getDate() - 7);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: now.toISOString() };
    }
    // custom
    const from = customFrom ? `${customFrom}T00:00:00+00:00` : '';
    const to = customTo ? `${customTo}T23:59:59+00:00` : '';
    return { from, to };
}
function normalizeSemanticGroupName(row) {
    const explicit = (row.error_group_name ?? '').trim();
    if (explicit)
        return explicit;
    const error = (row.error ?? '').trim();
    if (!error)
        return 'Uncategorized';
    const patterns = [
        { regex: /(LLM output was not valid JSON|JSONDecodeError|json\.loads|invalid JSON|malformed JSON|JSON parse|valid JSON)/i, label: 'JSON format error' },
        { regex: /(np\.int|has no attribute ['"]int['"]|deprecated alias for the builtin `int`|numpy.*int)/i, label: 'Deprecated attribute usage.' },
        { regex: /(No such file or directory|file not found|No such file)/i, label: 'File not found' },
        { regex: /(has no attribute|object has no attribute|Attribute not found)/i, label: 'Attribute not found.' },
        { regex: /(is not defined|Undefined variable)/i, label: 'Undefined variable error' },
        { regex: /(Buffer size limit|buffer.*limit|too large)/i, label: 'Buffer size limit.' },
        { regex: /(Access denied|permission denied)/i, label: 'Access denied error' },
        { regex: /(Credentials not found|missing.*credentials|No credentials)/i, label: 'Credentials not found' },
    ];
    const match = patterns.find((p) => p.regex.test(error));
    if (match)
        return match.label;
    return error.length > 90 ? `${error.slice(0, 87)}…` : error;
}
function summarizeSemanticGroupsForToday(rows, selectedProject) {
    const counts = new Map();
    rows.forEach((row) => {
        const projectName = row.project ?? '';
        if (selectedProject && projectName && projectName !== selectedProject) {
            return;
        }
        const name = normalizeSemanticGroupName(row);
        const existing = counts.get(name) ?? { id: row.error_group_id || undefined, name, value: 0 };
        existing.value += 1;
        if (!existing.id && row.error_group_id)
            existing.id = row.error_group_id;
        counts.set(name, existing);
    });
    return Array.from(counts.values())
        .map(({ id, name, value }) => ({ id, name, value }))
        .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));
}
const card = {
    background: 'var(--card-bg)',
    border: 'none',
    borderRadius: 10,
    padding: 20,
};
const cardTitle = {
    margin: '0 0 14px',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-muted)',
    textTransform: 'uppercase',
    letterSpacing: 1,
};
const selectStyle = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 6,
    color: 'var(--text)',
    padding: '6px 8px',
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
};
function fmt(ts) {
    if (!ts)
        return '—';
    return new Date(ts).toLocaleString([], {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
    });
}
function ErrorTable({ rows, emptyMsg }) {
    const [filterProject, setFilterProject] = (0, react_1.useState)('');
    const [selectedRow, setSelectedRow] = (0, react_1.useState)(null);
    const [hoveredIdx, setHoveredIdx] = (0, react_1.useState)(null);
    const HIDDEN_PROJECTS = new Set(['document similarity matcher', 'lat', 'ai services']);
    const visibleRows = rows.filter(e => !HIDDEN_PROJECTS.has(e.project.toLowerCase()));
    const projects = Array.from(new Set(visibleRows.map(e => e.project))).sort();
    const filtered = filterProject ? visibleRows.filter(e => e.project === filterProject) : visibleRows;
    if (visibleRows.length === 0) {
        return ((0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 28, marginBottom: 10 }, children: "\u2705" }), emptyMsg] }));
    }
    return ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 10 }, children: [(0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: [filtered.length, " error", filtered.length !== 1 ? 's' : ''] }), (0, jsx_runtime_1.jsxs)("select", { value: filterProject, onChange: e => setFilterProject(e.target.value), style: { ...selectStyle, minWidth: 200 }, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All Projects" }), projects.map(p => (0, jsx_runtime_1.jsx)("option", { value: p, children: p }, p))] })] }), (0, jsx_runtime_1.jsx)("div", { style: { overflowX: 'auto' }, children: (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse', fontSize: 13 }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsx)("tr", { style: { background: 'var(--input-bg)' }, children: ['Project', 'File', 'Error', 'Timestamp'].map(h => ((0, jsx_runtime_1.jsx)("th", { style: {
                                        padding: '9px 14px', textAlign: 'left', fontWeight: 600,
                                        color: 'var(--text-muted)', borderBottom: '1px solid var(--card-border)',
                                        whiteSpace: 'nowrap', fontSize: 12,
                                    }, children: h }, h))) }) }), (0, jsx_runtime_1.jsx)("tbody", { children: filtered.map((row, i) => ((0, jsx_runtime_1.jsxs)("tr", { onClick: () => setSelectedRow(row), onMouseEnter: () => setHoveredIdx(i), onMouseLeave: () => setHoveredIdx(null), title: "Click to view full error detail", style: {
                                    borderBottom: '1px solid var(--card-border)',
                                    background: hoveredIdx === i
                                        ? 'rgba(99,102,241,0.07)'
                                        : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s',
                                }, children: [(0, jsx_runtime_1.jsx)("td", { style: { padding: '9px 14px', whiteSpace: 'nowrap' }, children: (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#6366f120', color: '#818cf8' }, children: row.project }) }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '9px 14px', color: 'var(--text)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 12 }, children: row.file_name ?? '—' }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '9px 14px', color: hoveredIdx === i ? '#fca5a5' : '#f87171', maxWidth: 320, wordBreak: 'break-word', transition: 'color 0.15s' }, children: row.error }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '9px 14px', color: 'var(--text-muted)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 11 }, children: fmt(row.timestamp) })] }, i))) })] }) }), selectedRow && (0, jsx_runtime_1.jsx)(ErrorDetailModal_1.ErrorDetailModal, { row: selectedRow, onClose: () => setSelectedRow(null) })] }));
}
function Dashboard() {
    const navigate = (0, react_router_dom_1.useNavigate)();
    // ── Project drill-down modal state ─────────────────────────────────────────
    const [drillDownProject, setDrillDownProject] = (0, react_1.useState)(null);
    // ── Project Comparison period toggle ──
    const [comparisonPeriod, setComparisonPeriod] = (0, react_1.useState)('daily');
    const [customFrom, setCustomFrom] = (0, react_1.useState)('');
    const [customTo, setCustomTo] = (0, react_1.useState)('');
    // Only used to trigger a refetch once "Apply" is clicked for the custom range
    const [customApplyTick, setCustomApplyTick] = (0, react_1.useState)(0);
    // ── Which series are shown on the Project Comparison chart (click legend to isolate one) ──
    const [visibleSeries, setVisibleSeries] = (0, react_1.useState)({
        mostUsed: true,
        errorProducing: true,
    });
    // ── Drill-down state for selected project ──
    const [selectedProject, setSelectedProject] = (0, react_1.useState)(null);
    const [projectErrors, setProjectErrors] = (0, react_1.useState)([]);
    const [projectErrorsLoading, setProjectErrorsLoading] = (0, react_1.useState)(false);
    function toggleSeries(series) {
        setVisibleSeries((prev) => {
            const otherSeries = series === 'mostUsed' ? 'errorProducing' : 'mostUsed';
            // If both are currently visible (or only the other one is), clicking isolates this series.
            // If this series is already isolated (only one visible and it's this one), clicking restores both.
            const isolated = prev[series] && !prev[otherSeries];
            if (isolated) {
                return { mostUsed: true, errorProducing: true };
            }
            return { ...prev, [series]: true, [otherSeries]: false };
        });
    }
    // ── Top 10 projects ──
    const [topProjects, setTopProjects] = (0, react_1.useState)([]);
    const [topLoading, setTopLoading] = (0, react_1.useState)(true);
    const [topError, setTopError] = (0, react_1.useState)(null);
    // ── Top 10 error projects ──
    const [topErrorProjects, setTopErrorProjects] = (0, react_1.useState)([]);
    const [topErrorLoading, setTopErrorLoading] = (0, react_1.useState)(true);
    const [topErrorProjectsError, setTopErrorProjectsError] = (0, react_1.useState)(null);
    const fetchTopProjects = (0, react_1.useCallback)((from, to) => {
        const params = new URLSearchParams();
        if (from)
            params.set('from', from);
        if (to)
            params.set('to', to);
        const qs = params.toString();
        setTopLoading(true);
        setTopError(null);
        (0, api_1.apiFetch)(`/api/dashboard/top-projects${qs ? `?${qs}` : ''}`)
            .then(r => r.json())
            .then((d) => setTopProjects(d.projects ?? []))
            .catch((e) => {
            console.error('[Dashboard] top-projects failed:', e);
            setTopError('Failed to load top projects.');
        })
            .finally(() => setTopLoading(false));
    }, []);
    const fetchTopErrorProjects = (0, react_1.useCallback)((from, to) => {
        const params = new URLSearchParams();
        if (from)
            params.set('from', from);
        if (to)
            params.set('to', to);
        const qs = params.toString();
        setTopErrorLoading(true);
        setTopErrorProjectsError(null);
        (0, api_1.apiFetch)(`/api/dashboard/top-error-projects${qs ? `?${qs}` : ''}`)
            .then(r => r.json())
            .then((d) => setTopErrorProjects(d.projects ?? []))
            .catch((e) => {
            console.error('[Dashboard] top-error-projects failed:', e);
            setTopErrorProjectsError('Failed to load error-producing projects.');
        })
            .finally(() => setTopErrorLoading(false));
    }, []);
    (0, react_1.useEffect)(() => {
        // For custom, wait until "Apply" is clicked (customApplyTick changes) and a from/to is set.
        if (comparisonPeriod === 'custom' && !(customFrom && customTo))
            return;
        const { from, to } = periodToRange(comparisonPeriod, customFrom, customTo);
        fetchTopProjects(from, to);
        fetchTopErrorProjects(from, to);
        if (comparisonPeriod === 'custom')
            return; // no polling for a fixed custom range
        const interval = setInterval(() => {
            const r = periodToRange(comparisonPeriod, customFrom, customTo);
            fetchTopProjects(r.from, r.to);
            fetchTopErrorProjects(r.from, r.to);
        }, 3600000);
        return () => clearInterval(interval);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [comparisonPeriod, customApplyTick, fetchTopProjects, fetchTopErrorProjects]);
    // ── Today's errors ──
    const [todayErrors, setTodayErrors] = (0, react_1.useState)([]);
    const [todayLoading, setTodayLoading] = (0, react_1.useState)(true);
    const [todayDate, setTodayDate] = (0, react_1.useState)('');
    const [todayError, setTodayError] = (0, react_1.useState)(null);
    (0, react_1.useEffect)(() => {
        setTodayError(null);
        (0, api_1.apiFetch)('/api/dashboard/today-errors')
            .then(r => r.json())
            .then((d) => { setTodayErrors(d.errors ?? []); setTodayDate(d.date ?? ''); })
            .catch((e) => {
            console.error('[Dashboard] today-errors failed:', e);
            setTodayError("Failed to load today's errors.");
        })
            .finally(() => setTodayLoading(false));
    }, []);
    // ── Project Comparison data (merge topProjects + topErrorProjects) ──
    const comparisonData = (0, react_1.useMemo)(() => {
        const map = new Map();
        topProjects.forEach((p) => {
            const key = p.project_name;
            if (!map.has(key))
                map.set(key, { name: key, mostUsed: 0, errorProducing: 0 });
            map.get(key).mostUsed = Number(p.total);
        });
        topErrorProjects.forEach((p) => {
            const key = p.project_name;
            if (!map.has(key))
                map.set(key, { name: key, mostUsed: 0, errorProducing: 0 });
            map.get(key).errorProducing = Number(p.total);
        });
        return Array.from(map.values())
            .sort((a, b) => (b.mostUsed + b.errorProducing) - (a.mostUsed + a.errorProducing))
            .slice(0, 15)
            .map((d) => ({
            ...d,
            shortName: d.name.length > 16 ? d.name.slice(0, 15) + '…' : d.name,
        }));
    }, [topProjects, topErrorProjects]);
    const semanticGroupData = (0, react_1.useMemo)(() => summarizeSemanticGroupsForToday(todayErrors, selectedProject), [todayErrors, selectedProject]);
    // ── Semantic groups for selected project (drill-down) ──
    const projectSemanticGroupData = (0, react_1.useMemo)(() => selectedProject ? summarizeSemanticGroupsForToday(projectErrors, selectedProject) : [], [selectedProject, projectErrors]);
    const displayedSemanticGroups = selectedProject ? projectSemanticGroupData : semanticGroupData;
    function formatPeriodLabel(period, customFromValue, customToValue) {
        if (period === 'daily') {
            return 'Today';
        }
        if (period === 'weekly') {
            return 'Last 7 days';
        }
        if (customFromValue && customToValue) {
            const fromDate = new Date(customFromValue);
            const toDate = new Date(customToValue);
            const options = { year: 'numeric', month: 'short', day: 'numeric' };
            return `${fromDate.toLocaleDateString(undefined, options)} – ${toDate.toLocaleDateString(undefined, options)}`;
        }
        return 'Custom range';
    }
    const semanticGroupLabel = selectedProject
        ? formatPeriodLabel(comparisonPeriod, customFrom, customTo)
        : todayDate;
    // ── Fetch errors for selected project ──
    (0, react_1.useEffect)(() => {
        if (!selectedProject) {
            setProjectErrors([]);
            return;
        }
        const { from, to } = periodToRange(comparisonPeriod, customFrom, customTo);
        const params = new URLSearchParams();
        params.set('project', selectedProject);
        if (from)
            params.set('from', from);
        if (to)
            params.set('to', to);
        setProjectErrorsLoading(true);
        (0, api_1.apiFetch)(`/api/dashboard/project-errors?${params.toString()}`)
            .then(r => r.json())
            .then((d) => setProjectErrors(d.errors ?? []))
            .catch((e) => {
            console.error('[Dashboard] project-errors failed:', e);
            setProjectErrors([]);
        })
            .finally(() => setProjectErrorsLoading(false));
    }, [selectedProject, comparisonPeriod, customFrom, customTo, customApplyTick]);
    // ── When both series are visible, drill into the project summary; when only the
    //    error-producing series is filtered, send the user to the breaks list scoped to that project.
    const handleBarClick = (0, react_1.useCallback)((data) => {
        const payload = data?.activePayload?.[0]?.payload ?? data?.payload ?? data;
        const projectName = payload?.name;
        if (!projectName)
            return;
        if (visibleSeries.errorProducing && !visibleSeries.mostUsed) {
            navigate(`/breaks?project=${encodeURIComponent(projectName)}`);
            return;
        }
        setSelectedProject(prev => prev === projectName ? null : projectName);
    }, [navigate, visibleSeries]);
    const handleSemanticGroupClick = (0, react_1.useCallback)((item) => {
        if (!item?.name)
            return;
        const project = selectedProject || '';
        const params = new URLSearchParams();
        if (project)
            params.set('project', project);
        if (item.id)
            params.set('semantic_group', item.id);
        const qs = params.toString();
        navigate(`/breaks${qs ? `?${qs}` : ''}`);
    }, [navigate, selectedProject]);
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 24 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Dashboard" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Live error monitoring across all projects" })] }), (0, jsx_runtime_1.jsxs)("div", { style: { ...card, marginBottom: 24 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4, flexWrap: 'wrap', gap: 10 }, children: [(0, jsx_runtime_1.jsx)("h3", { style: { ...cardTitle, margin: 0 }, children: "Project Comparison" }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 16, alignItems: 'center' }, children: [(0, jsx_runtime_1.jsxs)("button", { onClick: () => toggleSeries('mostUsed'), title: "Click to isolate Most used, click again to show both", style: {
                                            display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
                                            color: visibleSeries.mostUsed ? 'var(--text-muted)' : 'rgba(255,255,255,0.25)',
                                            background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
                                            opacity: visibleSeries.mostUsed ? 1 : 0.5, transition: 'opacity 0.15s, color 0.15s',
                                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { width: 12, height: 12, borderRadius: 2, background: '#7c6ff7', flexShrink: 0, opacity: visibleSeries.mostUsed ? 1 : 0.35 } }), "Most used"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => toggleSeries('errorProducing'), title: "Click to isolate Error producing, click again to show both", style: {
                                            display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
                                            color: visibleSeries.errorProducing ? 'var(--text-muted)' : 'rgba(255,255,255,0.25)',
                                            background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
                                            opacity: visibleSeries.errorProducing ? 1 : 0.5, transition: 'opacity 0.15s, color 0.15s',
                                        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { width: 12, height: 12, borderRadius: 2, background: '#f97316', flexShrink: 0, opacity: visibleSeries.errorProducing ? 1 : 0.35 } }), "Error producing"] })] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 16, justifyContent: 'flex-end' }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                                    display: 'flex', background: 'var(--input-bg)', border: '1px solid var(--input-border)',
                                    borderRadius: 8, padding: 3, gap: 2,
                                }, children: ['daily', 'weekly', 'custom'].map((p) => ((0, jsx_runtime_1.jsx)("button", { onClick: () => setComparisonPeriod(p), style: {
                                        padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                                        border: 'none', cursor: 'pointer', textTransform: 'capitalize',
                                        background: comparisonPeriod === p ? '#6366f1' : 'transparent',
                                        color: comparisonPeriod === p ? '#fff' : 'var(--text-muted)',
                                        transition: 'background 0.15s, color 0.15s',
                                    }, children: p }, p))) }), comparisonPeriod === 'custom' && ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsx)("input", { type: "date", value: customFrom, onChange: e => setCustomFrom(e.target.value), style: { ...selectStyle, colorScheme: 'dark' } }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: "to" }), (0, jsx_runtime_1.jsx)("input", { type: "date", value: customTo, onChange: e => setCustomTo(e.target.value), style: { ...selectStyle, colorScheme: 'dark' } }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setCustomApplyTick(t => t + 1), disabled: !customFrom || !customTo, style: {
                                            padding: '6px 16px', borderRadius: 6, fontSize: 12, fontWeight: 700,
                                            cursor: (!customFrom || !customTo) ? 'not-allowed' : 'pointer',
                                            background: '#6366f1', color: '#fff', border: 'none',
                                            opacity: (!customFrom || !customTo) ? 0.5 : 1,
                                        }, children: "Apply" })] }))] }), topLoading || topErrorLoading ? ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)', fontSize: 13 }, children: "Loading\u2026" })) : (topError || topErrorProjectsError) ? ((0, jsx_runtime_1.jsxs)("div", { style: {
                            padding: '18px 20px', borderRadius: 8, fontSize: 13,
                            background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                            color: '#f87171',
                        }, children: [topError && (0, jsx_runtime_1.jsxs)("div", { children: ["\u26A0 Most used projects \u2014 ", topError] }), topErrorProjectsError && (0, jsx_runtime_1.jsxs)("div", { style: { marginTop: topError ? 6 : 0 }, children: ["\u26A0 Error-producing projects \u2014 ", topErrorProjectsError] })] })) : comparisonData.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)', fontSize: 13 }, children: "No project data available." })) : ((0, jsx_runtime_1.jsx)(recharts_1.ResponsiveContainer, { width: "100%", height: 280, children: (0, jsx_runtime_1.jsxs)(recharts_1.BarChart, { data: comparisonData, margin: { top: 16, right: 16, left: 0, bottom: 60 }, barCategoryGap: "30%", barGap: 3, onClick: handleBarClick, style: { outline: 'none' }, children: [(0, jsx_runtime_1.jsx)(recharts_1.CartesianGrid, { strokeDasharray: "3 3", stroke: "rgba(255,255,255,0.05)", vertical: false }), (0, jsx_runtime_1.jsx)(recharts_1.XAxis, { dataKey: "shortName", tick: { fill: 'rgba(255,255,255,0.45)', fontSize: 10 }, tickLine: false, axisLine: { stroke: 'rgba(255,255,255,0.08)' }, angle: -35, textAnchor: "end", interval: 0 }), (0, jsx_runtime_1.jsx)(recharts_1.YAxis, { tick: { fill: 'rgba(255,255,255,0.3)', fontSize: 10 }, tickLine: false, axisLine: false, width: 28 }), (0, jsx_runtime_1.jsx)(recharts_1.Tooltip, { cursor: { fill: 'rgba(255,255,255,0.04)' }, content: ({ active, payload, label }) => {
                                        if (!active || !payload?.length)
                                            return null;
                                        const full = comparisonData.find((d) => d.shortName === label)?.name ?? label;
                                        const isSelected = full === selectedProject;
                                        return ((0, jsx_runtime_1.jsxs)("div", { style: {
                                                background: '#1e293b', border: '1px solid rgba(255,255,255,0.1)',
                                                borderRadius: 8, padding: '10px 14px', fontSize: 13,
                                            }, children: [(0, jsx_runtime_1.jsx)("div", { style: { color: '#e2e8f0', fontWeight: 700, marginBottom: 8 }, children: full }), payload.map((p) => ((0, jsx_runtime_1.jsxs)("div", { style: { color: '#94a3b8', marginBottom: 3 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { color: p.fill, fontWeight: 700 }, children: "\u25A0 " }), p.dataKey === 'mostUsed' ? 'Most used' : 'Error producing', ":", ' ', (0, jsx_runtime_1.jsx)("span", { style: { color: '#fff', fontWeight: 700 }, children: p.value })] }, p.dataKey))), (0, jsx_runtime_1.jsx)("div", { style: {
                                                        marginTop: 8,
                                                        paddingTop: 8,
                                                        borderTop: '1px solid rgba(255,255,255,0.1)',
                                                        fontSize: 11,
                                                        color: '#94a3b8',
                                                        fontStyle: 'italic'
                                                    }, children: isSelected ? '🔍 Click to collapse' : '🔍 Click to drill down' })] }));
                                    } }), visibleSeries.mostUsed && ((0, jsx_runtime_1.jsx)(recharts_1.Bar, { dataKey: "mostUsed", fill: "#7c6ff7", radius: [4, 4, 0, 0], maxBarSize: 32, cursor: "pointer", fillOpacity: selectedProject ? 0.7 : 1, stroke: "none", strokeWidth: 0, onClick: handleBarClick })), visibleSeries.errorProducing && ((0, jsx_runtime_1.jsx)(recharts_1.Bar, { dataKey: "errorProducing", fill: "#f97316", radius: [4, 4, 0, 0], maxBarSize: 32, cursor: "pointer", fillOpacity: selectedProject ? 0.7 : 1, stroke: "none", strokeWidth: 0, onClick: handleBarClick }))] }) }))] }), (0, jsx_runtime_1.jsxs)("div", { style: { ...card, marginBottom: 24 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 10 }, children: [(0, jsx_runtime_1.jsx)("h3", { style: { ...cardTitle, margin: 0 }, children: selectedProject ? `Today's Errors by Semantic Group for ${selectedProject}` : "Today's Errors by Semantic Group" }), (0, jsx_runtime_1.jsxs)("span", { style: {
                                    fontSize: 12, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
                                    background: 'rgba(56,189,248,0.12)', color: '#7dd3fc',
                                    border: '1px solid rgba(56,189,248,0.25)',
                                }, children: [semanticGroupLabel, " \u00B7 ", displayedSemanticGroups.reduce((sum, item) => sum + item.value, 0), " grouped"] })] }), todayLoading ? ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', padding: '30px 0', color: 'var(--text-muted)', fontSize: 13 }, children: "Loading semantic group totals\u2026" })) : todayError ? ((0, jsx_runtime_1.jsxs)("div", { style: {
                            padding: '18px 20px', borderRadius: 8, fontSize: 13,
                            background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                            color: '#f87171',
                        }, children: ["\u26A0 ", todayError] })) : displayedSemanticGroups.length === 0 ? ((0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', padding: '36px 0', color: 'var(--text-muted)', fontSize: 13 }, children: ["No semantic group data for ", selectedProject ? ` ${selectedProject}` : 'today', "."] })) : ((0, jsx_runtime_1.jsx)(recharts_1.ResponsiveContainer, { width: "100%", height: 280, children: (0, jsx_runtime_1.jsxs)(recharts_1.BarChart, { data: displayedSemanticGroups, margin: { top: 8, right: 18, left: 8, bottom: 40 }, children: [(0, jsx_runtime_1.jsx)(recharts_1.CartesianGrid, { strokeDasharray: "3 3", stroke: "rgba(255,255,255,0.05)", vertical: false }), (0, jsx_runtime_1.jsx)(recharts_1.XAxis, { type: "category", dataKey: "name", tick: { fill: 'rgba(255,255,255,0.55)', fontSize: 10 }, tickLine: false, axisLine: { stroke: 'rgba(255,255,255,0.08)' }, angle: -20, textAnchor: "end", interval: 0 }), (0, jsx_runtime_1.jsx)(recharts_1.YAxis, { type: "number", tick: { fill: 'rgba(255,255,255,0.45)', fontSize: 10 }, tickLine: false, axisLine: { stroke: 'rgba(255,255,255,0.08)' }, width: 32 }), (0, jsx_runtime_1.jsx)(recharts_1.Tooltip, { cursor: { fill: 'rgba(255,255,255,0.04)' }, content: ({ active, payload }) => {
                                        if (!active || !payload?.length)
                                            return null;
                                        const item = payload[0].payload;
                                        return ((0, jsx_runtime_1.jsxs)("div", { style: {
                                                background: '#1e293b', border: '1px solid rgba(255,255,255,0.1)',
                                                borderRadius: 8, padding: '10px 14px', fontSize: 13,
                                            }, children: [(0, jsx_runtime_1.jsx)("div", { style: { color: '#e2e8f0', fontWeight: 700, marginBottom: 6 }, children: item.name }), (0, jsx_runtime_1.jsxs)("div", { style: { color: '#94a3b8' }, children: ["Errors: ", (0, jsx_runtime_1.jsx)("span", { style: { color: '#fff', fontWeight: 700 }, children: item.value })] })] }));
                                    } }), (0, jsx_runtime_1.jsx)(recharts_1.Bar, { dataKey: "value", fill: "#38bdf8", radius: [4, 4, 0, 0], maxBarSize: 32, cursor: "pointer", onClick: (data) => {
                                        const payload = data?.activePayload?.[0]?.payload ?? data?.payload ?? data;
                                        handleSemanticGroupClick(payload);
                                    } })] }) }))] }), (0, jsx_runtime_1.jsxs)("div", { style: { ...card, marginBottom: 24 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }, children: [(0, jsx_runtime_1.jsx)("h3", { style: { ...cardTitle, margin: 0 }, children: "\uD83D\uDCC5 Today's Errors" }), todayDate && ((0, jsx_runtime_1.jsxs)("span", { style: {
                                    fontSize: 12, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
                                    background: 'rgba(239,68,68,0.12)', color: '#f87171',
                                    border: '1px solid rgba(239,68,68,0.25)',
                                }, children: [todayDate, " \u2014 ", todayErrors.length, " error", todayErrors.length !== 1 ? 's' : ''] }))] }), todayLoading ? ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', padding: '30px 0', color: 'var(--text-muted)', fontSize: 13 }, children: "Loading today's errors\u2026" })) : todayError ? ((0, jsx_runtime_1.jsxs)("div", { style: {
                            padding: '18px 20px', borderRadius: 8, fontSize: 13,
                            background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                            color: '#f87171',
                        }, children: ["\u26A0 ", todayError] })) : ((0, jsx_runtime_1.jsx)(ErrorTable, { rows: todayErrors, emptyMsg: "No errors today \u2014 all systems running clean." }))] })] }));
}
//# sourceMappingURL=Dashboard.js.map