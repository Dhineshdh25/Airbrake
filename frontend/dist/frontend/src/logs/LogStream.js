"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LogStream = LogStream;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * AI Services Dashboard — tiles for all projects with category filter and detail modal.
 */
const react_1 = require("react");
const api_1 = require("../lib/api");
const CATEGORIES = ['All', 'Gen AI', 'Computer Vision', 'Traditional Model', 'RAG', 'Analytics'];
const CATEGORY_COLOR = {
    'Gen AI': '#6366f1',
    'Computer Vision': '#10b981',
    'Traditional Model': '#f59e0b',
    'RAG': '#8b5cf6',
    'Analytics': '#3b82f6',
};
const TILE_PALETTE = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];
function tileColor(i) { return TILE_PALETTE[i % TILE_PALETTE.length]; }
// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtTime(ts) {
    if (!ts)
        return '—';
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
}
function fmtDate(ts) {
    if (!ts)
        return '';
    return new Date(ts).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function SummaryCard({ label, value, color, icon }) {
    return ((0, jsx_runtime_1.jsxs)("div", { style: {
            flex: '1 1 auto', minWidth: 90,
            background: `linear-gradient(135deg, ${color}18 0%, ${color}08 100%)`,
            border: `1px solid ${color}30`,
            borderRadius: 12, padding: '14px 16px',
            display: 'flex', flexDirection: 'column', gap: 6,
        }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 18, lineHeight: 1 }, children: icon }), (0, jsx_runtime_1.jsx)("div", { style: {
                    fontSize: 20, fontWeight: 800, color, lineHeight: 1.2,
                    wordBreak: 'break-all', overflowWrap: 'anywhere',
                }, children: value }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#94a3b8', fontWeight: 500 }, children: label })] }));
}
function SuccessBar({ success, total }) {
    const pct = total > 0 ? Math.round((success / total) * 100) : 0;
    const color = pct >= 80 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
    return ((0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 20 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', justifyContent: 'space-between', marginBottom: 6 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, color: '#94a3b8', fontWeight: 600 }, children: "Success Rate" }), (0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, fontWeight: 700, color }, children: [pct, "%"] })] }), (0, jsx_runtime_1.jsx)("div", { style: { height: 6, borderRadius: 99, background: 'rgba(255,255,255,0.07)', overflow: 'hidden' }, children: (0, jsx_runtime_1.jsx)("div", { style: {
                        height: '100%', width: `${pct}%`, borderRadius: 99,
                        background: `linear-gradient(90deg, ${color}, ${color}aa)`,
                        transition: 'width 0.6s ease',
                        boxShadow: `0 0 8px ${color}66`,
                    } }) })] }));
}
function StatusBadge({ isError, isResolved }) {
    const bgColor = isResolved
        ? 'rgba(139,92,246,0.15)'
        : (isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)');
    const textColor = isResolved
        ? '#a78bfa'
        : (isError ? '#f87171' : '#34d399');
    const borderColor = isResolved
        ? 'rgba(139,92,246,0.3)'
        : (isError ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)');
    const label = isResolved ? 'Resolved' : (isError ? 'Failed' : 'Success');
    return ((0, jsx_runtime_1.jsxs)("span", { style: {
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
            background: bgColor,
            color: textColor,
            border: `1px solid ${borderColor}`,
        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 8 }, children: "\u25CF" }), label] }));
}
function FileCard({ row }) {
    const [expanded, setExpanded] = (0, react_1.useState)(false);
    const isError = !!row.error;
    const isResolved = row.isResolved ?? false;
    const hasDetails = row.llm_usage || row.input_tokens || row.output_tokens || row.calculated_cost || row.word_count;
    const borderColor = isResolved
        ? 'rgba(139,92,246,0.25)'
        : (isError ? 'rgba(239,68,68,0.25)' : 'rgba(255,255,255,0.07)');
    const bgColor = isResolved
        ? 'rgba(139,92,246,0.04)'
        : (isError ? 'rgba(239,68,68,0.04)' : 'rgba(255,255,255,0.02)');
    const iconBg = isResolved
        ? 'rgba(139,92,246,0.15)'
        : (isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.12)');
    const icon = isResolved ? '✔️' : (isError ? '📄' : '✅');
    return ((0, jsx_runtime_1.jsxs)("div", { style: {
            borderRadius: 10,
            border: `1px solid ${borderColor}`,
            background: bgColor,
            overflow: 'hidden',
            transition: 'border-color 0.15s',
        }, children: [(0, jsx_runtime_1.jsxs)("div", { onClick: () => hasDetails && setExpanded((v) => !v), style: {
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 14px',
                    cursor: hasDetails ? 'pointer' : 'default',
                }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                            background: iconBg,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 14,
                        }, children: icon }), (0, jsx_runtime_1.jsxs)("div", { style: { flex: 1, minWidth: 0 }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                                    fontSize: 13, fontWeight: 600, color: '#e2e8f0',
                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                }, children: row.file_name ?? 'Unknown file' }), isError && ((0, jsx_runtime_1.jsx)("div", { style: {
                                    fontSize: 11,
                                    color: isResolved ? '#a78bfa' : '#f87171',
                                    marginTop: 2,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                    textDecoration: isResolved ? 'line-through' : 'none',
                                }, children: row.error }))] }), (0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'right', flexShrink: 0 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#64748b', fontFamily: 'ui-monospace, monospace' }, children: fmtTime(row.timestamp) }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 10, color: '#475569' }, children: fmtDate(row.timestamp) })] }), (0, jsx_runtime_1.jsx)("div", { style: { flexShrink: 0 }, children: (0, jsx_runtime_1.jsx)(StatusBadge, { isError: isError, isResolved: isResolved }) }), hasDetails && ((0, jsx_runtime_1.jsx)("div", { style: { color: '#475569', fontSize: 12, flexShrink: 0, transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none' }, children: "\u25BE" }))] }), expanded && hasDetails && ((0, jsx_runtime_1.jsxs)("div", { style: {
                    borderTop: '1px solid rgba(255,255,255,0.06)',
                    padding: '12px 14px',
                    display: 'flex', flexWrap: 'wrap', gap: 10,
                    background: 'rgba(0,0,0,0.15)',
                }, children: [row.input_tokens != null && (0, jsx_runtime_1.jsx)(DetailChip, { label: "Input Tokens", value: String(row.input_tokens), color: "#3b82f6" }), row.output_tokens != null && (0, jsx_runtime_1.jsx)(DetailChip, { label: "Output Tokens", value: String(row.output_tokens), color: "#6366f1" }), row.calculated_cost && (0, jsx_runtime_1.jsx)(DetailChip, { label: "Cost", value: row.calculated_cost, color: "#10b981" }), row.word_count != null && (0, jsx_runtime_1.jsx)(DetailChip, { label: "Words", value: String(row.word_count), color: "#f59e0b" }), row.file_type && (0, jsx_runtime_1.jsx)(DetailChip, { label: "Type", value: row.file_type, color: "#14b8a6" })] }))] }));
}
function DetailChip({ label, value, color }) {
    return ((0, jsx_runtime_1.jsxs)("div", { style: {
            background: `${color}15`, border: `1px solid ${color}30`,
            borderRadius: 8, padding: '5px 10px',
            display: 'flex', flexDirection: 'column', gap: 1,
        }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 10, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }, children: label }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 12, color, fontWeight: 700 }, children: value })] }));
}
function SectionHeader({ title, count, color, collapsed, onToggle }) {
    return ((0, jsx_runtime_1.jsxs)("button", { onClick: onToggle, style: {
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '10px 0', marginBottom: collapsed ? 0 : 10,
        }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 13, fontWeight: 700, color }, children: title }), (0, jsx_runtime_1.jsx)("span", { style: {
                            fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                            background: `${color}20`, color,
                        }, children: count })] }), (0, jsx_runtime_1.jsx)("span", { style: { color, fontSize: 28, lineHeight: 1, transition: 'transform 0.2s', transform: collapsed ? 'none' : 'rotate(180deg)', display: 'inline-block' }, children: "\u25BE" })] }));
}
// ─── Main Modal ───────────────────────────────────────────────────────────────
function ProjectModal({ project, onClose }) {
    const [stats, setStats] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [currentPage, setCurrentPage] = (0, react_1.useState)(1);
    const [failedCollapsed, setFailedCollapsed] = (0, react_1.useState)(false);
    const [resolvedCollapsed, setResolvedCollapsed] = (0, react_1.useState)(true);
    const [successCollapsed, setSuccessCollapsed] = (0, react_1.useState)(true);
    // Time period filter states
    const [timePeriod, setTimePeriod] = (0, react_1.useState)('daily');
    const [customFrom, setCustomFrom] = (0, react_1.useState)('');
    const [customTo, setCustomTo] = (0, react_1.useState)('');
    const [customApplyTick, setCustomApplyTick] = (0, react_1.useState)(0);
    (0, react_1.useEffect)(() => {
        setLoading(true);
        // Build date filter params based on time period
        let dateParams = '';
        if (timePeriod === 'daily') {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const tomorrow = new Date(today);
            tomorrow.setDate(tomorrow.getDate() + 1);
            dateParams = `&from=${today.toISOString()}&to=${tomorrow.toISOString()}`;
        }
        else if (timePeriod === 'weekly') {
            const weekAgo = new Date();
            weekAgo.setDate(weekAgo.getDate() - 7);
            weekAgo.setHours(0, 0, 0, 0);
            const now = new Date();
            dateParams = `&from=${weekAgo.toISOString()}&to=${now.toISOString()}`;
        }
        else if (timePeriod === 'custom' && customFrom && customTo && customApplyTick > 0) {
            const fromDate = new Date(customFrom);
            fromDate.setHours(0, 0, 0, 0);
            const toDate = new Date(customTo);
            toDate.setHours(23, 59, 59, 999);
            dateParams = `&from=${fromDate.toISOString()}&to=${toDate.toISOString()}`;
        }
        (0, api_1.apiFetch)(`/api/projects/${encodeURIComponent(project.name)}/logs?page=${currentPage}&limit=50${dateParams}`)
            .then((r) => r.json())
            .then((d) => { setStats(d); setLoading(false); })
            .catch(() => setLoading(false));
    }, [project.name, currentPage, timePeriod, customApplyTick]);
    // Filter logs by status - no slicing, show all in current page
    const failedLogs = stats?.logs?.filter((r) => !!r.error && !r.isResolved) ?? [];
    const resolvedLogs = stats?.logs?.filter((r) => !!r.error && r.isResolved) ?? [];
    const successLogs = stats?.logs?.filter((r) => !r.error) ?? [];
    // Count totals
    const totalFailedLogs = failedLogs.length;
    const totalResolvedLogs = resolvedLogs.length;
    const totalSuccessLogs = successLogs.length;
    // Aggregate token/cost totals if available
    const totalInputTokens = stats?.logs?.reduce((s, r) => s + (r.input_tokens ?? 0), 0) ?? 0;
    const totalOutputTokens = stats?.logs?.reduce((s, r) => s + (r.output_tokens ?? 0), 0) ?? 0;
    const hasTokenData = totalInputTokens > 0 || totalOutputTokens > 0;
    return ((0, jsx_runtime_1.jsx)("div", { onClick: onClose, style: {
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.75)',
            backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000, padding: 24,
        }, children: (0, jsx_runtime_1.jsxs)("div", { onClick: (e) => e.stopPropagation(), style: {
                background: '#0f172a',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 16,
                width: '95%', maxWidth: 720,
                maxHeight: '90vh',
                display: 'flex', flexDirection: 'column',
                overflow: 'hidden',
                boxShadow: '0 25px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04)',
            }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '18px 22px',
                        borderBottom: '1px solid rgba(255,255,255,0.07)',
                        background: 'rgba(255,255,255,0.02)',
                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                                        width: 40, height: 40, borderRadius: 10,
                                        background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontSize: 16, boxShadow: '0 0 16px rgba(99,102,241,0.4)',
                                    }, children: "\uD83E\uDD16" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 16, fontWeight: 700, color: '#f1f5f9' }, children: project.name }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#475569', marginTop: 2 }, children: stats?.exists ? `${stats.total} total records` : 'Loading…' })] })] }), (0, jsx_runtime_1.jsx)("button", { onClick: onClose, style: {
                                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                                color: '#94a3b8', fontSize: 16, cursor: 'pointer',
                                width: 32, height: 32, borderRadius: 8,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                            }, children: "\u2715" })] }), (0, jsx_runtime_1.jsxs)("div", { style: { overflow: 'auto', padding: '20px 22px', flex: 1 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                                marginBottom: 20,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                flexWrap: 'wrap',
                                gap: 10,
                                padding: '12px 14px',
                                background: 'rgba(255,255,255,0.02)',
                                border: '1px solid rgba(255,255,255,0.07)',
                                borderRadius: 10,
                            }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }, children: "Time Period:" }), (0, jsx_runtime_1.jsx)("div", { style: {
                                                display: 'flex', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                                                borderRadius: 8, padding: 3, gap: 2,
                                            }, children: ['daily', 'weekly', 'custom'].map((period) => ((0, jsx_runtime_1.jsx)("button", { onClick: () => setTimePeriod(period), style: {
                                                    padding: '5px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                                                    border: 'none', cursor: 'pointer', textTransform: 'capitalize',
                                                    background: timePeriod === period ? '#6366f1' : 'transparent',
                                                    color: timePeriod === period ? '#fff' : '#94a3b8',
                                                    transition: 'background 0.15s, color 0.15s',
                                                }, children: period }, period))) }), timePeriod === 'custom' && ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("input", { type: "date", value: customFrom, onChange: (e) => setCustomFrom(e.target.value), style: {
                                                        background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                                                        borderRadius: 6, color: '#e2e8f0',
                                                        padding: '5px 8px', fontSize: 11, outline: 'none',
                                                        cursor: 'pointer', colorScheme: 'dark',
                                                    } }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, color: '#64748b' }, children: "to" }), (0, jsx_runtime_1.jsx)("input", { type: "date", value: customTo, onChange: (e) => setCustomTo(e.target.value), style: {
                                                        background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                                                        borderRadius: 6, color: '#e2e8f0',
                                                        padding: '5px 8px', fontSize: 11, outline: 'none',
                                                        cursor: 'pointer', colorScheme: 'dark',
                                                    } }), (0, jsx_runtime_1.jsx)("button", { onClick: () => {
                                                        setCustomApplyTick((t) => t + 1);
                                                        setCurrentPage(1);
                                                    }, disabled: !customFrom || !customTo, style: {
                                                        padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
                                                        cursor: (!customFrom || !customTo) ? 'not-allowed' : 'pointer',
                                                        background: '#6366f1', color: '#fff', border: 'none',
                                                        opacity: (!customFrom || !customTo) ? 0.5 : 1,
                                                    }, children: "Apply" })] }))] }), (0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 10, color: '#64748b', fontStyle: 'italic' }, children: [timePeriod === 'daily' && 'Today\'s data', timePeriod === 'weekly' && 'Last 7 days', timePeriod === 'custom' && customFrom && customTo && `${new Date(customFrom).toLocaleDateString()} - ${new Date(customTo).toLocaleDateString()}`, timePeriod === 'custom' && (!customFrom || !customTo) && 'Select date range'] })] }), loading && ((0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', color: '#475569', padding: '60px 0', fontSize: 14 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 28, marginBottom: 12 }, children: "\u23F3" }), "Loading logs\u2026"] })), !loading && stats && !stats.exists && ((0, jsx_runtime_1.jsxs)("div", { style: { textAlign: 'center', color: '#475569', padding: '60px 0', fontSize: 14 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 32, marginBottom: 12 }, children: "\uD83D\uDCED" }), "No data table found for this project yet."] })), !loading && stats && stats.exists && ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'stretch' }, children: [(0, jsx_runtime_1.jsx)(SummaryCard, { label: "Files Processed", value: stats.filesProcessed, color: "#3b82f6", icon: "\uD83D\uDCC1" }), (0, jsx_runtime_1.jsx)(SummaryCard, { label: "Total Success", value: stats.success, color: "#10b981", icon: "\u2705" }), (0, jsx_runtime_1.jsx)(SummaryCard, { label: "Total Failures", value: stats.failure, color: "#ef4444", icon: "\u274C" }), (stats.resolved ?? 0) > 0 && ((0, jsx_runtime_1.jsx)(SummaryCard, { label: "Resolved Errors", value: stats.resolved ?? 0, color: "#8b5cf6", icon: "\u2714\uFE0F" })), hasTokenData && ((0, jsx_runtime_1.jsx)(SummaryCard, { label: "Input Tokens", value: totalInputTokens.toLocaleString(), color: "#8b5cf6", icon: "\uD83D\uDD22" })), hasTokenData && ((0, jsx_runtime_1.jsx)(SummaryCard, { label: "Output Tokens", value: totalOutputTokens.toLocaleString(), color: "#6366f1", icon: "\uD83D\uDCE4" })), stats.totalCost && ((0, jsx_runtime_1.jsx)(SummaryCard, { label: "Total Cost", value: stats.totalCost, color: "#f59e0b", icon: "\uD83D\uDCB0" }))] }), (0, jsx_runtime_1.jsx)(SuccessBar, { success: stats.success, total: stats.filesProcessed }), totalFailedLogs > 0 && ((0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 16 }, children: [(0, jsx_runtime_1.jsx)(SectionHeader, { title: "Failed Files", count: totalFailedLogs, color: "#f87171", collapsed: failedCollapsed, onToggle: () => setFailedCollapsed((v) => !v) }), !failedCollapsed && ((0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexDirection: 'column', gap: 6 }, children: failedLogs.map((row, i) => (0, jsx_runtime_1.jsx)(FileCard, { row: row }, i)) }))] })), totalResolvedLogs > 0 && ((0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 16 }, children: [(0, jsx_runtime_1.jsx)(SectionHeader, { title: "Resolved Files", count: totalResolvedLogs, color: "#8b5cf6", collapsed: resolvedCollapsed, onToggle: () => setResolvedCollapsed((v) => !v) }), !resolvedCollapsed && ((0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexDirection: 'column', gap: 6 }, children: resolvedLogs.map((row, i) => (0, jsx_runtime_1.jsx)(FileCard, { row: row }, i)) }))] })), totalSuccessLogs > 0 && ((0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 8 }, children: [(0, jsx_runtime_1.jsx)(SectionHeader, { title: "Successful Files", count: totalSuccessLogs, color: "#34d399", collapsed: successCollapsed, onToggle: () => setSuccessCollapsed((v) => !v) }), !successCollapsed && ((0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexDirection: 'column', gap: 6 }, children: successLogs.map((row, i) => (0, jsx_runtime_1.jsx)(FileCard, { row: row }, i)) }))] })), stats.logs?.length === 0 && ((0, jsx_runtime_1.jsx)("div", { style: { textAlign: 'center', color: '#475569', padding: '30px 0', fontSize: 13 }, children: "No file logs recorded yet." })), stats.pagination && stats.pagination.totalPages > 1 && ((0, jsx_runtime_1.jsxs)("div", { style: {
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        marginTop: 20,
                                        padding: '16px 0',
                                        borderTop: '1px solid rgba(255,255,255,0.07)'
                                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { fontSize: 12, color: '#94a3b8' }, children: ["Page ", stats.pagination.currentPage, " of ", stats.pagination.totalPages, (0, jsx_runtime_1.jsxs)("span", { style: { marginLeft: 8, color: '#64748b' }, children: ["(", stats.pagination.totalRecords.toLocaleString(), " total records)"] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 8 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => setCurrentPage(1), disabled: !stats.pagination.hasPreviousPage, style: {
                                                        padding: '6px 12px',
                                                        borderRadius: 6,
                                                        fontSize: 12,
                                                        fontWeight: 600,
                                                        cursor: stats.pagination.hasPreviousPage ? 'pointer' : 'not-allowed',
                                                        background: stats.pagination.hasPreviousPage ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.05)',
                                                        border: `1px solid ${stats.pagination.hasPreviousPage ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.1)'}`,
                                                        color: stats.pagination.hasPreviousPage ? '#818cf8' : '#475569',
                                                    }, children: "First" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setCurrentPage(currentPage - 1), disabled: !stats.pagination.hasPreviousPage, style: {
                                                        padding: '6px 12px',
                                                        borderRadius: 6,
                                                        fontSize: 12,
                                                        fontWeight: 600,
                                                        cursor: stats.pagination.hasPreviousPage ? 'pointer' : 'not-allowed',
                                                        background: stats.pagination.hasPreviousPage ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.05)',
                                                        border: `1px solid ${stats.pagination.hasPreviousPage ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.1)'}`,
                                                        color: stats.pagination.hasPreviousPage ? '#818cf8' : '#475569',
                                                    }, children: "\u2190 Previous" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setCurrentPage(currentPage + 1), disabled: !stats.pagination.hasNextPage, style: {
                                                        padding: '6px 12px',
                                                        borderRadius: 6,
                                                        fontSize: 12,
                                                        fontWeight: 600,
                                                        cursor: stats.pagination.hasNextPage ? 'pointer' : 'not-allowed',
                                                        background: stats.pagination.hasNextPage ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.05)',
                                                        border: `1px solid ${stats.pagination.hasNextPage ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.1)'}`,
                                                        color: stats.pagination.hasNextPage ? '#818cf8' : '#475569',
                                                    }, children: "Next \u2192" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setCurrentPage(stats.pagination.totalPages), disabled: !stats.pagination.hasNextPage, style: {
                                                        padding: '6px 12px',
                                                        borderRadius: 6,
                                                        fontSize: 12,
                                                        fontWeight: 600,
                                                        cursor: stats.pagination.hasNextPage ? 'pointer' : 'not-allowed',
                                                        background: stats.pagination.hasNextPage ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.05)',
                                                        border: `1px solid ${stats.pagination.hasNextPage ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.1)'}`,
                                                        color: stats.pagination.hasNextPage ? '#818cf8' : '#475569',
                                                    }, children: "Last" })] })] }))] }))] })] }) }));
}
// ─── Tile ─────────────────────────────────────────────────────────────────────
function ProjectTile({ project, index, onClick }) {
    const tc = tileColor(index);
    const cc = CATEGORY_COLOR[project.category] ?? '#64748b';
    const initials = project.name.split(' ').slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('');
    return ((0, jsx_runtime_1.jsxs)("div", { onClick: onClick, style: {
            background: 'var(--surface)', border: '1px solid var(--card-border)',
            borderTop: `3px solid ${tc}`, borderRadius: 'var(--radius-md)',
            padding: '18px 16px', display: 'flex', flexDirection: 'column', gap: 10,
            cursor: 'pointer', transition: 'box-shadow 0.15s',
        }, onMouseEnter: (e) => { e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.18)'; }, onMouseLeave: (e) => { e.currentTarget.style.boxShadow = 'none'; }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 10 }, children: [(0, jsx_runtime_1.jsx)("div", { style: {
                            width: 36, height: 36, borderRadius: 8, background: tc, flexShrink: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 13, fontWeight: 700, color: '#fff',
                        }, children: initials }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 13, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3, wordBreak: 'break-word' }, children: project.name })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, color: '#fff', background: cc, padding: '2px 8px', borderRadius: 4, fontWeight: 600 }, children: project.category }), (0, jsx_runtime_1.jsx)("span", { style: { width: 8, height: 8, borderRadius: '50%', background: tc, boxShadow: `0 0 6px ${tc}` } })] })] }));
}
// ─── Main ─────────────────────────────────────────────────────────────────────
function LogStream() {
    const [projects, setProjects] = (0, react_1.useState)([]);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [search, setSearch] = (0, react_1.useState)('');
    const [activeCategory, setActiveCategory] = (0, react_1.useState)('All');
    const [selectedProject, setSelectedProject] = (0, react_1.useState)(null);
    const [projectFilter, setProjectFilter] = (0, react_1.useState)(''); // New: project name filter
    (0, react_1.useEffect)(() => {
        setLoading(true);
        const params = activeCategory !== 'All' ? `?category=${encodeURIComponent(activeCategory)}` : '';
        (0, api_1.apiFetch)(`/api/projects${params}`)
            .then((r) => r.json())
            .then((data) => {
            setProjects(data);
            setLoading(false);
        })
            .catch(() => setLoading(false));
    }, [activeCategory]);
    // Apply both search and project filter
    const filtered = projects.filter((p) => {
        const matchesSearch = p.name.toLowerCase().includes(search.toLowerCase());
        const matchesProjectFilter = !projectFilter || p.name === projectFilter;
        return matchesSearch && matchesProjectFilter;
    });
    // Get unique project names for the filter dropdown
    const projectNames = Array.from(new Set(projects.map((p) => p.name))).sort();
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "log-stream", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 20 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "AI Services" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "All projects at a glance \u2014 click a tile to view data" })] }), (0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }, children: CATEGORIES.map((cat) => {
                    const active = activeCategory === cat;
                    const color = CATEGORY_COLOR[cat] ?? '#6366f1';
                    return ((0, jsx_runtime_1.jsx)("button", { onClick: () => { setActiveCategory(cat); setSearch(''); }, style: {
                            padding: '6px 14px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                            border: active ? `2px solid ${color}` : '1px solid var(--card-border)',
                            background: active ? color : 'var(--surface)',
                            color: active ? '#fff' : 'var(--text-muted)',
                            fontWeight: active ? 700 : 400, transition: 'all 0.15s',
                        }, children: cat }, cat));
                }) }), (0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsx)("input", { placeholder: "Search projects\u2026", value: search, onChange: (e) => setSearch(e.target.value), style: {
                            background: 'var(--input-bg)', border: '1px solid var(--input-border)',
                            borderRadius: 'var(--radius-sm)', color: 'var(--text)',
                            padding: '8px 14px', fontSize: 13, outline: 'none', flex: '1 1 auto', minWidth: 200,
                        } }), (0, jsx_runtime_1.jsxs)("select", { value: projectFilter, onChange: (e) => {
                            setProjectFilter(e.target.value);
                            setSearch(''); // Clear search when using dropdown
                        }, style: {
                            background: 'var(--input-bg)', border: '1px solid var(--input-border)',
                            borderRadius: 6, color: 'var(--text)',
                            padding: '8px 12px', fontSize: 13, outline: 'none',
                            cursor: 'pointer', minWidth: 200,
                        }, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "All Projects" }), projectNames.map((name) => ((0, jsx_runtime_1.jsx)("option", { value: name, children: name }, name)))] }), (0, jsx_runtime_1.jsxs)("span", { style: { fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }, children: [filtered.length, " project", filtered.length !== 1 ? 's' : '', " shown"] })] }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading projects\u2026" })) : ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14 }, children: [filtered.map((project, i) => ((0, jsx_runtime_1.jsx)(ProjectTile, { project: project, index: i, onClick: () => setSelectedProject(project) }, project.id))), filtered.length === 0 && ((0, jsx_runtime_1.jsx)("div", { style: { gridColumn: '1/-1', padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }, children: "No projects match" }))] })), selectedProject && ((0, jsx_runtime_1.jsx)(ProjectModal, { project: selectedProject, onClose: () => setSelectedProject(null) }))] }));
}
//# sourceMappingURL=LogStream.js.map