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

interface JiraTicketsResponse {
  total: number;
  resolved: number;
  todo: number;
  sync_failed: number;
  tickets: JiraTicketRow[];
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
  const [summary, setSummary] = useState<{ total: number; resolved: number; todo: number; sync_failed: number }>({
    total: 0,
    resolved: 0,
    todo: 0,
    sync_failed: 0,
  });
  const [statusFilter, setStatusFilter] = useState('');
  const [syncStatusFilter, setSyncStatusFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const projectOptions = useMemo(() => {
    const projects = Array.from(new Set(tickets.map((row) => row.project_name).filter(Boolean)));
    return projects.sort();
  }, [tickets]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setRetryMessage(null);

    const params = new URLSearchParams();
    if (projectFilter) params.set('project', projectFilter);
    if (statusFilter) params.set('status', statusFilter);
    if (syncStatusFilter) params.set('sync_status', syncStatusFilter);

    apiFetch(`/api/jira/tickets?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        setSummary({
          total: data.total ?? 0,
          resolved: data.resolved ?? 0,
          todo: data.todo ?? 0,
          sync_failed: data.sync_failed ?? 0,
        });
        setTickets((data.tickets ?? []) as JiraTicketRow[]);
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
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectFilter, statusFilter, syncStatusFilter, reloadTick]);

  async function retrySync(logId: string, issueKey: string) {
    setRetryMessage(null);
    setRetryingId(logId);

    try {
      const response = await apiFetch(`/api/jira/tickets/${encodeURIComponent(logId)}/retry-sync`, {
        method: 'POST',
      });
      const data = await response.json();
      setRetryMessage(
        data.success
          ? `Sync retry triggered for ${issueKey}. Refreshed ${data.log_ids?.length ?? 0} log(s).`
          : `Retry failed: ${data.detail || 'unknown error'}`,
      );
      setReloadTick((tick) => tick + 1);
    } catch (error) {
      console.error('[JiraOverview] retry sync failed:', error);
      setRetryMessage('Retry failed. Please try again.');
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <div data-testid="jira-overview">
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Jira</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Jira tickets linked to Airbrake errors, with sync status and retry controls.
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
        <span style={{ padding: '8px 12px', borderRadius: 999, background: 'rgba(251,191,36,0.16)', color: '#fbbf24', fontSize: 12, fontWeight: 700 }}>
          Sync failed: {summary.sync_failed}
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

          <select
            value={syncStatusFilter}
            onChange={(event) => setSyncStatusFilter(event.target.value)}
            style={SELECT_STYLE}
          >
            <option value="">All sync statuses</option>
            <option value="synced">Synced</option>
            <option value="sync_failed">Sync Failed</option>
            <option value="skipped">Skipped</option>
          </select>
        </div>

        {retryMessage ? (
          <div style={{ padding: '12px 14px', borderRadius: 8, background: 'rgba(56,189,248,0.12)', color: '#38bdf8' }}>
            {retryMessage}
          </div>
        ) : null}
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
                  <div style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ticket.jira_status?.toLowerCase() === 'resolved' ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)', color: ticket.jira_status?.toLowerCase() === 'resolved' ? '#34d399' : '#f87171' }}>
                    {ticket.jira_status || 'Unknown'}
                  </div>
                  <div style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: ticket.jira_sync_status?.toLowerCase() === 'sync_failed' ? 'rgba(248,113,113,0.12)' : 'rgba(99,102,241,0.12)', color: ticket.jira_sync_status?.toLowerCase() === 'sync_failed' ? '#f87171' : '#818cf8' }}>
                    {ticket.jira_sync_status || 'Unknown sync'}
                  </div>
                </div>

                <div style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {ticket.error || 'No error message available.'}
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, color: 'var(--text-muted)', fontSize: 12 }}>
                  <span>Updated {formatDate(ticket.updated_at)}</span>
                  <span>Created by {ticket.created_by || 'unknown'}</span>
                </div>

                {ticket.jira_sync_detail ? (
                  <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', fontSize: 12, border: '1px solid rgba(255,255,255,0.08)' }}>
                    {ticket.jira_sync_detail}
                  </div>
                ) : null}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
                <a
                  href={ticket.jira_url || `https://your-domain.atlassian.net/browse/${encodeURIComponent(ticket.issue_key)}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', color: '#38bdf8', background: 'rgba(56,189,248,0.08)', textDecoration: 'none', fontSize: 13,
                  }}
                >
                  View in Jira
                </a>
                <button
                  type="button"
                  onClick={() => retrySync(ticket.log_id, ticket.issue_key)}
                  disabled={retryingId === ticket.log_id}
                  style={{
                    padding: '10px 14px', borderRadius: 8, border: 'none',
                    background: retryingId === ticket.log_id ? 'rgba(148,163,184,0.4)' : 'rgba(99,102,241,0.95)',
                    color: '#fff', cursor: retryingId === ticket.log_id ? 'default' : 'pointer',
                    fontSize: 13, fontWeight: 700,
                  }}
                >
                  {retryingId === ticket.log_id ? 'Retrying…' : 'Retry sync'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
