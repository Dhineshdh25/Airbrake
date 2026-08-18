import { useEffect, useState, type CSSProperties } from 'react';
import { apiFetch, ApiError, buildAirbrakeErrorUrl } from '../lib/api';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ErrorRow {
  project: string;
  file_name: string | null;
  error: string;
  error_hash?: string | null;
  error_detail?: string | null;
  timestamp: string | null;
  error_group_name?: string | null;
  error_group_id?: string | null;
  representative_id?: string | null;  // specific log row id — used for single-row resolve/reopen
}

interface Occurrence {
  id?: string | null;
  file_name: string | null;
  timestamp: string | null;
  failure_count: number;
  occurrence_number?: number | null;
}

interface SolutionData {
  id: string | null;
  solution: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  created_by?: string | null;
  version?: number | null;
  confidence_score?: number | null;
  usage_count?: number | null;
}

interface KbSolution {
  id: string | null;
  solution: string | null;
  created_by: string | null;
  created_at: string | null;
  confidence_score: number | null;
  usage_count: number | null;
  version: number | null;
  log_ref_id?: string | null;
  match_source?: string | null;  // "exact_match" | "same_group:<name>" | "semantic_similarity"
}

interface AiRecommendation {
  recommendation: string | null;
  description: string | null;
  solutions: KbSolution[];
}

interface StackFrame {
  file_path: string;
  line_number: number;
  function_name?: string | null;
  code_line?: string | null;
  column?: number | null;
}

interface ParsedStackTrace {
  frames: StackFrame[];
  raw_trace: string;
}

interface DuplicatePromptState {
  solution_id: string;
  solution: string;
  decision: string | null;
  similarity: number | null;
  version: number | null;
  confidence_score: number | null;
  usage_count: number | null;
  created_by: string | null;
  created_at: string | null;
}

interface ErrorDetailData {
  project_name: string;
  file_name?: string | null;
  error_message: string;
  error_detail: string | null;
  parsed_stacktrace?: ParsedStackTrace | null;
  error_hash: string;
  error_group_name?: string | null;
  occurrence_count: number;      // sequence number of THIS specific occurrence
  total_occurrences?: number;    // total rows sharing this error (shown in Error Details only)
  first_seen: string | null;
  last_seen: string | null;
  status: 'new' | 'existing' | 'regression';
  error_status?: string | null;
  resolved_at?: string | null;
  reopened_at?: string | null;
  occurrences: Occurrence[];
  solution: SolutionData | null;
  ai_recommendation?: AiRecommendation | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(ts: string | null | undefined) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

export function getTraceDisplayText(
  _errorDetail: string | null | undefined,
  solutionText: string | null | undefined,
) {
  return solutionText?.trim() || null;
}

export function getStackTraceDisplayText(
  errorDetail: string | null | undefined,
  parsedStacktrace?: ParsedStackTrace | null,
  aiDescription?: string | null,
  aiRecommendation?: string | null,
) {
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

const btnPrimary: CSSProperties = {
  padding: '7px 16px', borderRadius: 6, fontSize: 12, fontWeight: 600,
  background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer',
};
const btnSecondary: CSSProperties = {
  padding: '7px 14px', borderRadius: 6, fontSize: 12,
  background: 'transparent', color: 'var(--text-muted)',
  border: '1px solid var(--card-border)', cursor: 'pointer',
};
const btnDanger: CSSProperties = {
  padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
  background: 'rgba(239,68,68,0.1)', color: '#f87171',
  border: '1px solid rgba(239,68,68,0.25)', cursor: 'pointer',
};
const metaRow: CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: 12,
  fontSize: 11, color: 'var(--text-muted)', marginTop: 8,
};
const sectionLabel: CSSProperties = {
  fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
  letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 10,
};

// ── Confidence bar ────────────────────────────────────────────────────────────

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color = pct >= 80 ? '#34d399' : pct >= 50 ? '#fbbf24' : '#f87171';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        display: 'inline-block', width: 60, height: 5, borderRadius: 3,
        background: 'rgba(255,255,255,0.1)', overflow: 'hidden',
      }}>
        <span style={{ display: 'block', width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </span>
      <span style={{ color, fontWeight: 600 }}>{pct.toFixed(0)}%</span>
    </span>
  );
}

// ── Solution meta line ────────────────────────────────────────────────────────

function SolutionMeta({ sol }: { sol: SolutionData | KbSolution }) {
  return (
    <div style={metaRow}>
      {sol.version != null && <span>v{sol.version}</span>}
      {sol.confidence_score != null && (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Confidence: <ConfidenceBar score={sol.confidence_score} />
        </span>
      )}
      {sol.usage_count != null && <span>Used {sol.usage_count}×</span>}
      {sol.created_by && <span>By {sol.created_by}</span>}
      {sol.created_at && <span>{fmt(sol.created_at)}</span>}
    </div>
  );
}

// ── Parsed Stack Trace ────────────────────────────────────────────────────────

function ParsedStackTraceView({ parsedTrace }: { parsedTrace: ParsedStackTrace }) {
  if (!parsedTrace.frames || parsedTrace.frames.length === 0) {
    return (
      <pre style={{
        margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
        lineHeight: 1.8, color: '#fca5a5',
        background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)',
        borderRadius: 8, padding: '18px 20px',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', minHeight: 140,
      }}>
        {parsedTrace.raw_trace}
      </pre>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {parsedTrace.frames.map((frame, idx) => (
        <div key={idx} style={{
          background: 'rgba(239,68,68,0.04)', border: '1px solid rgba(239,68,68,0.12)',
          borderRadius: 8, overflow: 'hidden',
        }}>
          <div style={{
            padding: '10px 14px', background: 'rgba(239,68,68,0.06)',
            borderBottom: '1px solid rgba(239,68,68,0.12)',
            display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
          }}>
            <span style={{ color: '#fca5a5', fontWeight: 600 }}>{frame.file_path}</span>
            <span style={{ color: 'rgba(252,165,165,0.5)' }}>:</span>
            <span style={{ color: '#fbbf24', fontWeight: 600 }}>line {frame.line_number}</span>
            {frame.column != null && (
              <><span style={{ color: 'rgba(252,165,165,0.5)' }}>:</span>
                <span style={{ color: '#fbbf24' }}>col {frame.column}</span></>
            )}
            {frame.function_name && (
              <><span style={{ color: 'rgba(252,165,165,0.5)', marginLeft: 4 }}>in</span>
                <span style={{ color: '#818cf8', fontWeight: 600 }}>{frame.function_name}</span></>
            )}
          </div>
          {frame.code_line ? (
            <div style={{ padding: '12px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <span style={{
                  color: 'rgba(252,165,165,0.4)', fontSize: 11, fontFamily: 'ui-monospace, monospace',
                  minWidth: 32, textAlign: 'right', paddingTop: 2, userSelect: 'none',
                }}>{frame.line_number}</span>
                <pre style={{
                  margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
                  lineHeight: 1.6, color: '#fca5a5', whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word', flex: 1,
                }}>{frame.code_line}</pre>
              </div>
            </div>
          ) : (
            <div style={{ padding: '12px 14px', fontSize: 11, color: 'rgba(252,165,165,0.5)' }}>
              <span style={{ fontStyle: 'italic' }}>Source code not available</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ErrorDetailModal({
  row, errorHash, projectName: projectNameProp, onClose, onRefresh,
}: {
  row?: ErrorRow;
  errorHash?: string;
  projectName?: string;
  onClose: () => void;
  /** Called after a resolve/reopen so the parent list can re-fetch. */
  onRefresh?: () => void;
}) {
  const effectiveErrorHash = row?.error_hash || errorHash;
  const isModal = !!row;

  // ── Remote data ──────────────────────────────────────────────────────────
  const [data, setData] = useState<ErrorDetailData | null>(null);
  const [loading, setLoading] = useState(!!effectiveErrorHash);
  const [notFound, setNotFound] = useState(false);

  // ── Paginated KB solutions ───────────────────────────────────────────────
  const [kbSolutions, setKbSolutions] = useState<KbSolution[]>([]);
  const [kbTotal, setKbTotal] = useState(0);
  const [kbOffset, setKbOffset] = useState(0);
  const [kbLoading, setKbLoading] = useState(false);
  const KB_PAGE = 5;

  // ── Versions panel ───────────────────────────────────────────────────────
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [versions, setVersions] = useState<KbSolution[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(false);

  // ── Editor ───────────────────────────────────────────────────────────────
  const [editorText, setEditorText] = useState('');
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorError, setEditorError] = useState('');
  const [duplicatePrompt, setDuplicatePrompt] = useState<DuplicatePromptState | null>(null);
  /** When the user clicks Improve on a card, we store its id here so the
   *  save payload can carry base_solution_id to the backend.  null means
   *  the editor is in Create New mode. */
  const [improveTargetId, setImproveTargetId] = useState<string | null>(null);

  // ── Action state ─────────────────────────────────────────────────────────
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');

  // ── Jira ticket state ─────────────────────────────────────────────────────
  const [jiraStatus, setJiraStatus]     = useState<'idle' | 'creating' | 'created' | 'error'>('idle');
  const [jiraTicket, setJiraTicket]     = useState<{ key: string; url: string } | null>(null);
  const [jiraError,  setJiraError]      = useState('');
  const [jiraConnected, setJiraConnected] = useState<boolean | null>(null); // null = unknown

  // ── The specific log row id to target for resolve/reopen ─────────────────
  // When opened from BreaksList, row.representative_id is the most-recent
  // open log row id from the grouped query.
  const targetLogId: string | null = row?.representative_id ?? null;

  // ── Derived ──────────────────────────────────────────────────────────────
  const projectName = data?.project_name ?? row?.project ?? projectNameProp ?? '';
  const errorMessage = data?.error_message ?? row?.error ?? '';
  const errorStatus = data?.error_status ?? null;

  // The resolved log ID for Jira operations — only set when a specific
  // occurrence was selected (navigated from BreaksList).
  // If null, "Create Jira Ticket" is disabled — you must open a specific
  // occurrence from the Breaks list to create a ticket for it.
  const resolvedLogId: string | null = targetLogId;

  const isResolved = errorStatus === 'resolved';
  const isReopened = errorStatus === 'reopened';

  // The solution stored on the error row (used/previously used)
  const activeSolution = data?.solution ?? null;

  // AI recommendation: top solution from ai_recommendation.solutions, sorted by confidence then usage
  const aiRec = data?.ai_recommendation ?? null;
  const aiText = aiRec?.recommendation ?? null;
  // Pick the single best AI-recommended solution to display (highest confidence → usage)
  const aiTopSolution: KbSolution | null = (() => {
    const sols = (aiRec?.solutions ?? []).filter(s => s?.solution);
    if (sols.length === 0) return null;
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
    if (!effectiveErrorHash) return;
    setLoading(true);
    // Build query string — always include project_name when available,
    // and log_id (the specific row id) so the backend returns the status
    // of this exact occurrence rather than the aggregate across all rows
    // sharing the same error_hash.
    const qsParams = new URLSearchParams();
    if (projectNameProp) qsParams.set('project_name', projectNameProp);
    if (targetLogId) qsParams.set('log_id', targetLogId);
    const qs = qsParams.toString() ? `?${qsParams.toString()}` : '';
    apiFetch(`/api/breaks/detail/${encodeURIComponent(effectiveErrorHash)}${qs}`)
      .then(r => { if (!r.ok) throw r; return r.json(); })
      .then((d: ErrorDetailData) => {
        setData(d);
        setNotFound(false);
        // If the backend reports an existing Jira ticket for this error,
        // surface it immediately so the Create button can be disabled.
        try {
          const anyd: any = d as any;
          if (anyd.jira_ticket && anyd.jira_ticket.key) {
            setJiraTicket({ key: anyd.jira_ticket.key, url: anyd.jira_ticket.url });
            setJiraStatus('created');
          }
        } catch (e) {
          // ignore parse errors
        }
        // Reset KB pagination whenever detail reloads
        setKbSolutions([]);
        setKbOffset(0);
        setKbTotal(0);
      })
      .catch(err => { if (err?.status === 404) setNotFound(true); })
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadDetail(); }, [effectiveErrorHash, projectNameProp]);

  // Load first KB page after data arrives (only for open/reopened states)
  useEffect(() => {
    if (!data || isResolved) return;
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
  function loadKbPage(offset: number, errorData: ErrorDetailData) {
    if (!errorData?.error_message && !errorData?.error_hash) return;
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
    apiFetch(`/api/knowledge_base/top?${qs}`)
      .then(r => r.json())
      .then(j => {
        const sols: KbSolution[] = j.solutions ?? [];
        setKbSolutions(prev => offset === 0 ? sols : [...prev, ...sols]);
        setKbTotal(j.total ?? 0);
        setKbOffset(offset + sols.length);
      })
      .catch(console.error)
      .finally(() => setKbLoading(false));
  }

  async function loadVersions(solutionId: string) {
    if (versionsFor === solutionId) { setVersionsFor(null); return; }
    setLoadingVersions(true);
    try {
      const r = await apiFetch(`/api/knowledge_base/${encodeURIComponent(solutionId)}/versions`);
      const j = await r.json();
      setVersions(j.versions ?? []);
      setVersionsFor(solutionId);
    } finally { setLoadingVersions(false); }
  }

  // ── "Use solution" — resolves in-place, closes modal, refreshes parent ────

  async function useSolution(solutionId: string) {
    if (!effectiveErrorHash || !projectName) return;
    setActionBusy(true);
    setActionError('');
    try {
      const r = await apiFetch('/api/knowledge_base/use', {
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
      if (!r.ok) throw new Error((await r.json()).error ?? 'Failed');
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
    } catch (e) {
      setActionError(e instanceof ApiError ? e.label : String(e));
    } finally { setActionBusy(false); }
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
          ? buildAirbrakeErrorUrl(effectiveErrorHash, projectName)
          : undefined,
      };
      sessionStorage.setItem('jira_pending_ticket', JSON.stringify(pendingContext));

      const r = await apiFetch('/api/jira/initiate', { method: 'POST' });
      const j = await r.json();
      if (j.redirect_url) {
        window.location.href = j.redirect_url;  // navigate to Atlassian — no credentials in URL
      } else {
        setJiraError('Could not start Jira connection. Please try again.');
        setJiraStatus('error');
        sessionStorage.removeItem('jira_pending_ticket');
      }
    } catch {
      setJiraError('Could not start Jira connection. Please try again.');
      setJiraStatus('error');
      sessionStorage.removeItem('jira_pending_ticket');
    }
  }

  // ── Jira: check GLOBAL ticket existence when modal opens ─────────────────
  // This is separate from the OAuth status check. It reads the database for
  // any existing Jira ticket linked to this error_hash — regardless of which
  // user created it. Both User A and User B see the same ticket info.
  useEffect(() => {
    if (!effectiveErrorHash) return;
    // Pass log_id (the specific occurrence) so only THIS occurrence shows a
    // ticket badge — not all occurrences sharing the same error_hash.
    // Fire after data loads so resolvedLogId is available.
    if (!resolvedLogId) return;
    apiFetch(`/api/jira/ticket-status?log_id=${encodeURIComponent(resolvedLogId)}`)
      .then(r => r.json())
      .then((j: { has_ticket: boolean; issue_key?: string; issue_url?: string }) => {
        if (j.has_ticket && j.issue_key) {
          setJiraTicket({ key: j.issue_key, url: j.issue_url ?? '' });
          setJiraStatus('created');
        }
      })
      .catch(() => {/* non-fatal — button stays in default state */});
  }, [effectiveErrorHash, resolvedLogId]);

  // ── Jira: check OAuth connection status when modal opens ──────────────────
  useEffect(() => {
    if (!effectiveErrorHash) return;
    apiFetch('/api/jira/status')
      .then(r => r.json())
      .then((j: { connected: boolean }) => setJiraConnected(j.connected))
      .catch(() => setJiraConnected(false));
  }, [effectiveErrorHash]);

  // ── Jira: create ticket ───────────────────────────────────────────────────
  async function createJiraTicketInternal(errorData?: any) {
    const ticketData = errorData || {
      project_name:      projectName   || undefined,
      error_group:       data?.error_group_name || undefined,
      error_message:     errorMessage  || undefined,
      error_detail:      data?.error_detail     || undefined,
      error_hash:        effectiveErrorHash      || undefined,
      log_id:            resolvedLogId           || undefined,
      occurrence_count:  data?.occurrence_count  ?? undefined,
      status:            data?.error_status      || undefined,
      solution:          data?.solution?.solution || undefined,
      ai_recommendation: data?.ai_recommendation?.recommendation || undefined,
      timestamp:         data?.last_seen         || undefined,
      file_name:         data?.file_name         || undefined,
      airbrake_url:      effectiveErrorHash
        ? buildAirbrakeErrorUrl(effectiveErrorHash, projectName, resolvedLogId)
        : undefined,
    };

    setJiraStatus('creating');
    setJiraError('');
    setJiraTicket(null);

    try {
      const r = await apiFetch('/api/jira/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ticketData),
      });
      const j = await r.json();
      setJiraTicket({ key: j.key, url: j.url });
      setJiraStatus('created');

      // Link this specific occurrence to the Jira ticket.
      // resolvedLogId is always a specific row UUID — never an error_hash.
      // This ensures the ticket badge shows only on THIS occurrence.
      if (j.key && resolvedLogId) {
        apiFetch('/api/jira/link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            log_id:    resolvedLogId,
            issue_key: j.key,
            issue_url: j.url ?? '',
          }),
        }).catch(() => {/* non-fatal */});
      }
    } catch (e: unknown) {
      let msg = 'Failed to create Jira ticket.';
      if (e instanceof ApiError) {
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
  useEffect(() => {
    const pendingStr = sessionStorage.getItem('jira_pending_ticket');
    if (!pendingStr) return;

    // Only auto-retry if we're back on the error detail and Jira is now connected
    if (effectiveErrorHash && jiraConnected === true) {
      try {
        const pending = JSON.parse(pendingStr);
        sessionStorage.removeItem('jira_pending_ticket');
        // Auto-retry with the stored error data
        createJiraTicketInternal(pending);
      } catch (err) {
        console.error('[ErrorDetailModal] Failed to parse pending ticket context:', err);
        sessionStorage.removeItem('jira_pending_ticket');
      }
    }
  }, [jiraConnected, effectiveErrorHash]);

  // ── Reopen ───────────────────────────────────────────────────────────────

  async function handleReopen() {
    if (!effectiveErrorHash || !projectName) return;
    setActionBusy(true);
    setActionError('');
    try {
      const r = await apiFetch('/api/knowledge_base/reopen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          error_hash: effectiveErrorHash,
          project_name: projectName,
          // Target only this specific occurrence.
          ...(targetLogId ? { log_id: targetLogId } : {}),
        }),
      });
      if (!r.ok) throw new Error((await r.json()).error ?? 'Failed');
      onRefresh?.();
      // Reload full detail so KB solutions are fresh and state switches to reopened
      loadDetail();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.label : String(e));
    } finally { setActionBusy(false); }
  }

  // ── Delete solution (entire family) ──────────────────────────────────────

  async function handleDeleteSolution(solutionId: string) {
    if (!effectiveErrorHash) return;
    if (!window.confirm('Delete this solution? This cannot be undone.')) return;
    setActionBusy(true);
    try {
      await apiFetch(
        `/api/knowledge_base/${encodeURIComponent(effectiveErrorHash)}` +
        `?solution_id=${encodeURIComponent(solutionId)}` +
        `&project_name=${encodeURIComponent(projectName)}`,
        { method: 'DELETE' },
      );
      setData(prev => prev ? { ...prev, solution: null } : prev);
      setKbSolutions(prev => prev.filter(s => s.id !== solutionId));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.label : String(e));
    } finally { setActionBusy(false); }
  }

  async function handleDeleteVersion(solutionId: string, versionId: string) {
    try {
      await apiFetch(
        `/api/knowledge_base/${encodeURIComponent(solutionId)}/versions/${encodeURIComponent(versionId)}`,
        { method: 'DELETE' },
      );
      setVersions(prev => prev.filter(v => v.id !== versionId));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.label : String(e));
    }
  }

  // ── Editor: save new / improved solution ─────────────────────────────────

  async function handleSave(forceCreate = false) {
    if (!effectiveErrorHash || !editorText.trim()) return;
    setEditorSaving(true);
    setEditorError('');
    setDuplicatePrompt(null);
    try {
      // 1. Check for duplicates first
      const previewPayload: Record<string, unknown> = {
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
      const previewRes = await apiFetch('/api/knowledge_base', {
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
      const saveRes = await apiFetch('/api/knowledge_base', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...previewPayload, check_only: false }),
      });
      const saved = await saveRes.json();

      // 3. Auto-use (resolve) with the new or found solution id
      const idToUse = saved.duplicate ? saved.solution_id : saved.id;
      if (idToUse) {
        await useSolution(idToUse);
      } else {
        loadDetail();
      }
      setEditorText('');
      setImproveTargetId(null);
    } catch (e) {
      setEditorError(e instanceof ApiError ? e.label : 'Failed to save solution.');
    } finally { setEditorSaving(false); }
  }

  async function handleUseDuplicate() {
    if (!duplicatePrompt) return;
    setDuplicatePrompt(null);
    await useSolution(duplicatePrompt.solution_id);
  }

  // ── Improve: pre-fill editor with existing solution text ─────────────────

  function handleImprove(solutionId: string, solutionText: string) {
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

  if (!effectiveErrorHash) return null;

  if (loading) {
    return (
      <div style={{ padding: isModal ? 0 : '60px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
        Loading error details…
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={{ padding: isModal ? 0 : '60px 0', textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)', fontSize: 16 }}>Error not found.</p>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#818cf8', cursor: 'pointer', fontSize: 13, padding: 0 }}>← Back</button>
      </div>
    );
  }

  // ── Render helpers ────────────────────────────────────────────────────────

  function renderSolutionCard(sol: KbSolution, opts: {
    highlight?: boolean;
    showImprove?: boolean;
    showDelete?: boolean;
  } = {}) {
    const isActiveInVersions = versionsFor === sol.id;
    return (
      <div key={sol.id ?? sol.solution} style={{
        padding: 14, borderRadius: 8,
        background: opts.highlight ? 'rgba(99,102,241,0.08)' : 'rgba(255,255,255,0.03)',
        border: `1px solid ${opts.highlight ? 'rgba(99,102,241,0.25)' : 'var(--card-border)'}`,
        marginBottom: 8,
      }}>
        <div style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {sol.solution}
        </div>
        {sol.match_source && sol.match_source !== 'exact_match' && (
          <div style={{ marginTop: 6 }}>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
              background: sol.match_source.startsWith('same_group')
                ? 'rgba(56,189,248,0.12)' : 'rgba(99,102,241,0.12)',
              color: sol.match_source.startsWith('same_group') ? '#38bdf8' : '#818cf8',
              border: `1px solid ${sol.match_source.startsWith('same_group') ? 'rgba(56,189,248,0.3)' : 'rgba(99,102,241,0.3)'}`,
              letterSpacing: '0.04em',
            }}>
              {sol.match_source.startsWith('same_group')
                ? `✓ Same Group${sol.match_source.includes(':') ? ': ' + sol.match_source.split(':')[1] : ''}`
                : '✓ Similar Error'}
            </span>
          </div>
        )}
        <SolutionMeta sol={sol} />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <button
            onClick={() => useSolution(sol.id!)}
            disabled={actionBusy || !sol.id}
            style={{ ...btnPrimary, opacity: actionBusy ? 0.6 : 1 }}
          >
            {actionBusy ? 'Working…' : 'Use'}
          </button>
          {opts.showImprove && (
            <button onClick={() => handleImprove(sol.id!, sol.solution!)} style={btnSecondary}>Improve</button>
          )}
          {sol.id && (
            <button onClick={() => loadVersions(sol.id!)} disabled={loadingVersions} style={btnSecondary}>
              {loadingVersions && isActiveInVersions ? 'Loading…' : isActiveInVersions ? 'Hide Versions' : 'Versions'}
            </button>
          )}
          {opts.showDelete && sol.id && (
            <button onClick={() => handleDeleteSolution(sol.id!)} disabled={actionBusy} style={btnDanger}>Delete</button>
          )}
        </div>

        {/* Version panel */}
        {isActiveInVersions && (
          <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: 'rgba(0,0,0,0.15)', border: '1px solid var(--card-border)' }}>
            {versions.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No other versions.</div>
            ) : versions.map(v => (
              <div key={v.id} style={{ paddingBottom: 10, marginBottom: 10, borderBottom: '1px solid var(--card-border)' }}>
                <div style={{ fontSize: 12, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{v.solution}</div>
                <SolutionMeta sol={v} />
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button onClick={() => useSolution(v.id!)} disabled={actionBusy || !v.id} style={{ ...btnPrimary, padding: '5px 12px' }}>Use</button>
                  <button onClick={() => handleDeleteVersion(sol.id!, v.id!)} style={{ ...btnDanger, padding: '5px 12px' }}>Delete Version</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── RESOLVED STATE ────────────────────────────────────────────────────────
  // Only shows the solution that was actually used on this specific error row.
  // Does NOT search the KB — reads from data.solution only.

  function renderResolved() {
    const resolvedSolution = activeSolution?.solution ? activeSolution : aiTopSolution;

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Resolved banner */}
        <div style={{
          padding: '14px 18px', borderRadius: 10,
          background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#34d399', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>
            ✓ Resolved
          </div>
          {data?.resolved_at && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Resolved {fmt(data.resolved_at)}</div>
          )}
        </div>

        {/* Raw Error Message */}
        {errorMessage && (
          <div style={{
            padding: 16,
            borderRadius: 10,
            background: 'rgba(239,68,68,0.06)',
            border: '1px solid rgba(239,68,68,0.18)',
          }}>
            <div style={{ ...sectionLabel, color: '#f87171', marginBottom: 8 }}>Raw Error Message</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', lineHeight: 1.5, wordBreak: 'break-word' }}>
              {errorMessage}
            </div>
          </div>
        )}

        {/* Solution used */}
        {resolvedSolution ? (
          <div style={{
            padding: 16, borderRadius: 10,
            background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
          }}>
            <div style={{ ...sectionLabel, color: '#818cf8' }}>💡 Solution Used</div>
            <div style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 6 }}>
              {resolvedSolution.solution}
            </div>
            <div style={metaRow}>
              {resolvedSolution.version != null && <span>v{resolvedSolution.version}</span>}
              {resolvedSolution.confidence_score != null && (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  Confidence: <ConfidenceBar score={resolvedSolution.confidence_score} />
                </span>
              )}
              {resolvedSolution.usage_count != null && <span>Used {resolvedSolution.usage_count}×</span>}
              {resolvedSolution.created_by && <span>Resolved by {resolvedSolution.created_by}</span>}
              {data?.resolved_at && <span>{fmt(data.resolved_at)}</span>}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '12px 0' }}>
            No solution record found for this resolution.
          </div>
        )}

        {actionError && (
          <div style={{ fontSize: 12, color: '#f87171', padding: '8px 12px', borderRadius: 6, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
            {actionError}
          </div>
        )}
      </div>
    );
  }

  // ── OPEN / REOPENED STATE ─────────────────────────────────────────────────

  function renderOpen() {
    const hasMoreKb = kbOffset < kbTotal;

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>

        {/* ── Previously Used Solution (read-only, shown only after reopen) ─ */}
        {isReopened && activeSolution?.solution && (
          <div style={{
            padding: 16, borderRadius: 10,
            background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.18)',
          }}>
            <div style={{ ...sectionLabel, color: '#f87171' }}>🧾 Previously Used Solution</div>
            <div style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 6 }}>
              {activeSolution.solution}
            </div>
            <div style={metaRow}>
              {activeSolution.version != null && <span>v{activeSolution.version}</span>}
              {activeSolution.created_by && <span>Resolved by {activeSolution.created_by}</span>}
              {data?.resolved_at && <span>Resolved {fmt(data.resolved_at)}</span>}
            </div>
            {/* Read-only — no buttons */}
          </div>
        )}

        {errorMessage && (
          <div style={{
            padding: 16,
            borderRadius: 10,
            background: 'rgba(239,68,68,0.06)',
            border: '1px solid rgba(239,68,68,0.18)',
          }}>
            <div style={{ ...sectionLabel, color: '#f87171', marginBottom: 8 }}>Raw Error Message</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', lineHeight: 1.5, wordBreak: 'break-word' }}>
              {errorMessage}
            </div>
          </div>
        )}

        {/* ── 2. Stack Trace ────────────────────────────────────────────────── */}
        {(data?.error_detail || data?.parsed_stacktrace?.raw_trace || aiRec?.description || aiRecommendationText) && (
          <div>
            <div style={sectionLabel}>📋 Stack Trace</div>
            {data?.parsed_stacktrace && data.parsed_stacktrace.frames && data.parsed_stacktrace.frames.length > 0 ? (
              <div>
                {(() => {
                  const topFrame = data.parsed_stacktrace.frames[0];
                  // Check if this is a real source file or just a placeholder
                  const isRealFile = topFrame.file_path &&
                    !['<unknown>', '<string>', '<stdin>', 'unknown'].includes(topFrame.file_path.toLowerCase());

                  // Only show the "Code Line That Caused the Error" section if we have a real file
                  // or if we have actual code content to show
                  if (!isRealFile && !topFrame.code_line) {
                    return null; // Skip this entire section
                  }

                  return (
                    <div style={{
                      padding: '18px 20px', borderRadius: 12,
                      background: 'rgba(239,68,68,0.08)', border: '3px solid rgba(239,68,68,0.3)',
                      boxShadow: '0 4px 12px rgba(239,68,68,0.15)',
                      marginBottom: 16,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                        <span style={{ fontSize: 20 }}>💥</span>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: '#f87171', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                            Code Line That Caused the Error
                          </div>
                          <div style={{ fontSize: 11, color: 'rgba(248,113,113,0.7)', marginTop: 2 }}>
                            The exact line where the error originated
                          </div>
                        </div>
                      </div>

                      {/* File location header */}
                      <div style={{
                        padding: '12px 16px',
                        background: 'rgba(239,68,68,0.15)',
                        borderRadius: 8,
                        border: '1px solid rgba(239,68,68,0.25)',
                        marginBottom: 12,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12 }}>
                          <span style={{ fontSize: 16 }}>📂</span>
                          <span style={{ color: '#fca5a5', fontWeight: 700, fontFamily: 'ui-monospace, monospace' }}>
                            {topFrame.file_path}
                          </span>
                          <span style={{ color: 'rgba(252,165,165,0.5)' }}>:</span>
                          <span style={{
                            color: '#fbbf24',
                            fontWeight: 700,
                            background: 'rgba(251,191,36,0.2)',
                            padding: '3px 10px',
                            borderRadius: 5,
                            border: '1px solid rgba(251,191,36,0.3)',
                          }}>
                            line {topFrame.line_number}
                          </span>
                          {topFrame.function_name && (
                            <>
                              <span style={{ color: 'rgba(252,165,165,0.5)' }}>in</span>
                              <span style={{
                                color: '#818cf8',
                                fontWeight: 700,
                                background: 'rgba(129,140,248,0.15)',
                                padding: '3px 10px',
                                borderRadius: 5,
                                border: '1px solid rgba(129,140,248,0.3)',
                              }}>
                                {topFrame.function_name}()
                              </span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* The problematic code line */}
                      {topFrame.code_line && (
                        <div style={{
                          background: 'rgba(0,0,0,0.5)',
                          borderRadius: 8,
                          padding: '14px',
                          border: '2px solid rgba(239,68,68,0.3)',
                        }}>
                          <div style={{
                            fontFamily: 'ui-monospace, Cascadia Code, Consolas, monospace',
                            fontSize: 13,
                            lineHeight: 1.6,
                            color: '#fef3c7',
                            whiteSpace: 'pre',
                            overflowX: 'auto',
                          }}>
                            {topFrame.code_line}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            ) : (
              <pre style={{
                margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 12,
                lineHeight: 1.8, color: '#fca5a5',
                background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)',
                borderRadius: 8, padding: '18px 20px',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', minHeight: 140,
              }}>
                {getStackTraceDisplayText(
                  data?.error_detail ?? null,
                  data?.parsed_stacktrace ?? null,
                  aiRec?.description ?? null,
                  aiRecommendationText,
                ) || 'No stack trace available'}
              </pre>
            )}
          </div>
        )}

        {/* ── 1. AI Recommended Solution ──────────────────────────────────── */}
        {hasAiContent && (
          <div style={{
            padding: 16, borderRadius: 10,
            background: 'rgba(56,189,248,0.07)', border: '1px solid rgba(56,189,248,0.2)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <span>🤖</span>
              <span style={{ ...sectionLabel, color: '#38bdf8', marginBottom: 0 }}>AI Recommended Solution</span>
            </div>

            {aiRecommendationText && (
              <div style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', marginBottom: 14 }}>
                {aiRecommendationText}
              </div>
            )}

            {/* Single best solution card */}
            {aiTopSolution && (
              <div style={{
                padding: 12, borderRadius: 8,
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
              }}>
                <div style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {aiTopSolution.solution}
                </div>
                <SolutionMeta sol={aiTopSolution} />
                <div style={{ marginTop: 10 }}>
                  {/* Single button — calls the same useSolution endpoint as every other Use button */}
                  <button
                    onClick={() => useSolution(aiTopSolution.id!)}
                    disabled={actionBusy || !aiTopSolution.id}
                    style={{ ...btnPrimary, opacity: actionBusy ? 0.6 : 1 }}
                  >
                    {actionBusy ? 'Working…' : 'Use Recommended Solution'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 3. Existing Solutions (KB) ──────────────────────────────────── */}
        {/* Always shown (not just when solutions exist) so the Load More state
            is visible even while loading the first page. Queried by
            error_hash + project_name, so every occurrence of the same
            project+error sees the same solution pool. */}
        <div>
          <div style={sectionLabel}>💡 Existing Solutions</div>

          {kbSolutions.length === 0 && !kbLoading && (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '8px 0' }}>
              No solutions yet for this error.
            </div>
          )}

          {kbSolutions.map(sol => renderSolutionCard(sol, {
            highlight: false,
            showImprove: true,
            showDelete: true,
          }))}

          {kbLoading && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>Loading…</div>
          )}

          {hasMoreKb && !kbLoading && (
            <button onClick={() => loadKbPage(kbOffset, data!)} style={{ ...btnSecondary, marginTop: 4 }}>
              Load More ({kbTotal - kbOffset} remaining)
            </button>
          )}
        </div>

        {/* ── 4. Create New Solution / Improve ─────────────────────────────── */}
        <div>
          <div style={sectionLabel}>
            {improveTargetId ? '✏️ Improve Solution' : '✏️ Create New Solution'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            {improveTargetId
              ? 'Edit the solution below. Saving will create a new version of this solution only.'
              : 'Type a fix below. Saving will auto-resolve this error and update usage/confidence. Duplicate detection runs before saving — you will be prompted if a similar solution exists.'}
          </div>
          <textarea
            id="airbrake-solution-editor"
            value={editorText}
            onChange={e => setEditorText(e.target.value)}
            placeholder="Describe the root cause and fix for this error…"
            rows={5}
            style={{
              width: '100%', background: 'var(--input-bg)', border: '1px solid var(--input-border)',
              borderRadius: 8, color: 'var(--text)', padding: 12, fontSize: 13,
              lineHeight: 1.6, resize: 'vertical', outline: 'none', fontFamily: 'inherit',
              boxSizing: 'border-box',
            }}
          />
          {editorError && (
            <div style={{ fontSize: 12, color: '#f87171', marginTop: 6 }}>{editorError}</div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
            {improveTargetId && (
              <button
                onClick={handleCancelImprove}
                style={btnSecondary}
              >
                Cancel
              </button>
            )}
            <button
              onClick={() => handleSave(false)}
              disabled={editorSaving || !editorText.trim()}
              style={{
                ...btnPrimary,
                opacity: editorSaving || !editorText.trim() ? 0.45 : 1,
                cursor: editorSaving || !editorText.trim() ? 'not-allowed' : 'pointer',
              }}
            >
              {editorSaving ? 'Saving…' : improveTargetId ? 'Save Improved Version' : 'Save Solution'}
            </button>

            {/* ── Create Jira Ticket ──────────────────────────────────────── */}
            {(!jiraTicket && jiraStatus !== 'created') ? (
              <button
                onClick={handleCreateJiraTicket}
                disabled={jiraStatus === 'creating' || !resolvedLogId}
                title={
                  !resolvedLogId
                    ? 'Open a specific occurrence from the Breaks list to create a ticket'
                    : jiraConnected === false
                      ? 'Connect your Jira account to create tickets'
                      : 'Create a Jira ticket from this error'
                }
                style={{
                  ...btnPrimary,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  opacity: (jiraStatus === 'creating' || !resolvedLogId) ? 0.45 : 1,
                  cursor: (jiraStatus === 'creating' || !resolvedLogId) ? 'not-allowed' : 'pointer',
                }}
              >
                <span style={{ fontSize: 14 }}>🎫</span>
                {jiraStatus === 'creating'
                  ? 'Creating…'
                  : !resolvedLogId
                    ? 'Select an occurrence'
                    : jiraConnected === false
                      ? 'Connect Jira'
                      : 'Create Jira Ticket'}
              </button>
            ) : (
              /* ── Ticket created confirmation ───────────────────────────── */
              <a
                href={jiraTicket?.url ?? '#'}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  ...btnSecondary,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  textDecoration: 'none',
                  color: '#34d399',
                  borderColor: 'rgba(52,211,153,0.35)',
                  background: 'rgba(52,211,153,0.08)',
                }}
              >
                <span>✓</span>
                <span style={{ fontWeight: 700 }}>Ticket Created</span>
                <span style={{ color: '#818cf8' }}>{jiraTicket?.key}</span>
                <span style={{ fontSize: 10, opacity: 0.6 }}>↗</span>
              </a>
            )}
            {jiraStatus === 'error' && jiraError && (
              <div style={{ fontSize: 11, color: '#f87171', marginTop: 4, width: '100%', textAlign: 'right' }}>
                {jiraError}
              </div>
            )}
          </div>
        </div>

        {actionError && (
          <div style={{ fontSize: 12, color: '#f87171', padding: '8px 12px', borderRadius: 6, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
            {actionError}
          </div>
        )}

        {/* ── Duplicate detection overlay ───────────────────────────────────── */}
        {duplicatePrompt && (
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100, padding: 24,
          }}>
            <div style={{
              width: '100%', maxWidth: 480, background: 'var(--surface)',
              border: '1px solid var(--card-border)', borderRadius: 12, padding: 20,
              boxShadow: '0 16px 40px rgba(0,0,0,0.4)',
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#818cf8', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
                Similar Solution Found
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>
                A very similar solution already exists in the knowledge base.
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 14 }}>
                <div style={{ marginBottom: 8, color: 'var(--text)', whiteSpace: 'pre-wrap' }}>{duplicatePrompt.solution}</div>
                {duplicatePrompt.confidence_score != null && <div>Confidence: {duplicatePrompt.confidence_score.toFixed(1)}%</div>}
                {duplicatePrompt.usage_count != null && <div>Used {duplicatePrompt.usage_count}×</div>}
                {duplicatePrompt.version != null && <div>Version v{duplicatePrompt.version}</div>}
                {duplicatePrompt.created_by && <div>By {duplicatePrompt.created_by}</div>}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button onClick={handleUseDuplicate} style={btnPrimary}>Use Existing</button>
                <button onClick={() => handleSave(true)} style={btnSecondary}>Create Anyway</button>
                <button onClick={() => setDuplicatePrompt(null)} style={btnDanger}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── MAIN RENDER ───────────────────────────────────────────────────────────

  const statusColor = isResolved ? '#34d399' : isReopened ? '#f87171' : '#818cf8';
  const statusLabel = isResolved ? '✓ Resolved' : isReopened ? '↺ Reopened' : '● Open';

  const content = (
    <div style={{
      display: 'flex', flexDirection: 'column', minHeight: '100%',
      background: 'var(--surface)', border: '1px solid var(--card-border)',
      borderRadius: 14, width: '100%', maxWidth: 900,
      boxShadow: '0 24px 60px rgba(0,0,0,0.35)', overflow: 'hidden',
    }}>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        padding: '20px 26px', borderBottom: '1px solid var(--card-border)',
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Error Details
            </span>
            <span style={{
              fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 99,
              background: isResolved ? 'rgba(52,211,153,0.12)' : isReopened ? 'rgba(248,113,113,0.12)' : 'rgba(99,102,241,0.12)',
              color: statusColor, border: `1px solid ${statusColor}40`,
            }}>
              {statusLabel}
            </span>
            {data?.status && data.status !== 'new' && (
              <span style={{
                fontSize: 11, fontWeight: 600, padding: '2px 10px', borderRadius: 99,
                background: data.status === 'regression' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)',
                color: data.status === 'regression' ? '#f87171' : '#fbbf24',
                border: `1px solid ${data.status === 'regression' ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
              }}>
                {data.status === 'regression' ? '⚠ Regression' : '◎ Recurring'}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Project</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#818cf8' }}>{projectName || '—'}</div>
            </div>
            {data?.file_name && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>File</div>
                <div style={{ fontSize: 12, fontFamily: 'ui-monospace,monospace', color: 'var(--text)' }}>{data.file_name}</div>
              </div>
            )}
            {data?.occurrence_count != null && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Occurrence</div>
                <div style={{ fontSize: 13, color: 'var(--text)' }}>
                  #{data.occurrence_count}
                  {data.total_occurrences != null && data.total_occurrences !== data.occurrence_count && (
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                      {' '}of {data.total_occurrences}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'rgba(255,255,255,0.06)', border: '1px solid var(--card-border)',
            color: 'var(--text-muted)', fontSize: 16, cursor: 'pointer',
            width: 32, height: 32, borderRadius: 8, flexShrink: 0, marginLeft: 16,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >✕</button>
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <div style={{ overflow: 'auto', padding: '22px 26px', flex: 1 }}>
        {isResolved ? renderResolved() : renderOpen()}
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div style={{
        padding: '14px 26px', borderTop: '1px solid var(--card-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12,
      }}>
        {isResolved && (
          <button
            onClick={handleReopen}
            disabled={actionBusy}
            style={{
              ...btnDanger, padding: '8px 20px', fontSize: 13,
              opacity: actionBusy ? 0.7 : 1,
              cursor: actionBusy ? 'not-allowed' : 'pointer',
            }}
          >
            {actionBusy ? 'Working…' : '↺ Reopen Error'}
          </button>
        )}
      </div>
    </div>
  );

  if (isModal) {
    return (
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 1000, padding: 24,
        }}
      >
        <div
          onClick={e => e.stopPropagation()}
          style={{ width: '100%', maxWidth: 820, maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
        >
          {content}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: '40px 16px', minHeight: '100vh' }}>
      {content}
    </div>
  );
}
