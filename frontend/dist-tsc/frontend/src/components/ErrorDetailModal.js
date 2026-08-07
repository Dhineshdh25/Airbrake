"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getTraceDisplayText = getTraceDisplayText;
exports.getStackTraceDisplayText = getStackTraceDisplayText;
exports.ErrorDetailModal = ErrorDetailModal;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const api_1 = require("../lib/api");
// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(ts) {
    if (!ts)
        return '—';
    return new Date(ts).toLocaleString([], {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
    });
}
function getTraceDisplayText(_errorDetail, solutionText) {
    return solutionText?.trim() || null;
}
function getStackTraceDisplayText(errorDetail, parsedStacktrace, aiDescription, aiRecommendation) {
    if (parsedStacktrace && parsedStacktrace.frames && parsedStacktrace.frames.length > 0) {
        return null;
    }
    const generatedCause = aiDescription?.trim() || aiRecommendation?.trim();
    if (generatedCause) {
        return generatedCause;
    }
    const rawTrace = parsedStacktrace?.raw_trace?.trim();
    if (rawTrace) {
        return rawTrace;
    }
    return errorDetail?.trim() || null;
}
// ── Shared styles ─────────────────────────────────────────────────────────────
const btnPrimary = {
    padding: '7px 16px', borderRadius: 6, fontSize: 12, fontWeight: 600,
    background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer',
};
const btnSecondary = {
    padding: '7px 14px', borderRadius: 6, fontSize: 12,
    background: 'transparent', color: 'var(--text-muted)',
    border: '1px solid var(--card-border)', cursor: 'pointer',
};
const btnDanger = {
    padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
    background: 'rgba(239,68,68,0.1)', color: '#f87171',
    border: '1px solid rgba(239,68,68,0.25)', cursor: 'pointer',
};
const metaRow = {
    display: 'flex', flexWrap: 'wrap', gap: 12,
    fontSize: 11, color: 'var(--text-muted)', marginTop: 8,
};
const sectionLabel = {
    fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
    letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 10,
};
// ── Confidence bar ────────────────────────────────────────────────────────────
function ConfidenceBar({ score }) {
    const pct = Math.min(100, Math.max(0, score));
    const color = pct >= 80 ? '#34d399' : pct >= 50 ? '#fbbf24' : '#f87171';
    return ((0, jsx_runtime_1.jsxs)("span", { style: { display: 'inline-flex', alignItems: 'center', gap: 6 }, children: [(0, jsx_runtime_1.jsx)("span", { style: {
                    display: 'inline-block', width: 60, height: 5, borderRadius: 3,
                    background: 'rgba(255,255,255,0.1)', overflow: 'hidden',
                }, children: (0, jsx_runtime_1.jsx)("span", { style: { display: 'block', width: `${pct}%`, height: '100%', background: color, borderRadius: 3 } }) }), (0, jsx_runtime_1.jsxs)("span", { style: { color, fontWeight: 600 }, children: [pct.toFixed(0), "%"] })] }));
}
// ── Solution meta line ────────────────────────────────────────────────────────
function SolutionMeta({ sol }) {
    return ((0, jsx_runtime_1.jsxs)("div", { style: metaRow, children: [sol.version != null && (0, jsx_runtime_1.jsxs)("span", { children: ["v", sol.version] }), sol.confidence_score != null && ((0, jsx_runtime_1.jsxs)("span", { style: { display: 'flex', alignItems: 'center', gap: 6 }, children: ["Confidence: ", (0, jsx_runtime_1.jsx)(ConfidenceBar, { score: sol.confidence_score })] })), sol.usage_count != null && (0, jsx_runtime_1.jsxs)("span", { children: ["Used ", sol.usage_count, "\u00D7"] }), sol.created_by && (0, jsx_runtime_1.jsxs)("span", { children: ["By ", sol.created_by] }), sol.created_at && (0, jsx_runtime_1.jsx)("span", { children: fmt(sol.created_at) })] }));
}
// ── Parsed Stack Trace ────────────────────────────────────────────────────────
function ParsedStackTraceView({ parsedTrace }) {
    if (!parsedTrace.frames || parsedTrace.frames.length === 0) {
        return ((0, jsx_runtime_1.jsx)("pre", { style: {
                margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
                lineHeight: 1.8, color: '#fca5a5',
                background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)',
                borderRadius: 8, padding: '18px 20px',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', minHeight: 140,
            }, children: parsedTrace.raw_trace }));
    }
    return ((0, jsx_runtime_1.jsx)("div", { style: { display: 'flex', flexDirection: 'column', gap: 12 }, children: parsedTrace.frames.map((frame, idx) => ((0, jsx_runtime_1.jsxs)("div", { style: {
                background: 'rgba(239,68,68,0.04)', border: '1px solid rgba(239,68,68,0.12)',
                borderRadius: 8, overflow: 'hidden',
            }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: '10px 14px', background: 'rgba(239,68,68,0.06)',
                        borderBottom: '1px solid rgba(239,68,68,0.12)',
                        display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                    }, children: [(0, jsx_runtime_1.jsx)("span", { style: { color: '#fca5a5', fontWeight: 600 }, children: frame.file_path }), (0, jsx_runtime_1.jsx)("span", { style: { color: 'rgba(252,165,165,0.5)' }, children: ":" }), (0, jsx_runtime_1.jsxs)("span", { style: { color: '#fbbf24', fontWeight: 600 }, children: ["line ", frame.line_number] }), frame.column != null && ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("span", { style: { color: 'rgba(252,165,165,0.5)' }, children: ":" }), (0, jsx_runtime_1.jsxs)("span", { style: { color: '#fbbf24' }, children: ["col ", frame.column] })] })), frame.function_name && ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("span", { style: { color: 'rgba(252,165,165,0.5)', marginLeft: 4 }, children: "in" }), (0, jsx_runtime_1.jsx)("span", { style: { color: '#818cf8', fontWeight: 600 }, children: frame.function_name })] }))] }), frame.code_line ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '12px 14px' }, children: (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'flex-start', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("span", { style: {
                                    color: 'rgba(252,165,165,0.4)', fontSize: 11, fontFamily: 'ui-monospace, monospace',
                                    minWidth: 32, textAlign: 'right', paddingTop: 2, userSelect: 'none',
                                }, children: frame.line_number }), (0, jsx_runtime_1.jsx)("pre", { style: {
                                    margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
                                    lineHeight: 1.6, color: '#fca5a5', whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word', flex: 1,
                                }, children: frame.code_line })] }) })) : ((0, jsx_runtime_1.jsx)("div", { style: { padding: '12px 14px', fontSize: 11, color: 'rgba(252,165,165,0.5)' }, children: (0, jsx_runtime_1.jsx)("span", { style: { fontStyle: 'italic' }, children: "Source code not available" }) }))] }, idx))) }));
}
// ── Main component ────────────────────────────────────────────────────────────
function ErrorDetailModal({ row, errorHash, projectName: projectNameProp, onClose, onRefresh, }) {
    const effectiveErrorHash = row?.error_hash || errorHash;
    const isModal = !!row;
    // ── Remote data ──────────────────────────────────────────────────────────
    const [data, setData] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(!!effectiveErrorHash);
    const [notFound, setNotFound] = (0, react_1.useState)(false);
    // ── Paginated KB solutions ───────────────────────────────────────────────
    const [kbSolutions, setKbSolutions] = (0, react_1.useState)([]);
    const [kbTotal, setKbTotal] = (0, react_1.useState)(0);
    const [kbOffset, setKbOffset] = (0, react_1.useState)(0);
    const [kbLoading, setKbLoading] = (0, react_1.useState)(false);
    const KB_PAGE = 5;
    // ── Versions panel ───────────────────────────────────────────────────────
    const [versionsFor, setVersionsFor] = (0, react_1.useState)(null);
    const [versions, setVersions] = (0, react_1.useState)([]);
    const [loadingVersions, setLoadingVersions] = (0, react_1.useState)(false);
    // ── Editor ───────────────────────────────────────────────────────────────
    const [editorText, setEditorText] = (0, react_1.useState)('');
    const [editorSaving, setEditorSaving] = (0, react_1.useState)(false);
    const [editorError, setEditorError] = (0, react_1.useState)('');
    const [duplicatePrompt, setDuplicatePrompt] = (0, react_1.useState)(null);
    /** When the user clicks Improve on a card, we store its id here so the
     *  save payload can carry base_solution_id to the backend.  null means
     *  the editor is in Create New mode. */
    const [improveTargetId, setImproveTargetId] = (0, react_1.useState)(null);
    // ── Action state ─────────────────────────────────────────────────────────
    const [actionBusy, setActionBusy] = (0, react_1.useState)(false);
    const [actionError, setActionError] = (0, react_1.useState)('');
    // ── Jira ticket state ─────────────────────────────────────────────────────
    const [jiraStatus, setJiraStatus] = (0, react_1.useState)('idle');
    const [jiraTicket, setJiraTicket] = (0, react_1.useState)(null);
    const [jiraError, setJiraError] = (0, react_1.useState)('');
    const [jiraConnected, setJiraConnected] = (0, react_1.useState)(null); // null = unknown
    // ── The specific log row id to target for resolve/reopen ─────────────────
    // When opened from BreaksList, row.representative_id is the most-recent
    // open log row id from the grouped query. We send it on every resolve/reopen
    // call so only THAT row changes status, not every row sharing the hash.
    const targetLogId = row?.representative_id ?? null;
    // ── Derived ──────────────────────────────────────────────────────────────
    const projectName = data?.project_name ?? row?.project ?? projectNameProp ?? '';
    const errorMessage = data?.error_message ?? row?.error ?? '';
    const errorStatus = data?.error_status ?? null;
    const isResolved = errorStatus === 'resolved';
    const isReopened = errorStatus === 'reopened';
    // The solution stored on the error row (used/previously used)
    const activeSolution = data?.solution ?? null;
    // AI recommendation: top solution from ai_recommendation.solutions, sorted by confidence then usage
    const aiRec = data?.ai_recommendation ?? null;
    const aiText = aiRec?.recommendation ?? null;
    // Pick the single best AI-recommended solution to display (highest confidence → usage)
    const aiTopSolution = (() => {
        const sols = (aiRec?.solutions ?? []).filter(s => s?.solution);
        if (sols.length === 0)
            return null;
        return [...sols].sort((a, b) => {
            const cd = (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
            return cd !== 0 ? cd : (b.usage_count ?? 0) - (a.usage_count ?? 0);
        })[0];
    })();
    const aiTextIsDuplicate = !!(aiText && aiTopSolution && aiText.trim() === aiTopSolution.solution?.trim());
    const aiRecommendationText = aiText && !aiTextIsDuplicate ? aiText : null;
    const hasAiContent = !!(aiRecommendationText || aiTopSolution);
    // ── Data fetching ─────────────────────────────────────────────────────────
    function loadDetail() {
        if (!effectiveErrorHash)
            return;
        setLoading(true);
        // Build query string — always include project_name when available,
        // and log_id (the specific row id) so the backend returns the status
        // of this exact occurrence rather than the aggregate across all rows
        // sharing the same error_hash.
        const qsParams = new URLSearchParams();
        if (projectNameProp)
            qsParams.set('project_name', projectNameProp);
        if (targetLogId)
            qsParams.set('log_id', targetLogId);
        const qs = qsParams.toString() ? `?${qsParams.toString()}` : '';
        (0, api_1.apiFetch)(`/api/breaks/detail/${encodeURIComponent(effectiveErrorHash)}${qs}`)
            .then(r => { if (!r.ok)
            throw r; return r.json(); })
            .then((d) => {
            setData(d);
            setNotFound(false);
            // If the backend reports an existing Jira ticket for this error,
            // surface it immediately so the Create button can be disabled.
            try {
                const anyd = d;
                if (anyd.jira_ticket && anyd.jira_ticket.key) {
                    setJiraTicket({ key: anyd.jira_ticket.key, url: anyd.jira_ticket.url });
                    setJiraStatus('created');
                }
            }
            catch (e) {
                // ignore parse errors
            }
            // Reset KB pagination whenever detail reloads
            setKbSolutions([]);
            setKbOffset(0);
            setKbTotal(0);
        })
            .catch(err => { if (err?.status === 404)
            setNotFound(true); })
            .finally(() => setLoading(false));
    }
    (0, react_1.useEffect)(() => { loadDetail(); }, [effectiveErrorHash, projectNameProp]);
    // Load first KB page after data arrives (only for open/reopened states)
    (0, react_1.useEffect)(() => {
        if (!data || isResolved)
            return;
        setKbSolutions([]);
        setKbOffset(0);
        setKbTotal(0);
        loadKbPage(0, data);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data?.error_message, data?.error_status]);
    /**
     * Fetch a page of existing solutions.
     * Queries by error_hash + project_name (NOT by log row id) so every
     * occurrence of the same project+error sees the same solution pool.
     */
    function loadKbPage(offset, errorData) {
        if (!errorData?.error_message && !errorData?.error_hash)
            return;
        setKbLoading(true);
        const qs = new URLSearchParams({
            limit: String(KB_PAGE),
            offset: String(offset),
            ...(errorData.error_message ? { error_message: errorData.error_message } : {}),
            // error_hash kept as fallback for the backend's legacy path
            ...(errorData.error_hash ? { error_hash: errorData.error_hash } : {}),
            ...(errorData.project_name ? { project_name: errorData.project_name } : {}),
            // Semantic group fallback tier — enables cross-hash retrieval within the same category
            ...(errorData.error_group_name ? { error_group_name: errorData.error_group_name } : {}),
        });
        (0, api_1.apiFetch)(`/api/knowledge_base/top?${qs}`)
            .then(r => r.json())
            .then(j => {
            const sols = j.solutions ?? [];
            setKbSolutions(prev => offset === 0 ? sols : [...prev, ...sols]);
            setKbTotal(j.total ?? 0);
            setKbOffset(offset + sols.length);
        })
            .catch(console.error)
            .finally(() => setKbLoading(false));
    }
    async function loadVersions(solutionId) {
        if (versionsFor === solutionId) {
            setVersionsFor(null);
            return;
        }
        setLoadingVersions(true);
        try {
            const r = await (0, api_1.apiFetch)(`/api/knowledge_base/${encodeURIComponent(solutionId)}/versions`);
            const j = await r.json();
            setVersions(j.versions ?? []);
            setVersionsFor(solutionId);
        }
        finally {
            setLoadingVersions(false);
        }
    }
    // ── "Use solution" — resolves in-place, closes modal, refreshes parent ────
    async function useSolution(solutionId) {
        if (!effectiveErrorHash || !projectName)
            return;
        setActionBusy(true);
        setActionError('');
        try {
            const r = await (0, api_1.apiFetch)('/api/knowledge_base/use', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    solution_id: solutionId,
                    error_hash: effectiveErrorHash,
                    project_name: projectName,
                    // Target only the specific occurrence that was opened, not all rows
                    // sharing the same hash (which would resolve unrelated occurrences).
                    ...(targetLogId ? { log_id: targetLogId } : {}),
                }),
            });
            if (!r.ok)
                throw new Error((await r.json()).error ?? 'Failed');
            const j = await r.json();
            // Update local state so if the parent doesn't navigate away we still show resolved
            setData(prev => prev ? {
                ...prev,
                error_status: 'resolved',
                resolved_at: new Date().toISOString(),
                solution: {
                    id: j.solution_id,
                    solution: j.solution,
                    created_at: j.created_at,
                    created_by: j.created_by,
                    version: j.version,
                    confidence_score: j.confidence_score,
                    usage_count: j.usage_count,
                    updated_at: null,
                },
            } : prev);
            onRefresh?.();
            onClose();
        }
        catch (e) {
            setActionError(e instanceof api_1.ApiError ? e.label : String(e));
        }
        finally {
            setActionBusy(false);
        }
    }
    // ── Jira: initiate OAuth — authenticated fetch returns the redirect URL ──
    async function startJiraOAuth() {
        try {
            // Store pending ticket context so we can auto-retry after OAuth callback
            const pendingContext = {
                error_hash: effectiveErrorHash,
                project_name: projectName,
                error_message: errorMessage,
                error_group: data?.error_group_name,
                error_detail: data?.error_detail,
                occurrence_count: data?.occurrence_count,
                status: data?.error_status,
                solution: data?.solution?.solution,
                ai_recommendation: data?.ai_recommendation?.recommendation,
                timestamp: data?.last_seen,
                file_name: data?.file_name,
                airbrake_url: effectiveErrorHash
                    ? (0, api_1.buildAirbrakeErrorUrl)(effectiveErrorHash, projectName)
                    : undefined,
            };
            sessionStorage.setItem('jira_pending_ticket', JSON.stringify(pendingContext));
            const r = await (0, api_1.apiFetch)('/api/jira/initiate', { method: 'POST' });
            const j = await r.json();
            if (j.redirect_url) {
                window.location.href = j.redirect_url; // navigate to Atlassian — no credentials in URL
            }
            else {
                setJiraError('Could not start Jira connection. Please try again.');
                setJiraStatus('error');
                sessionStorage.removeItem('jira_pending_ticket');
            }
        }
        catch {
            setJiraError('Could not start Jira connection. Please try again.');
            setJiraStatus('error');
            sessionStorage.removeItem('jira_pending_ticket');
        }
    }
    // ── Jira: check GLOBAL ticket existence when modal opens ─────────────────
    // This is separate from the OAuth status check. It reads the database for
    // any existing Jira ticket linked to this error_hash — regardless of which
    // user created it. Both User A and User B see the same ticket info.
    (0, react_1.useEffect)(() => {
        if (!effectiveErrorHash)
            return;
        (0, api_1.apiFetch)(`/api/jira/ticket-status?error_hash=${encodeURIComponent(effectiveErrorHash)}`)
            .then(r => r.json())
            .then((j) => {
            if (j.has_ticket && j.issue_key) {
                setJiraTicket({ key: j.issue_key, url: j.issue_url ?? '' });
                setJiraStatus('created');
            }
        })
            .catch(() => { });
    }, [effectiveErrorHash]);
    // ── Jira: check OAuth connection status when modal opens ──────────────────
    (0, react_1.useEffect)(() => {
        if (!effectiveErrorHash)
            return;
        (0, api_1.apiFetch)('/api/jira/status')
            .then(r => r.json())
            .then((j) => setJiraConnected(j.connected))
            .catch(() => setJiraConnected(false));
    }, [effectiveErrorHash]);
    // ── Jira: create ticket ───────────────────────────────────────────────────
    async function createJiraTicketInternal(errorData) {
        const ticketData = errorData || {
            project_name: projectName || undefined,
            error_group: data?.error_group_name || undefined,
            error_message: errorMessage || undefined,
            error_detail: data?.error_detail || undefined,
            error_hash: effectiveErrorHash || undefined,
            occurrence_count: data?.occurrence_count ?? undefined,
            status: data?.error_status || undefined,
            solution: data?.solution?.solution || undefined,
            ai_recommendation: data?.ai_recommendation?.recommendation || undefined,
            timestamp: data?.last_seen || undefined,
            file_name: data?.file_name || undefined,
            airbrake_url: effectiveErrorHash
                ? (0, api_1.buildAirbrakeErrorUrl)(effectiveErrorHash, projectName)
                : undefined,
        };
        setJiraStatus('creating');
        setJiraError('');
        setJiraTicket(null);
        try {
            const r = await (0, api_1.apiFetch)('/api/jira/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ticketData),
            });
            const j = await r.json();
            setJiraTicket({ key: j.key, url: j.url });
            setJiraStatus('created');
            // Link the Jira ticket to the log row so the global ticket-status
            // endpoint can find it when any other user opens this error.
            if (j.key && targetLogId) {
                (0, api_1.apiFetch)('/api/jira/link', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        log_id: targetLogId,
                        issue_key: j.key,
                        issue_url: j.url,
                    }),
                }).catch(() => { });
            }
        }
        catch (e) {
            let msg = 'Failed to create Jira ticket.';
            if (e instanceof api_1.ApiError) {
                if (e.status === 401) {
                    // Token revoked — send user to reconnect
                    msg = 'Your Jira session expired. Reconnecting…';
                    setJiraError(msg);
                    setJiraStatus('error');
                    setTimeout(() => { startJiraOAuth(); }, 1500);
                    return;
                }
                if (e.status === 403 || e.status === 502) {
                    // Try to surface the Jira permission error
                    msg = "You don't have permission to create issues in this Jira project. Contact your Jira administrator.";
                }
            }
            setJiraError(msg);
            setJiraStatus('error');
        }
    }
    async function handleCreateJiraTicket() {
        // If not connected, start OAuth via authenticated initiate call
        if (!jiraConnected) {
            await startJiraOAuth();
            return;
        }
        await createJiraTicketInternal();
    }
    // ── Auto-retry ticket creation after OAuth callback ─────────────────────
    (0, react_1.useEffect)(() => {
        const pendingStr = sessionStorage.getItem('jira_pending_ticket');
        if (!pendingStr)
            return;
        // Only auto-retry if we're back on the error detail and Jira is now connected
        if (effectiveErrorHash && jiraConnected === true) {
            try {
                const pending = JSON.parse(pendingStr);
                sessionStorage.removeItem('jira_pending_ticket');
                // Auto-retry with the stored error data
                createJiraTicketInternal(pending);
            }
            catch (err) {
                console.error('[ErrorDetailModal] Failed to parse pending ticket context:', err);
                sessionStorage.removeItem('jira_pending_ticket');
            }
        }
    }, [jiraConnected, effectiveErrorHash]);
    // ── Reopen ───────────────────────────────────────────────────────────────
    async function handleReopen() {
        if (!effectiveErrorHash || !projectName)
            return;
        setActionBusy(true);
        setActionError('');
        try {
            const r = await (0, api_1.apiFetch)('/api/knowledge_base/reopen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    error_hash: effectiveErrorHash,
                    project_name: projectName,
                    // Target only this specific occurrence.
                    ...(targetLogId ? { log_id: targetLogId } : {}),
                }),
            });
            if (!r.ok)
                throw new Error((await r.json()).error ?? 'Failed');
            onRefresh?.();
            // Reload full detail so KB solutions are fresh and state switches to reopened
            loadDetail();
        }
        catch (e) {
            setActionError(e instanceof api_1.ApiError ? e.label : String(e));
        }
        finally {
            setActionBusy(false);
        }
    }
    // ── Delete solution (entire family) ──────────────────────────────────────
    async function handleDeleteSolution(solutionId) {
        if (!effectiveErrorHash)
            return;
        if (!window.confirm('Delete this solution? This cannot be undone.'))
            return;
        setActionBusy(true);
        try {
            await (0, api_1.apiFetch)(`/api/knowledge_base/${encodeURIComponent(effectiveErrorHash)}` +
                `?solution_id=${encodeURIComponent(solutionId)}` +
                `&project_name=${encodeURIComponent(projectName)}`, { method: 'DELETE' });
            setData(prev => prev ? { ...prev, solution: null } : prev);
            setKbSolutions(prev => prev.filter(s => s.id !== solutionId));
        }
        catch (e) {
            setActionError(e instanceof api_1.ApiError ? e.label : String(e));
        }
        finally {
            setActionBusy(false);
        }
    }
    async function handleDeleteVersion(solutionId, versionId) {
        try {
            await (0, api_1.apiFetch)(`/api/knowledge_base/${encodeURIComponent(solutionId)}/versions/${encodeURIComponent(versionId)}`, { method: 'DELETE' });
            setVersions(prev => prev.filter(v => v.id !== versionId));
        }
        catch (e) {
            setActionError(e instanceof api_1.ApiError ? e.label : String(e));
        }
    }
    // ── Editor: save new / improved solution ─────────────────────────────────
    async function handleSave(forceCreate = false) {
        if (!effectiveErrorHash || !editorText.trim())
            return;
        setEditorSaving(true);
        setEditorError('');
        setDuplicatePrompt(null);
        try {
            // 1. Check for duplicates first
            const previewPayload = {
                error_hash: effectiveErrorHash,
                error_message: errorMessage || undefined,
                solution: editorText.trim(),
                project_name: projectName,
                check_only: !forceCreate,
                // When improving an existing solution, pass its id so the backend
                // creates a new version within that solution's family instead of a
                // new independent root.
                ...(improveTargetId ? { base_solution_id: improveTargetId } : {}),
                ...(forceCreate ? { create_anyway: true } : {}),
            };
            const previewRes = await (0, api_1.apiFetch)('/api/knowledge_base', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(previewPayload),
            });
            const preview = await previewRes.json();
            if (preview?.duplicate_prompt && !forceCreate) {
                setDuplicatePrompt({
                    solution_id: preview.solution_id,
                    solution: preview.solution,
                    decision: preview.decision,
                    similarity: preview.similarity,
                    version: preview.version,
                    confidence_score: preview.confidence_score,
                    usage_count: preview.usage_count,
                    created_by: preview.created_by,
                    created_at: preview.created_at,
                });
                return;
            }
            // 2. Actual save (check_only: false)
            const saveRes = await (0, api_1.apiFetch)('/api/knowledge_base', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...previewPayload, check_only: false }),
            });
            const saved = await saveRes.json();
            // 3. Auto-use (resolve) with the new or found solution id
            const idToUse = saved.duplicate ? saved.solution_id : saved.id;
            if (idToUse) {
                await useSolution(idToUse);
            }
            else {
                loadDetail();
            }
            setEditorText('');
            setImproveTargetId(null);
        }
        catch (e) {
            setEditorError(e instanceof api_1.ApiError ? e.label : 'Failed to save solution.');
        }
        finally {
            setEditorSaving(false);
        }
    }
    async function handleUseDuplicate() {
        if (!duplicatePrompt)
            return;
        setDuplicatePrompt(null);
        await useSolution(duplicatePrompt.solution_id);
    }
    // ── Improve: pre-fill editor with existing solution text ─────────────────
    function handleImprove(solutionId, solutionText) {
        setImproveTargetId(solutionId);
        setEditorText(solutionText);
        setTimeout(() => {
            document.getElementById('airbrake-solution-editor')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            document.getElementById('airbrake-solution-editor')?.focus();
        }, 50);
    }
    function handleCancelImprove() {
        setImproveTargetId(null);
        setEditorText('');
    }
    // ── Early returns ─────────────────────────────────────────────────────────
    if (!effectiveErrorHash)
        return null;
    if (loading) {
        return ((0, jsx_runtime_1.jsx)("div", { style: { padding: isModal ? 0 : '60px 0', textAlign: 'center', color: 'var(--text-muted)' }, children: "Loading error details\u2026" }));
    }
    if (notFound) {
        return ((0, jsx_runtime_1.jsxs)("div", { style: { padding: isModal ? 0 : '60px 0', textAlign: 'center' }, children: [(0, jsx_runtime_1.jsx)("p", { style: { color: 'var(--text-muted)', fontSize: 16 }, children: "Error not found." }), (0, jsx_runtime_1.jsx)("button", { onClick: onClose, style: { background: 'none', border: 'none', color: '#818cf8', cursor: 'pointer', fontSize: 13, padding: 0 }, children: "\u2190 Back" })] }));
    }
    // ── Render helpers ────────────────────────────────────────────────────────
    function renderSolutionCard(sol, opts = {}) {
        const isActiveInVersions = versionsFor === sol.id;
        return ((0, jsx_runtime_1.jsxs)("div", { style: {
                padding: 14, borderRadius: 8,
                background: opts.highlight ? 'rgba(99,102,241,0.08)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${opts.highlight ? 'rgba(99,102,241,0.25)' : 'var(--card-border)'}`,
                marginBottom: 8,
            }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }, children: sol.solution }), sol.match_source && sol.match_source !== 'exact_match' && ((0, jsx_runtime_1.jsx)("div", { style: { marginTop: 6 }, children: (0, jsx_runtime_1.jsx)("span", { style: {
                            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                            background: sol.match_source.startsWith('same_group')
                                ? 'rgba(56,189,248,0.12)' : 'rgba(99,102,241,0.12)',
                            color: sol.match_source.startsWith('same_group') ? '#38bdf8' : '#818cf8',
                            border: `1px solid ${sol.match_source.startsWith('same_group') ? 'rgba(56,189,248,0.3)' : 'rgba(99,102,241,0.3)'}`,
                            letterSpacing: '0.04em',
                        }, children: sol.match_source.startsWith('same_group')
                            ? `✓ Same Group${sol.match_source.includes(':') ? ': ' + sol.match_source.split(':')[1] : ''}`
                            : '✓ Similar Error' }) })), (0, jsx_runtime_1.jsx)(SolutionMeta, { sol: sol }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => useSolution(sol.id), disabled: actionBusy || !sol.id, style: { ...btnPrimary, opacity: actionBusy ? 0.6 : 1 }, children: actionBusy ? 'Working…' : 'Use' }), opts.showImprove && ((0, jsx_runtime_1.jsx)("button", { onClick: () => handleImprove(sol.id, sol.solution), style: btnSecondary, children: "Improve" })), sol.id && ((0, jsx_runtime_1.jsx)("button", { onClick: () => loadVersions(sol.id), disabled: loadingVersions, style: btnSecondary, children: loadingVersions && isActiveInVersions ? 'Loading…' : isActiveInVersions ? 'Hide Versions' : 'Versions' })), opts.showDelete && sol.id && ((0, jsx_runtime_1.jsx)("button", { onClick: () => handleDeleteSolution(sol.id), disabled: actionBusy, style: btnDanger, children: "Delete" }))] }), isActiveInVersions && ((0, jsx_runtime_1.jsx)("div", { style: { marginTop: 10, padding: 10, borderRadius: 8, background: 'rgba(0,0,0,0.15)', border: '1px solid var(--card-border)' }, children: versions.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: "No other versions." })) : versions.map(v => ((0, jsx_runtime_1.jsxs)("div", { style: { paddingBottom: 10, marginBottom: 10, borderBottom: '1px solid var(--card-border)' }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }, children: v.solution }), (0, jsx_runtime_1.jsx)(SolutionMeta, { sol: v }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 6, marginTop: 8 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => useSolution(v.id), disabled: actionBusy || !v.id, style: { ...btnPrimary, padding: '5px 12px' }, children: "Use" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => handleDeleteVersion(sol.id, v.id), style: { ...btnDanger, padding: '5px 12px' }, children: "Delete Version" })] })] }, v.id))) }))] }, sol.id ?? sol.solution));
    }
    // ── RESOLVED STATE ────────────────────────────────────────────────────────
    // Only shows the solution that was actually used on this specific error row.
    // Does NOT search the KB — reads from data.solution only.
    function renderResolved() {
        const resolvedSolution = activeSolution?.solution ? activeSolution : aiTopSolution;
        return ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 20 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: '14px 18px', borderRadius: 10,
                        background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
                    }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, fontWeight: 700, color: '#34d399', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }, children: "\u2713 Resolved" }), data?.resolved_at && ((0, jsx_runtime_1.jsxs)("div", { style: { fontSize: 12, color: 'var(--text-muted)' }, children: ["Resolved ", fmt(data.resolved_at)] }))] }), errorMessage && ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 16,
                        borderRadius: 10,
                        background: 'rgba(239,68,68,0.06)',
                        border: '1px solid rgba(239,68,68,0.18)',
                    }, children: [(0, jsx_runtime_1.jsx)("div", { style: { ...sectionLabel, color: '#f87171', marginBottom: 8 }, children: "Raw Error Message" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 15, fontWeight: 700, color: '#fca5a5', lineHeight: 1.5, wordBreak: 'break-word' }, children: errorMessage })] })), resolvedSolution ? ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 16, borderRadius: 10,
                        background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
                    }, children: [(0, jsx_runtime_1.jsx)("div", { style: { ...sectionLabel, color: '#818cf8' }, children: "\uD83D\uDCA1 Solution Used" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 6 }, children: resolvedSolution.solution }), (0, jsx_runtime_1.jsxs)("div", { style: metaRow, children: [resolvedSolution.version != null && (0, jsx_runtime_1.jsxs)("span", { children: ["v", resolvedSolution.version] }), resolvedSolution.confidence_score != null && ((0, jsx_runtime_1.jsxs)("span", { style: { display: 'flex', alignItems: 'center', gap: 6 }, children: ["Confidence: ", (0, jsx_runtime_1.jsx)(ConfidenceBar, { score: resolvedSolution.confidence_score })] })), resolvedSolution.usage_count != null && (0, jsx_runtime_1.jsxs)("span", { children: ["Used ", resolvedSolution.usage_count, "\u00D7"] }), resolvedSolution.created_by && (0, jsx_runtime_1.jsxs)("span", { children: ["Resolved by ", resolvedSolution.created_by] }), data?.resolved_at && (0, jsx_runtime_1.jsx)("span", { children: fmt(data.resolved_at) })] })] })) : ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)', padding: '12px 0' }, children: "No solution record found for this resolution." })), actionError && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: '#f87171', padding: '8px 12px', borderRadius: 6, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }, children: actionError }))] }));
    }
    // ── OPEN / REOPENED STATE ─────────────────────────────────────────────────
    function renderOpen() {
        const hasMoreKb = kbOffset < kbTotal;
        return ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 22 }, children: [isReopened && activeSolution?.solution && ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 16, borderRadius: 10,
                        background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.18)',
                    }, children: [(0, jsx_runtime_1.jsx)("div", { style: { ...sectionLabel, color: '#f87171' }, children: "\uD83E\uDDFE Previously Used Solution" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 6 }, children: activeSolution.solution }), (0, jsx_runtime_1.jsxs)("div", { style: metaRow, children: [activeSolution.version != null && (0, jsx_runtime_1.jsxs)("span", { children: ["v", activeSolution.version] }), activeSolution.created_by && (0, jsx_runtime_1.jsxs)("span", { children: ["Resolved by ", activeSolution.created_by] }), data?.resolved_at && (0, jsx_runtime_1.jsxs)("span", { children: ["Resolved ", fmt(data.resolved_at)] })] })] })), errorMessage && ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 16,
                        borderRadius: 10,
                        background: 'rgba(239,68,68,0.06)',
                        border: '1px solid rgba(239,68,68,0.18)',
                    }, children: [(0, jsx_runtime_1.jsx)("div", { style: { ...sectionLabel, color: '#f87171', marginBottom: 8 }, children: "Raw Error Message" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 15, fontWeight: 700, color: '#fca5a5', lineHeight: 1.5, wordBreak: 'break-word' }, children: errorMessage })] })), (data?.error_detail || data?.parsed_stacktrace?.raw_trace || aiRec?.description || aiRecommendationText) && ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: sectionLabel, children: "\uD83D\uDCCB Stack Trace" }), data?.parsed_stacktrace && data.parsed_stacktrace.frames && data.parsed_stacktrace.frames.length > 0 ? ((0, jsx_runtime_1.jsx)("div", { children: (() => {
                                const topFrame = data.parsed_stacktrace.frames[0];
                                // Check if this is a real source file or just a placeholder
                                const isRealFile = topFrame.file_path &&
                                    !['<unknown>', '<string>', '<stdin>', 'unknown'].includes(topFrame.file_path.toLowerCase());
                                // Only show the "Code Line That Caused the Error" section if we have a real file
                                // or if we have actual code content to show
                                if (!isRealFile && !topFrame.code_line) {
                                    return null; // Skip this entire section
                                }
                                return ((0, jsx_runtime_1.jsxs)("div", { style: {
                                        padding: '18px 20px', borderRadius: 12,
                                        background: 'rgba(239,68,68,0.08)', border: '3px solid rgba(239,68,68,0.3)',
                                        boxShadow: '0 4px 12px rgba(239,68,68,0.15)',
                                        marginBottom: 16,
                                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 20 }, children: "\uD83D\uDCA5" }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, fontWeight: 700, color: '#f87171', textTransform: 'uppercase', letterSpacing: '0.08em' }, children: "Code Line That Caused the Error" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: 'rgba(248,113,113,0.7)', marginTop: 2 }, children: "The exact line where the error originated" })] })] }), (0, jsx_runtime_1.jsx)("div", { style: {
                                                padding: '12px 16px',
                                                background: 'rgba(239,68,68,0.15)',
                                                borderRadius: 8,
                                                border: '1px solid rgba(239,68,68,0.25)',
                                                marginBottom: 12,
                                            }, children: (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 16 }, children: "\uD83D\uDCC2" }), (0, jsx_runtime_1.jsx)("span", { style: { color: '#fca5a5', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }, children: topFrame.file_path }), (0, jsx_runtime_1.jsx)("span", { style: { color: 'rgba(252,165,165,0.5)' }, children: ":" }), (0, jsx_runtime_1.jsxs)("span", { style: {
                                                            color: '#fbbf24',
                                                            fontWeight: 700,
                                                            background: 'rgba(251,191,36,0.2)',
                                                            padding: '3px 10px',
                                                            borderRadius: 5,
                                                            border: '1px solid rgba(251,191,36,0.3)',
                                                        }, children: ["line ", topFrame.line_number] }), topFrame.function_name && ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("span", { style: { color: 'rgba(252,165,165,0.5)' }, children: "in" }), (0, jsx_runtime_1.jsxs)("span", { style: {
                                                                    color: '#818cf8',
                                                                    fontWeight: 700,
                                                                    background: 'rgba(129,140,248,0.15)',
                                                                    padding: '3px 10px',
                                                                    borderRadius: 5,
                                                                    border: '1px solid rgba(129,140,248,0.3)',
                                                                }, children: [topFrame.function_name, "()"] })] }))] }) }), topFrame.code_line && ((0, jsx_runtime_1.jsx)("div", { style: {
                                                background: 'rgba(0,0,0,0.5)',
                                                borderRadius: 8,
                                                padding: '14px',
                                                border: '2px solid rgba(239,68,68,0.3)',
                                            }, children: (0, jsx_runtime_1.jsx)("div", { style: {
                                                    fontFamily: 'ui-monospace, Cascadia Code, Consolas, monospace',
                                                    fontSize: 13,
                                                    lineHeight: 1.6,
                                                    color: '#fef3c7',
                                                    whiteSpace: 'pre',
                                                    overflowX: 'auto',
                                                }, children: topFrame.code_line }) }))] }));
                            })() })) : ((0, jsx_runtime_1.jsx)("pre", { style: {
                                margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
                                lineHeight: 1.8, color: '#fca5a5',
                                background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)',
                                borderRadius: 8, padding: '18px 20px',
                                whiteSpace: 'pre-wrap', wordBreak: 'break-word', minHeight: 140,
                            }, children: getStackTraceDisplayText(data?.error_detail ?? null, data?.parsed_stacktrace ?? null, aiRec?.description ?? null, aiRecommendationText) || 'No stack trace available' }))] })), hasAiContent && ((0, jsx_runtime_1.jsxs)("div", { style: {
                        padding: 16, borderRadius: 10,
                        background: 'rgba(56,189,248,0.07)', border: '1px solid rgba(56,189,248,0.2)',
                    }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }, children: [(0, jsx_runtime_1.jsx)("span", { children: "\uD83E\uDD16" }), (0, jsx_runtime_1.jsx)("span", { style: { ...sectionLabel, color: '#38bdf8', marginBottom: 0 }, children: "AI Recommended Solution" })] }), aiRecommendationText && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', marginBottom: 14 }, children: aiRecommendationText })), aiTopSolution && ((0, jsx_runtime_1.jsxs)("div", { style: {
                                padding: 12, borderRadius: 8,
                                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                            }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }, children: aiTopSolution.solution }), (0, jsx_runtime_1.jsx)(SolutionMeta, { sol: aiTopSolution }), (0, jsx_runtime_1.jsx)("div", { style: { marginTop: 10 }, children: (0, jsx_runtime_1.jsx)("button", { onClick: () => useSolution(aiTopSolution.id), disabled: actionBusy || !aiTopSolution.id, style: { ...btnPrimary, opacity: actionBusy ? 0.6 : 1 }, children: actionBusy ? 'Working…' : 'Use Recommended Solution' }) })] }))] })), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: sectionLabel, children: "\uD83D\uDCA1 Existing Solutions" }), kbSolutions.length === 0 && !kbLoading && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text-muted)', padding: '8px 0' }, children: "No solutions yet for this error." })), kbSolutions.map(sol => renderSolutionCard(sol, {
                            highlight: false,
                            showImprove: true,
                            showDelete: true,
                        })), kbLoading && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }, children: "Loading\u2026" })), hasMoreKb && !kbLoading && ((0, jsx_runtime_1.jsxs)("button", { onClick: () => loadKbPage(kbOffset, data), style: { ...btnSecondary, marginTop: 4 }, children: ["Load More (", kbTotal - kbOffset, " remaining)"] }))] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: sectionLabel, children: improveTargetId ? '✏️ Improve Solution' : '✏️ Create New Solution' }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }, children: improveTargetId
                                ? 'Edit the solution below. Saving will create a new version of this solution only.'
                                : 'Type a fix below. Saving will auto-resolve this error and update usage/confidence. Duplicate detection runs before saving — you will be prompted if a similar solution exists.' }), (0, jsx_runtime_1.jsx)("textarea", { id: "airbrake-solution-editor", value: editorText, onChange: e => setEditorText(e.target.value), placeholder: "Describe the root cause and fix for this error\u2026", rows: 5, style: {
                                width: '100%', background: 'var(--input-bg)', border: '1px solid var(--input-border)',
                                borderRadius: 8, color: 'var(--text)', padding: 12, fontSize: 13,
                                lineHeight: 1.6, resize: 'vertical', outline: 'none', fontFamily: 'inherit',
                                boxSizing: 'border-box',
                            } }), editorError && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: '#f87171', marginTop: 6 }, children: editorError })), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }, children: [improveTargetId && ((0, jsx_runtime_1.jsx)("button", { onClick: handleCancelImprove, style: btnSecondary, children: "Cancel" })), (0, jsx_runtime_1.jsx)("button", { onClick: () => handleSave(false), disabled: editorSaving || !editorText.trim(), style: {
                                        ...btnPrimary,
                                        opacity: editorSaving || !editorText.trim() ? 0.45 : 1,
                                        cursor: editorSaving || !editorText.trim() ? 'not-allowed' : 'pointer',
                                    }, children: editorSaving ? 'Saving…' : improveTargetId ? 'Save Improved Version' : 'Save Solution' }), (!jiraTicket && jiraStatus !== 'created') ? ((0, jsx_runtime_1.jsxs)("button", { onClick: handleCreateJiraTicket, disabled: jiraStatus === 'creating', title: jiraConnected === false ? 'Connect your Jira account to create tickets' : 'Create a Jira ticket from this error', style: {
                                        ...btnPrimary,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: 8,
                                        opacity: jiraStatus === 'creating' ? 0.6 : 1,
                                        cursor: jiraStatus === 'creating' ? 'not-allowed' : 'pointer',
                                    }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 14 }, children: "\uD83C\uDFAB" }), jiraStatus === 'creating'
                                            ? 'Creating…'
                                            : jiraConnected === false
                                                ? 'Connect Jira'
                                                : 'Create Jira Ticket'] })) : (
                                /* ── Ticket created confirmation ───────────────────────────── */
                                (0, jsx_runtime_1.jsxs)("a", { href: jiraTicket?.url ?? '#', target: "_blank", rel: "noopener noreferrer", style: {
                                        ...btnSecondary,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: 6,
                                        textDecoration: 'none',
                                        color: '#34d399',
                                        borderColor: 'rgba(52,211,153,0.35)',
                                        background: 'rgba(52,211,153,0.08)',
                                    }, children: [(0, jsx_runtime_1.jsx)("span", { children: "\u2713" }), (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 700 }, children: "Ticket Created" }), (0, jsx_runtime_1.jsx)("span", { style: { color: '#818cf8' }, children: jiraTicket?.key }), (0, jsx_runtime_1.jsx)("span", { style: { fontSize: 10, opacity: 0.6 }, children: "\u2197" })] })), jiraStatus === 'error' && jiraError && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#f87171', marginTop: 4, width: '100%', textAlign: 'right' }, children: jiraError }))] })] }), actionError && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, color: '#f87171', padding: '8px 12px', borderRadius: 6, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }, children: actionError })), duplicatePrompt && ((0, jsx_runtime_1.jsx)("div", { style: {
                        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100, padding: 24,
                    }, children: (0, jsx_runtime_1.jsxs)("div", { style: {
                            width: '100%', maxWidth: 480, background: 'var(--surface)',
                            border: '1px solid var(--card-border)', borderRadius: 12, padding: 20,
                            boxShadow: '0 16px 40px rgba(0,0,0,0.4)',
                        }, children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, fontWeight: 700, color: '#818cf8', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }, children: "Similar Solution Found" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }, children: "A very similar solution already exists in the knowledge base." }), (0, jsx_runtime_1.jsxs)("div", { style: { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 14 }, children: [(0, jsx_runtime_1.jsx)("div", { style: { marginBottom: 8, color: 'var(--text)', whiteSpace: 'pre-wrap' }, children: duplicatePrompt.solution }), duplicatePrompt.confidence_score != null && (0, jsx_runtime_1.jsxs)("div", { children: ["Confidence: ", duplicatePrompt.confidence_score.toFixed(1), "%"] }), duplicatePrompt.usage_count != null && (0, jsx_runtime_1.jsxs)("div", { children: ["Used ", duplicatePrompt.usage_count, "\u00D7"] }), duplicatePrompt.version != null && (0, jsx_runtime_1.jsxs)("div", { children: ["Version v", duplicatePrompt.version] }), duplicatePrompt.created_by && (0, jsx_runtime_1.jsxs)("div", { children: ["By ", duplicatePrompt.created_by] })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', justifyContent: 'flex-end', gap: 8 }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: handleUseDuplicate, style: btnPrimary, children: "Use Existing" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => handleSave(true), style: btnSecondary, children: "Create Anyway" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setDuplicatePrompt(null), style: btnDanger, children: "Cancel" })] })] }) }))] }));
    }
    // ── MAIN RENDER ───────────────────────────────────────────────────────────
    const statusColor = isResolved ? '#34d399' : isReopened ? '#f87171' : '#818cf8';
    const statusLabel = isResolved ? '✓ Resolved' : isReopened ? '↺ Reopened' : '● Open';
    const content = ((0, jsx_runtime_1.jsxs)("div", { style: {
            display: 'flex', flexDirection: 'column', minHeight: '100%',
            background: 'var(--surface)', border: '1px solid var(--card-border)',
            borderRadius: 14, width: '100%', maxWidth: 900,
            boxShadow: '0 24px 60px rgba(0,0,0,0.35)', overflow: 'hidden',
        }, children: [(0, jsx_runtime_1.jsxs)("div", { style: {
                    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                    padding: '20px 26px', borderBottom: '1px solid var(--card-border)',
                }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { flex: 1, minWidth: 0 }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }, children: "Error Details" }), (0, jsx_runtime_1.jsx)("span", { style: {
                                            fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 99,
                                            background: isResolved ? 'rgba(52,211,153,0.12)' : isReopened ? 'rgba(248,113,113,0.12)' : 'rgba(99,102,241,0.12)',
                                            color: statusColor, border: `1px solid ${statusColor}40`,
                                        }, children: statusLabel }), data?.status && data.status !== 'new' && ((0, jsx_runtime_1.jsx)("span", { style: {
                                            fontSize: 11, fontWeight: 600, padding: '2px 10px', borderRadius: 99,
                                            background: data.status === 'regression' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)',
                                            color: data.status === 'regression' ? '#f87171' : '#fbbf24',
                                            border: `1px solid ${data.status === 'regression' ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
                                        }, children: data.status === 'regression' ? '⚠ Regression' : '◎ Recurring' }))] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexWrap: 'wrap', gap: 16 }, children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }, children: "Project" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, fontWeight: 600, color: '#818cf8' }, children: projectName || '—' })] }), data?.file_name && ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }, children: "File" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 12, fontFamily: 'ui-monospace,monospace', color: 'var(--text)' }, children: data.file_name })] })), data?.occurrence_count != null && ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }, children: "Occurrences" }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 13, color: 'var(--text)' }, children: data.occurrence_count })] }))] })] }), (0, jsx_runtime_1.jsx)("button", { onClick: onClose, style: {
                            background: 'rgba(255,255,255,0.06)', border: '1px solid var(--card-border)',
                            color: 'var(--text-muted)', fontSize: 16, cursor: 'pointer',
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0, marginLeft: 16,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }, children: "\u2715" })] }), (0, jsx_runtime_1.jsx)("div", { style: { overflow: 'auto', padding: '22px 26px', flex: 1 }, children: isResolved ? renderResolved() : renderOpen() }), (0, jsx_runtime_1.jsx)("div", { style: {
                    padding: '14px 26px', borderTop: '1px solid var(--card-border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12,
                }, children: isResolved && ((0, jsx_runtime_1.jsx)("button", { onClick: handleReopen, disabled: actionBusy, style: {
                        ...btnDanger, padding: '8px 20px', fontSize: 13,
                        opacity: actionBusy ? 0.7 : 1,
                        cursor: actionBusy ? 'not-allowed' : 'pointer',
                    }, children: actionBusy ? 'Working…' : '↺ Reopen Error' })) })] }));
    if (isModal) {
        return ((0, jsx_runtime_1.jsx)("div", { onClick: onClose, style: {
                position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
                backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center',
                justifyContent: 'center', zIndex: 1000, padding: 24,
            }, children: (0, jsx_runtime_1.jsx)("div", { onClick: e => e.stopPropagation(), style: { width: '100%', maxWidth: 820, maxHeight: '90vh', display: 'flex', flexDirection: 'column' }, children: content }) }));
    }
    return ((0, jsx_runtime_1.jsx)("div", { style: { padding: '40px 16px', minHeight: '100vh' }, children: content }));
}
//# sourceMappingURL=ErrorDetailModal.js.map