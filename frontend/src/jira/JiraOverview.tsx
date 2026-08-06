import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../lib/api';

interface JiraTicketRow {
  log_id: string;
  issue_key: string;
  project_name: string;
  error: string;
  jira_status: string;
  jira_sync_status: string;
  jira_sync_detail: string;
  jira_url: string;
  created_by: string;
  updated_at: string;
}

interface JiraIssue {
  id: string;
  key: string;
  self?: string;
  fields: {
    summary?: string;
    status?: { name?: string };
    created?: string;
    updated?: string;
    assignee?: { displayName?: string };
    reporter?: { displayName?: string };
    project?: { name?: string; key?: string };
  };
}

const SELECT_STYLE: React.CSSProperties = {
  background: 'var(--input-bg)',
  border: '1px solid var(--input-border)',
  borderRadius: 6,
  color: 'var(--text)',
  padding: '8px 11px',
  fontSize: 13,
  outline: 'none',
  cursor: 'pointer',
};

function formatDate(value: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

export function JiraOverview() {
  const [tickets, setTickets] = useState<JiraTicketRow[]>([]);
  const [summary, setSummary] = useState<{ total: number; resolved: number; todo: number }>({
    total: 0,
    resolved: 0,
    todo: 0,
  });
  const [statusFilter, setStatusFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [jiraBaseUrl, setJiraBaseUrl] = useState('https://your-domain.atlassian.net');

  const projectOptions = useMemo(() => {
    const projects = Array.from(new Set(tickets.map((row) => row.project_name).filter(Boolean)));
    return projects.sort();
  }, [tickets]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);

    // If there's no session token, redirect to login and show friendly message.
    const sessionToken = localStorage.getItem('session_token');
    if (!sessionToken) {
      setLoadError('Your session has expired. Please log in again.');
      try { window.location.href = '/auth/login'; } catch (e) {}
      setLoading(false);
      return;
    }

    // Build JQL query to search Jira directly
    const jqlParts: string[] = [];

    if (projectFilter) {
      jqlParts.push(`project = "${projectFilter}"`);
    }

    if (statusFilter === 'resolved') {
      jqlParts.push('status IN (Done, Resolved, Closed)');
    } else if (statusFilter === 'todo') {
      jqlParts.push('status NOT IN (Done, Resolved, Closed)');
    }

    // Build final JQL query
    const jql = jqlParts.length > 0 ? jqlParts.join(' AND ') + ' ORDER BY updated DESC' : 'ORDER BY updated DESC';

    // Query Jira directly using the new search endpoint
    apiFetch(`/api/jira/search?jql=${encodeURIComponent(jql)}&maxResults=100`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;

        // Extract Jira base URL from the first issue's self URL if available
        if (data.issues && data.issues.length > 0 && data.issues[0].self) {
          try {
            const url = new URL(data.issues[0].self);
            const baseUrl = `${url.protocol}//${url.host}`;
            setJiraBaseUrl(baseUrl);
          } catch (e) {
            console.warn('[JiraOverview] Could not parse Jira URL from self link');
          }
        }

        // Transform Jira issues to our ticket format
        const issues: JiraIssue[] = data.issues ?? [];
        const transformedTickets: JiraTicketRow[] = issues.map((issue) => {
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
        const resolved = transformedTickets.filter(t =>
          ['done', 'resolved', 'closed'].includes(t.jira_status.toLowerCase())
        ).length;
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
          const body = error?.body as any;

          if (status === 401 || body?.reason === 'missing_or_invalid_token' || body?.error === 'Unauthorized') {
            // Clear session client-side already handled by apiFetch; show friendly message
            setLoadError('Your session has expired. Please log in again.');
          } else if (status === 403) {
            setLoadError('You do not have permission to view Jira tickets.');
          } else if (status === 404) {
            setLoadError('Jira resource not found.');
          } else if (body && typeof body === 'object' && (body.error === 'Jira account not connected' || body.error === 'Jira not connected')) {
            setLoadError('Jira not connected. Please connect your Jira account in Settings.');
          } else {
            setLoadError('Unable to load Jira tickets. Make sure you have connected your Jira account.');
          }

          setTickets([]);
          setSummary({ total: 0, resolved: 0, todo: 0 });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectFilter, statusFilter, reloadTick, jiraBaseUrl]);

  return (
    <div data-testid="jira-overview">
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Jira</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          All Jira tickets from your connected Jira instance.
        </p>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <span style={{ padding: '8px 12px', borderRadius: 999, background: 'rgba(99,102,241,0.16)', color: '#818cf8', fontSize: 12, fontWeight: 700 }}>
          Total tickets: {summary.total}
        </span>
        <span style={{ padding: '8px 12px', borderRadius: 999, background: 'rgba(52,211,153,0.16)', color: '#34d399', fontSize: 12, fontWeight: 700 }}>
          Resolved: {summary.resolved}
        </span>
        <span style={{ padding: '8px 12px', borderRadius: 999, background: 'rgba(248,113,113,0.16)', color: '#f87171', fontSize: 12, fontWeight: 700 }}>
          Todo: {summary.todo}
        </span>
      </div>

      <div style={{ display: 'grid', gap: 12, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <select
            value={projectFilter}
            onChange={(event) => setProjectFilter(event.target.value)}
            style={SELECT_STYLE}
          >
            <option value="">All projects</option>
            {projectOptions.map((project) => (
              <option key={project} value={project}>
                {project}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            style={SELECT_STYLE}
          >
            <option value="">All statuses</option>
            <option value="resolved">Resolved</option>
            <option value="todo">Todo</option>
          </select>

          <button
            type="button"
            onClick={() => setReloadTick((tick) => tick + 1)}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: '1px solid var(--input-border)',
              background: 'var(--input-bg)',
              color: 'var(--text)',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }}>
          Loading Jira tickets…
        </div>
      ) : loadError ? (
        <div style={{ padding: '16px', borderRadius: 8, background: 'rgba(248,113,113,0.1)', color: '#f87171' }}>
          {loadError}
        </div>
      ) : tickets.length === 0 ? (
        <div style={{ padding: '40px 0', color: 'var(--text-muted)', fontSize: 14 }}>
          No Jira tickets found for this filter.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {tickets.map((ticket) => (
            <div
              key={ticket.log_id}
              style={{
                padding: 18,
                borderRadius: 12,
                background: 'var(--surface)',
                border: '1px solid var(--card-border)',
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto',
                gap: 18,
                alignItems: 'start',
              }}
            >
              <div style={{ minWidth: 0, display: 'grid', gap: 10 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>
                    {ticket.issue_key || 'Unknown issue'}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                    {ticket.project_name || 'No project'}
                  </div>
                  <div style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ['done', 'resolved', 'closed'].includes(ticket.jira_status?.toLowerCase()) ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)', color: ['done', 'resolved', 'closed'].includes(ticket.jira_status?.toLowerCase()) ? '#34d399' : '#f87171' }}>
                    {ticket.jira_status || 'Unknown'}
                  </div>
                </div>

                <div style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {ticket.error || 'No error message available.'}
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, color: 'var(--text-muted)', fontSize: 12 }}>
                  <span>Updated {formatDate(ticket.updated_at)}</span>
                  <span>Created by {ticket.created_by || 'unknown'}</span>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
                <a
                  href={ticket.jira_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', color: '#38bdf8', background: 'rgba(56,189,248,0.08)', textDecoration: 'none', fontSize: 13,
                  }}
                >
                  View in Jira
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
