/**
 * Settings view.
 * Requirements: 6.5, 9.1
 *
 * Users section shows ONLY the currently logged-in user.
 * Resolved Tickets and Open Tickets columns appear only when count > 0.
 * Table <thead> and <tbody> use identical conditional logic so column
 * alignment is always correct.
 */

import React, { useEffect, useRef, useState } from 'react';
import type { RetentionPolicy, Role } from '@portal/shared';
import { apiFetch } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { JiraSettings } from './JiraSettings';

interface Props {
  readonly role: Role;
}

const selectStyle: React.CSSProperties = {
  background: 'var(--input-bg)',
  border: '1px solid var(--input-border)',
  borderRadius: 'var(--radius-sm)' as unknown as number,
  color: 'var(--text)',
  padding: '8px 12px',
  fontSize: 13,
  outline: 'none',
  cursor: 'pointer',
};

// ── Ticket types ──────────────────────────────────────────────────────────────

interface MyTicket {
  log_id: string;
  issue_key: string;
  project_name: string;
  error: string;
  jira_status: string;
  jira_url: string;
  updated_at: string;
}

interface MyTicketsResponse {
  total: number;
  limit: number;
  offset: number;
  tickets: MyTicket[];
}

// Loading sentinel — null means "not yet fetched"
type CountState = number | null;

const PAGE_SIZE = 5;

// ── Ticket count hook ─────────────────────────────────────────────────────────
// Fetches the total count for a given status on mount.
// Returns [count, loading] where count is null while loading.

function useTicketCount(status: 'resolved' | 'open'): CountState {
  const [count, setCount] = useState<CountState>(null);
  const fetched = useRef(false);

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    apiFetch(`/api/jira/my-tickets?status=${status}&limit=1&offset=0`)
      .then(r => r.json())
      .then((d: MyTicketsResponse) => setCount(d.total ?? 0))
      .catch(() => setCount(0));
  }, [status]);

  return count;
}

// ── Expandable ticket panel (rendered inside a <td>) ─────────────────────────

function TicketDropdown({
  status,
  total,
  color,
}: {
  status: 'resolved' | 'open';
  total: number;          // already known > 0 at render time
  color: string;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const [tickets, setTickets] = useState<MyTicket[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Fetch page data whenever the panel is opened or page changes
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError('');
    apiFetch(
      `/api/jira/my-tickets?status=${status}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`
    )
      .then(r => r.json())
      .then((d: MyTicketsResponse) => setTickets(d.tickets ?? []))
      .catch(() => setError('Failed to load tickets.'))
      .finally(() => setLoading(false));
  }, [open, page, status]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      {/* Count + chevron toggle */}
      <button
        onClick={() => { setOpen(o => !o); setPage(0); }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
          color,
        }}
        aria-expanded={open}
        aria-label={`${total} tickets. ${open ? 'Collapse' : 'Expand'}.`}
      >
        <span style={{ fontSize: 13, fontWeight: 700 }}>{total}</span>
        <span style={{
          fontSize: 10,
          opacity: 0.7,
          display: 'inline-block',
          transition: 'transform 0.15s',
          transform: open ? 'rotate(180deg)' : 'none',
        }}>▼</span>
      </button>

      {/* Expanded list */}
      {open && (
        <div style={{
          marginTop: 10,
          background: 'var(--bg)',
          border: '1px solid var(--card-border)',
          borderRadius: 8,
          overflow: 'hidden',
          minWidth: 300,
        }}>
          {loading ? (
            <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-muted)' }}>
              Loading…
            </div>
          ) : error ? (
            <div style={{ padding: '12px 14px', fontSize: 12, color: '#f87171' }}>{error}</div>
          ) : tickets.length === 0 ? (
            <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-muted)' }}>
              No tickets found.
            </div>
          ) : (
            <>
              {tickets.map((t, i) => (
                <div
                  key={t.log_id}
                  style={{
                    padding: '10px 14px',
                    borderBottom: i < tickets.length - 1 ? '1px solid var(--card-border)' : 'none',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 3,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {t.jira_url ? (
                      <a
                        href={t.jira_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: '#818cf8',
                          fontFamily: 'ui-monospace, monospace',
                          textDecoration: 'none',
                        }}
                      >
                        {t.issue_key}
                      </a>
                    ) : (
                      <span style={{
                        fontSize: 12, fontWeight: 700, color: '#818cf8',
                        fontFamily: 'ui-monospace, monospace',
                      }}>
                        {t.issue_key}
                      </span>
                    )}
                    {t.jira_status && (
                      <span style={{
                        fontSize: 10, fontWeight: 600,
                        padding: '2px 7px', borderRadius: 999,
                        background: `${color}1a`, color,
                      }}>
                        {t.jira_status}
                      </span>
                    )}
                  </div>
                  <div style={{
                    fontSize: 12, color: 'var(--text)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    maxWidth: 360,
                  }}>
                    {t.error || '—'}
                  </div>
                  {t.project_name && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {t.project_name}
                    </div>
                  )}
                </div>
              ))}

              {/* Pagination — only when more than one page */}
              {totalPages > 1 && (
                <div style={{
                  padding: '8px 14px',
                  borderTop: '1px solid var(--card-border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  fontSize: 12, color: 'var(--text-muted)',
                }}>
                  <button
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                    disabled={page === 0}
                    style={{
                      background: 'none', border: 'none',
                      cursor: page === 0 ? 'default' : 'pointer',
                      color: page === 0 ? 'var(--text-muted)' : '#818cf8',
                      fontSize: 12, opacity: page === 0 ? 0.4 : 1,
                      padding: '2px 6px',
                    }}
                  >
                    ← Prev
                  </button>
                  <span>{page + 1} / {totalPages}</span>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    style={{
                      background: 'none', border: 'none',
                      cursor: page >= totalPages - 1 ? 'default' : 'pointer',
                      color: page >= totalPages - 1 ? 'var(--text-muted)' : '#818cf8',
                      fontSize: 12, opacity: page >= totalPages - 1 ? 0.4 : 1,
                      padding: '2px 6px',
                    }}
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}

// ── Users section ─────────────────────────────────────────────────────────────
// Columns are conditionally rendered: a column only appears when count > 0.
// <thead> and <tbody> use identical conditions so alignment is always correct.

function UsersSection() {
  const { user } = useAuth();
  const resolvedCount = useTicketCount('resolved');
  const openCount     = useTicketCount('open');

  // While counts are loading, show a minimal single-column table to avoid
  // the "columns appear after load" layout jump.  Once both counts resolve
  // we render the final column set.
  const countsReady = resolvedCount !== null && openCount !== null;

  const showResolved = countsReady && (resolvedCount ?? 0) > 0;
  const showOpen     = countsReady && (openCount ?? 0) > 0;

  if (!user) return null;

  return (
    <section
      data-testid="user-management"
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--card-border)',
        borderRadius: 'var(--radius-md)' as unknown as number,
        overflow: 'hidden',
      }}
    >
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--card-border)' }}>
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>Users</h3>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        {/* ── Header — identical conditions as body ── */}
        <thead>
          <tr style={{
            fontSize: 11, fontWeight: 600,
            color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: 0.8,
            borderBottom: '1px solid var(--card-border)',
          }}>
            <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>Email</th>
            <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>Role</th>
            {showResolved && (
              <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>
                Resolved Tickets
              </th>
            )}
            {showOpen && (
              <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>
                Open Tickets
              </th>
            )}
          </tr>
        </thead>

        {/* ── Body — same conditions as header ── */}
        <tbody>
          <tr data-testid="user-row">
            <td data-testid="user-email" style={{ padding: '14px 18px', fontSize: 13.5 }}>
              {user.email}
            </td>
            <td data-testid="user-role" style={{ padding: '14px 18px', fontSize: 13, color: 'var(--text-muted)' }}>
              {user.role}
            </td>
            {showResolved && (
              <td style={{ padding: '10px 18px', verticalAlign: 'top' }}>
                <TicketDropdown
                  status="resolved"
                  total={resolvedCount!}
                  color="#34d399"
                />
              </td>
            )}
            {showOpen && (
              <td style={{ padding: '10px 18px', verticalAlign: 'top' }}>
                <TicketDropdown
                  status="open"
                  total={openCount!}
                  color="#818cf8"
                />
              </td>
            )}
          </tr>
        </tbody>
      </table>

      {/* Loading state — shown until both counts resolve */}
      {!countsReady && (
        <div style={{ padding: '10px 18px', fontSize: 12, color: 'var(--text-muted)' }}>
          Loading ticket counts…
        </div>
      )}
    </section>
  );
}

// ── Main Settings component ───────────────────────────────────────────────────

export function Settings({ role }: Props) {
  const [retention, setRetention] = useState<RetentionPolicy | null>(null);
  const [retentionLoading, setRetentionLoading] = useState(true);

  const isAdmin = role === 'admin';

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    apiFetch('/api/retention')
      .then(r => r.json())
      .then((data: RetentionPolicy) => {
        if (!cancelled) { setRetention(data); setRetentionLoading(false); }
      })
      .catch(() => { if (!cancelled) setRetentionLoading(false); });
    return () => { cancelled = true; };
  }, [isAdmin]);

  // Non-admin: only show Jira integration
  if (!isAdmin) {
    return (
      <div data-testid="settings">
        <div style={{ marginBottom: 28 }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Settings</h2>
        </div>
        <JiraSettings />
      </div>
    );
  }

  return (
    <div data-testid="settings">
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Settings</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Manage users and data retention policies
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

        {/* Users — current user only, conditional ticket columns */}
        <UsersSection />

        {/* Data Retention */}
        <section
          data-testid="retention-settings"
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--card-border)',
            borderRadius: 'var(--radius-md)' as unknown as number,
            padding: '18px',
          }}
        >
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Data Retention</h3>
          {retentionLoading ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <label htmlFor="retention-select" style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Retention period
              </label>
              <select
                id="retention-select"
                data-testid="retention-selector"
                value={retention?.retentionDays ?? 30}
                onChange={() => {/* handled by parent */}}
                aria-label="Retention period"
                style={selectStyle}
              >
                <option value={30}>30 days</option>
                <option value={60}>60 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>
          )}
        </section>

        {/* Jira integration */}
        <JiraSettings />
      </div>
    </div>
  );
}
