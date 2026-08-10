/**
 * JiraOverview — Jira tickets dashboard.
 *
 * Fetches all Jira issues visible to the connected account via
 * GET /api/jira/search?jql=...
 * Reuses existing OAuth integration — no new auth logic.
 *
 * Columns: Issue Key | Summary | Project | Status | Priority | Assignee | Created | Updated | Actions
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '../lib/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface JiraUser {
  displayName?: string;
  emailAddress?: string;
  accountId?: string;
}

interface JiraIssue {
  id: string;
  key: string;
  self?: string;
  fields: {
    summary?: string;
    status?: { name?: string; statusCategory?: { colorName?: string } };
    priority?: { name?: string; iconUrl?: string };
    assignee?: JiraUser | null;
    reporter?: JiraUser | null;
    project?: { name?: string; key?: string };
    issuetype?: { name?: string; iconUrl?: string };
    labels?: string[];
    created?: string;
    updated?: string;
    description?: unknown;
  };
}

interface SearchResponse {
  issues: JiraIssue[];
  isLast?: boolean;
  nextPageToken?: string | null;
  total?: number;
  error?: string;
  needs_auth?: boolean;
  message?: string;
  site_url?: string;
}

type SortKey = 'updated' | 'created' | 'priority' | 'status';
type SortDir = 'asc' | 'desc';

const PRIORITY_ORDER: Record<string, number> = {
  Highest: 0, Critical: 0,
  High: 1,
  Medium: 2,
  Low: 3,
  Lowest: 4, Trivial: 4,
};

const TERMINAL_STATUSES = new Set(['done', 'closed', 'resolved', 'fixed', 'complete', 'completed']);

// 30-second in-memory cache — keyed by JQL string
const _cache: Map<string, { ts: number; data: SearchResponse }> = new Map();
const CACHE_TTL_MS = 30_000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function statusColor(name: string | undefined): string {
  const n = (name ?? '').toLowerCase();
  if (TERMINAL_STATUSES.has(n)) return '#34d399';
  if (['in progress', 'in review', 'in development'].some(s => n.includes(s))) return '#fbbf24';
  return '#818cf8';
}

function priorityColor(name: string | undefined): string {
  const n = (name ?? '').toLowerCase();
  if (n.includes('highest') || n.includes('critical')) return '#ef4444';
  if (n.includes('high')) return '#f87171';
  if (n.includes('medium')) return '#fbbf24';
  if (n.includes('low')) return '#60a5fa';
  return 'var(--text-muted)';
}

function browseUrl(issue: JiraIssue, siteUrl: string): string {
  if (!siteUrl || !issue.key) {
    console.warn('[Jira] Missing siteUrl or issue.key:', { siteUrl, key: issue.key });
    return `#${issue.key || 'unknown'}`;
  }
  // Remove trailing slash from siteUrl if present
  const baseUrl = siteUrl.replace(/\/$/, '');
  return `${baseUrl}/browse/${issue.key}`;
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const SELECT_STYLE: React.CSSProperties = {
  background: 'var(--input-bg)',
  border: '1px solid var(--input-border)',
  borderRadius: 6,
  color: 'var(--text)',
  padding: '7px 10px',
  fontSize: 12,
  outline: 'none',
  cursor: 'pointer',
};

const INPUT_STYLE: React.CSSProperties = {
  ...SELECT_STYLE,
  minWidth: 200,
};

const TH_STYLE: React.CSSProperties = {
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

const TD_STYLE: React.CSSProperties = {
  padding: '10px 14px',
  fontSize: 13,
  verticalAlign: 'middle',
  borderBottom: '1px solid var(--card-border)',
};

// ── Component ─────────────────────────────────────────────────────────────────

export function JiraOverview() {
  // ── Remote data ──────────────────────────────────────────────────────────
  const [issues, setIssues] = useState<JiraIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notConnected, setNotConnected] = useState(false);
  const [jiraSiteUrl, setJiraSiteUrl] = useState('');
  const [reloadTick, setReloadTick] = useState(0);
  const bypassCache = useRef(false);

  // ── Filter / sort / search state ─────────────────────────────────────────
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [assigneeFilter, setAssigneeFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('updated');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // ── Derived filter options ────────────────────────────────────────────────
  const projectOptions = useMemo(() =>
    [...new Set(issues.map(i => i.fields?.project?.name ?? '').filter(Boolean))].sort(),
    [issues]);

  const statusOptions = useMemo(() =>
    [...new Set(issues.map(i => i.fields?.status?.name ?? '').filter(Boolean))].sort(),
    [issues]);

  const priorityOptions = useMemo(() =>
    [...new Set(issues.map(i => i.fields?.priority?.name ?? '').filter(Boolean))].sort(),
    [issues]);

  const assigneeOptions = useMemo(() =>
    [...new Set(issues.map(i => i.fields?.assignee?.displayName ?? '').filter(Boolean))].sort(),
    [issues]);

  // ── Filtered + sorted rows ────────────────────────────────────────────────
  const visible = useMemo(() => {
    console.log('[Jira useMemo] Computing visible rows from', issues.length, 'issues');

    let rows = [...issues]; // Create a copy to avoid mutating original
    const q = search.toLowerCase().trim();

    if (q) rows = rows.filter(i =>
      i.key.toLowerCase().includes(q) ||
      (i.fields?.summary ?? '').toLowerCase().includes(q)
    );
    if (projectFilter) rows = rows.filter(i => (i.fields?.project?.name ?? '') === projectFilter);
    if (statusFilter) rows = rows.filter(i => (i.fields?.status?.name ?? '') === statusFilter);
    if (priorityFilter) rows = rows.filter(i => (i.fields?.priority?.name ?? '') === priorityFilter);
    if (assigneeFilter) rows = rows.filter(i => (i.fields?.assignee?.displayName ?? '') === assigneeFilter);

    rows = rows.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'updated') {
        cmp = (a.fields?.updated ?? '') < (b.fields?.updated ?? '') ? -1 : 1;
      } else if (sortKey === 'created') {
        cmp = (a.fields?.created ?? '') < (b.fields?.created ?? '') ? -1 : 1;
      } else if (sortKey === 'status') {
        cmp = (a.fields?.status?.name ?? '') < (b.fields?.status?.name ?? '') ? -1 : 1;
      } else if (sortKey === 'priority') {
        const pa = PRIORITY_ORDER[a.fields?.priority?.name ?? ''] ?? 99;
        const pb = PRIORITY_ORDER[b.fields?.priority?.name ?? ''] ?? 99;
        cmp = pa - pb;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

    console.log('[Jira useMemo] Visible rows computed:', rows.length);
    return rows;
  }, [issues, search, projectFilter, statusFilter, priorityFilter, assigneeFilter, sortKey, sortDir]);

  // ── Fetch ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setNotConnected(false);

    const cacheKey = 'default-search';
    const cached = _cache.get(cacheKey);
    const useCache = !bypassCache.current && cached && (Date.now() - cached.ts < CACHE_TTL_MS);
    bypassCache.current = false;

    const doFetch = useCache
      ? Promise.resolve(cached!.data)
      : apiFetch('/api/jira/search?maxResults=200')
        .then(r => r.json() as Promise<SearchResponse>)
        .then(data => { _cache.set(cacheKey, { ts: Date.now(), data }); return data; });

    doFetch
      .then((data: SearchResponse) => {
        console.log('[Jira] Raw API response:', data);

        if (cancelled) return;

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

        const list: JiraIssue[] = issuesArray;
        console.log('[Jira] Setting issues state:', list.length, 'issues');
        console.log('[Jira] First issue sample:', list[0]);

        // Store Jira site URL from API response
        if (data.site_url) {
          setJiraSiteUrl(data.site_url);
          console.log('[Jira] Jira site URL from API:', data.site_url);
        } else {
          console.warn('[Jira] No site_url in API response');
        }

        console.log('[Jira] About to call setIssues with', list.length, 'issues');
        setIssues(list);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = String((err as Error)?.message ?? err ?? '');
        if (msg.includes('401') || msg.includes('Unauthorized') || msg.includes('needs_auth')) {
          setNotConnected(true);
        } else {
          setLoadError('Unable to load Jira tickets. Check your connection in Settings.');
        }
        setIssues([]);
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [reloadTick]);

  // ── Column sort handler ───────────────────────────────────────────────────
  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  function SortArrow({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span style={{ opacity: 0.25 }}> ↕</span>;
    return <span style={{ color: '#818cf8' }}>{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>;
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
  return (
    <div data-testid="jira-overview" style={{ minHeight: '100%' }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Jira</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          All tickets from your connected Jira instance.
        </p>
      </div>

      {/* Summary chips */}
      {!notConnected && !loadError && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 18 }}>
          <span style={{ padding: '7px 12px', borderRadius: 999, background: 'rgba(99,102,241,0.16)', color: '#818cf8', fontSize: 12, fontWeight: 700 }}>
            Total: {issues.length}
          </span>
          <span style={{ padding: '7px 12px', borderRadius: 999, background: 'rgba(52,211,153,0.16)', color: '#34d399', fontSize: 12, fontWeight: 700 }}>
            Resolved: {resolved}
          </span>
          <span style={{ padding: '7px 12px', borderRadius: 999, background: 'rgba(248,113,113,0.16)', color: '#f87171', fontSize: 12, fontWeight: 700 }}>
            Open: {todo}
          </span>
        </div>
      )}

      {/* Toolbar */}
      {!notConnected && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'center' }}>
          <input
            type="search"
            placeholder="Search key or summary…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={INPUT_STYLE}
          />

          <select value={projectFilter} onChange={e => setProjectFilter(e.target.value)} style={SELECT_STYLE}>
            <option value="">All projects</option>
            {projectOptions.map(p => <option key={p} value={p}>{p}</option>)}
          </select>

          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={SELECT_STYLE}>
            <option value="">All statuses</option>
            {statusOptions.map(s => <option key={s} value={s}>{s}</option>)}
          </select>

          <select value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)} style={SELECT_STYLE}>
            <option value="">All priorities</option>
            {priorityOptions.map(p => <option key={p} value={p}>{p}</option>)}
          </select>

          <select value={assigneeFilter} onChange={e => setAssigneeFilter(e.target.value)} style={SELECT_STYLE}>
            <option value="">All assignees</option>
            {assigneeOptions.map(a => <option key={a} value={a}>{a}</option>)}
          </select>

          <button
            type="button"
            onClick={() => { bypassCache.current = true; setReloadTick(t => t + 1); }}
            style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', cursor: 'pointer', fontSize: 12 }}
          >
            ↺ Refresh
          </button>

          {!loading && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 4 }}>
              {visible.length} result{visible.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}

      {/* States */}
      {notConnected ? (
        <div style={{ padding: '24px 20px', borderRadius: 10, background: 'rgba(99,102,241,0.07)', border: '1px solid rgba(99,102,241,0.2)', fontSize: 14, color: 'var(--text-muted)' }}>
          🔗 Connect your Jira account from{' '}
          <a href="/settings" style={{ color: '#818cf8', textDecoration: 'none', fontWeight: 600 }}>Settings</a>{' '}
          to view your tickets here.
        </div>
      ) : loading ? (
        <div style={{ padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }}>Loading Jira tickets…</div>
      ) : loadError ? (
        <div style={{ padding: '14px 18px', borderRadius: 8, background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.2)', color: '#f87171', fontSize: 13 }}>
          {loadError}
        </div>
      ) : visible.length === 0 ? (
        <div style={{ padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }}>
          No tickets match the current filters.
        </div>
      ) : (

        /* ── Table ─────────────────────────────────────────────────────── */
        <div style={{ overflowX: 'auto', borderRadius: 10, border: '1px solid var(--card-border)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', background: 'var(--surface)' }}>
            <thead>
              <tr>
                <th style={TH_STYLE}>Issue Key</th>
                <th style={{ ...TH_STYLE, minWidth: 260 }}>Summary</th>
                <th style={TH_STYLE}>Project</th>
                <th
                  style={{ ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => handleSort('status')}
                >
                  Status <SortArrow k="status" />
                </th>
                <th
                  style={{ ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => handleSort('priority')}
                >
                  Priority <SortArrow k="priority" />
                </th>
                <th style={TH_STYLE}>Assignee</th>
                <th
                  style={{ ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => handleSort('created')}
                >
                  Created <SortArrow k="created" />
                </th>
                <th
                  style={{ ...TH_STYLE, cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => handleSort('updated')}
                >
                  Updated <SortArrow k="updated" />
                </th>
                <th style={{ ...TH_STYLE, textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((issue, idx) => {
                const isLast = idx === visible.length - 1;
                const tdStyle: React.CSSProperties = {
                  ...TD_STYLE,
                  borderBottom: isLast ? 'none' : '1px solid var(--card-border)',
                };
                const url = browseUrl(issue, jiraSiteUrl);
                const sName = issue.fields?.status?.name ?? '—';
                const pName = issue.fields?.priority?.name;

                return (
                  <tr key={issue.id} style={{ transition: 'background 0.1s' }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.025)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >
                    {/* Issue Key */}
                    <td style={tdStyle}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: '#818cf8', fontWeight: 700, textDecoration: 'none', fontFamily: 'ui-monospace, monospace', fontSize: 12 }}
                      >
                        {issue.key}
                      </a>
                    </td>

                    {/* Summary */}
                    <td style={{ ...tdStyle, maxWidth: 340 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text)' }}>
                        {issue.fields?.summary ?? '—'}
                      </div>
                    </td>

                    {/* Project */}
                    <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }}>
                      {issue.fields?.project?.name ?? issue.fields?.project?.key ?? '—'}
                    </td>

                    {/* Status */}
                    <td style={tdStyle}>
                      <span style={{
                        padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
                        background: `${statusColor(sName)}1a`,
                        color: statusColor(sName),
                        whiteSpace: 'nowrap',
                      }}>
                        {sName}
                      </span>
                    </td>

                    {/* Priority */}
                    <td style={tdStyle}>
                      {pName ? (
                        <span style={{ fontSize: 12, fontWeight: 600, color: priorityColor(pName) }}>
                          {pName}
                        </span>
                      ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>

                    {/* Assignee */}
                    <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }}>
                      {issue.fields?.assignee?.displayName ?? (
                        <span style={{ fontStyle: 'italic', opacity: 0.5 }}>Unassigned</span>
                      )}
                    </td>

                    {/* Created */}
                    <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {fmtDate(issue.fields?.created)}
                    </td>

                    {/* Updated */}
                    <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {fmtDate(issue.fields?.updated)}
                    </td>

                    {/* Actions */}
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          padding: '5px 12px', borderRadius: 6,
                          border: '1px solid rgba(56,189,248,0.3)',
                          color: '#38bdf8', background: 'rgba(56,189,248,0.07)',
                          textDecoration: 'none', fontSize: 12, whiteSpace: 'nowrap',
                        }}
                      >
                        Open in Jira ↗
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
