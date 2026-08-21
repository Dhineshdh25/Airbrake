/**
 * Settings view — admin and non-admin layouts.
 *
 * ADMIN:
 *   - Users section: full table of all users, role editing, add/remove workflow
 *   - Projects section: all projects with responsible-user assignment
 *   - Jira Integration section
 *
 * NON-ADMIN (viewer / developer):
 *   - Own row only: email, role, own Jira ticket counts
 *   - Jira Integration section
 *
 * Security:
 *   - All mutations go through the backend; the backend derives the caller's
 *     identity from the session cookie — never from a frontend-supplied user_id.
 *   - Ticket counts for other users are fetched via GET /api/users/<id>/tickets
 *     which is admin-gated server-side.
 *   - No user's oauth_subject or raw metadata is rendered.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { Role } from '@portal/shared';
import { apiFetch } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { JiraSettings } from './JiraSettings';

// ── Existing VALID_ROLES from the backend (must stay in sync with middleware.py) ─
const VALID_ROLES: Role[] = ['admin', 'developer', 'viewer'];

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserRow {
  id: string;
  email: string;
  role: Role;
  oauth_provider: string;
  created_at: string;
}

interface TicketCounts {
  resolved: number;
  open: number;
}

interface ProjectRow {
  id: string;
  name: string;
  category: string;
  is_live: boolean;
  owner_user_id: string;
  responsible_user_id: string;
  responsible_user_email: string;
}

interface MyTicket {
  log_id: string;
  issue_key: string;
  project_name: string;
  error: string;
  jira_status: string;
  jira_url: string;
  created_at: string;
}

interface MyTicketsResponse {
  total: number;
  limit: number;
  offset: number;
  tickets: MyTicket[];
}

type CountState = number | null;

const PAGE_SIZE = 5;

// ── Shared visual tokens (matching existing dark-theme UI) ────────────────────

const S: Record<string, React.CSSProperties> = {
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--card-border)',
    borderRadius: 10,
    overflow: 'hidden',
  },
  cardHeader: {
    padding: '14px 18px',
    borderBottom: '1px solid var(--card-border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  cardTitle: { fontSize: 14, fontWeight: 600 },
  th: {
    padding: '10px 18px',
    textAlign: 'left' as const,
    fontWeight: 600,
    fontSize: 11,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: 0.8,
    borderBottom: '1px solid var(--card-border)',
    whiteSpace: 'nowrap' as const,
  },
  td: {
    padding: '13px 18px',
    fontSize: 13,
    verticalAlign: 'middle' as const,
    borderBottom: '1px solid var(--card-border)',
  },
  btnPrimary: {
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    background: '#6366f1',
    color: '#fff',
    border: 'none',
    cursor: 'pointer',
  },
  btnSecondary: {
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 500,
    background: 'transparent',
    color: 'var(--text-muted)',
    border: '1px solid var(--card-border)',
    cursor: 'pointer',
  },
  btnDanger: {
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    background: 'rgba(239,68,68,0.1)',
    color: '#f87171',
    border: '1px solid rgba(239,68,68,0.25)',
    cursor: 'pointer',
  },
  input: {
    width: '100%',
    padding: '8px 10px',
    borderRadius: 6,
    border: '1px solid var(--input-border)',
    background: 'var(--input-bg)',
    color: 'var(--text)',
    fontSize: 13,
    outline: 'none',
    boxSizing: 'border-box' as const,
  },
  select: {
    padding: '6px 10px',
    borderRadius: 6,
    border: '1px solid var(--input-border)',
    background: 'var(--input-bg)',
    color: 'var(--text)',
    fontSize: 12,
    cursor: 'pointer',
    outline: 'none',
  },
  errorMsg: {
    marginTop: 8,
    padding: '7px 11px',
    borderRadius: 6,
    fontSize: 12,
    color: '#f87171',
    background: 'rgba(239,68,68,0.08)',
    border: '1px solid rgba(239,68,68,0.2)',
  },
  successMsg: {
    marginTop: 8,
    padding: '7px 11px',
    borderRadius: 6,
    fontSize: 12,
    color: '#34d399',
    background: 'rgba(52,211,153,0.08)',
    border: '1px solid rgba(52,211,153,0.2)',
  },
};

// ── Ticket dropdown (unchanged from previous implementation) ──────────────────

function TicketDropdown({
  userId,
  status,
  color,
}: {
  userId: string;
  status: 'resolved' | 'open';
  color: string;
}) {
  const [total, setTotal]     = useState<CountState>(null);
  const [open, setOpen]       = useState(false);
  const [page, setPage]       = useState(0);
  const [tickets, setTickets] = useState<MyTicket[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');
  const fetched = useRef(false);

  // Fetch total count once on mount, using the per-user endpoint
  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    apiFetch(`/api/jira/my-tickets?status=${status}&limit=1&offset=0`)
      .then(r => r.json())
      .then((d: MyTicketsResponse) => setTotal(d.total ?? 0))
      .catch(() => setTotal(0));
  // userId prop used to prevent stale closures when row changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, status]);

  // Fetch page data whenever expanded or page changes
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
  }, [open, page, status, userId]);

  if (total === null) {
    return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>;
  }
  if (total === 0) {
    return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>;
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <button
        onClick={() => { setOpen(o => !o); setPage(0); }}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          background: 'none', border: 'none', cursor: 'pointer', padding: 0, color,
        }}
        aria-expanded={open}
      >
        <span style={{ fontSize: 13, fontWeight: 700 }}>{total}</span>
        <span style={{
          fontSize: 9, opacity: 0.7, display: 'inline-block', transition: 'transform 0.15s',
          transform: open ? 'rotate(180deg)' : 'none',
        }}>▼</span>
      </button>

      {open && (
        <div style={{
          marginTop: 8, background: 'var(--bg)', border: '1px solid var(--card-border)',
          borderRadius: 8, overflow: 'hidden', minWidth: 280, position: 'relative', zIndex: 10,
        }}>
          {loading ? (
            <div style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>
          ) : error ? (
            <div style={{ padding: '10px 14px', fontSize: 12, color: '#f87171' }}>{error}</div>
          ) : tickets.length === 0 ? (
            <div style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-muted)' }}>No tickets found.</div>
          ) : (
            <>
              {tickets.map((t, i) => (
                <div key={t.log_id} style={{
                  padding: '9px 13px',
                  borderBottom: i < tickets.length - 1 ? '1px solid var(--card-border)' : 'none',
                  display: 'flex', flexDirection: 'column', gap: 3,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
                    {t.jira_url ? (
                      <a href={t.jira_url} target="_blank" rel="noreferrer"
                        style={{ fontSize: 11, fontWeight: 700, color: '#818cf8', fontFamily: 'ui-monospace, monospace', textDecoration: 'none' }}>
                        {t.issue_key}
                      </a>
                    ) : (
                      <span style={{ fontSize: 11, fontWeight: 700, color: '#818cf8', fontFamily: 'ui-monospace, monospace' }}>
                        {t.issue_key}
                      </span>
                    )}
                    {t.jira_status && (
                      <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 999, background: `${color}1a`, color }}>
                        {t.jira_status}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 340 }}>
                    {t.error || '—'}
                  </div>
                  {t.project_name && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{t.project_name}</div>
                  )}
                </div>
              ))}
              {totalPages > 1 && (
                <div style={{
                  padding: '7px 13px', borderTop: '1px solid var(--card-border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11,
                }}>
                  <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                    style={{ ...S.btnSecondary, padding: '3px 8px', opacity: page === 0 ? 0.4 : 1 }}>
                    ← Prev
                  </button>
                  <span style={{ color: 'var(--text-muted)' }}>{page + 1} / {totalPages}</span>
                  <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                    style={{ ...S.btnSecondary, padding: '3px 8px', opacity: page >= totalPages - 1 ? 0.4 : 1 }}>
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

// ── Per-user ticket counts for the admin users table ──────────────────────────
// Fetches GET /api/users/<id>/tickets — admin-gated on the backend.
// Shows the COUNT only. Expanding to show ticket detail is intentionally
// disabled for other users: the only available listing endpoint (/api/jira/my-tickets)
// is session-scoped and would return the admin's own tickets instead of the
// target user's — which would be cross-user ticket leakage.
// The currently-logged-in admin's own row uses TicketDropdown (below) which
// calls my-tickets correctly.

function AdminTicketCell({
  userId,
  status,
  color,
}: {
  userId: string;
  status: 'resolved' | 'open';
  color: string;
}) {
  const [count, setCount] = useState<CountState>(null);
  const fetched = useRef(false);

  // Reset and re-fetch whenever userId changes (defensive guard)
  useEffect(() => {
    fetched.current = false;
    setCount(null);
  }, [userId]);

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    apiFetch(`/api/users/${encodeURIComponent(userId)}/tickets`)
      .then(r => r.json())
      .then((d: TicketCounts) => {
        setCount(status === 'resolved' ? (d.resolved ?? 0) : (d.open ?? 0));
      })
      .catch(() => setCount(0));
  }, [userId, status]);

  if (count === null) return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>;
  if (count === 0)    return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>;

  // Count only — no dropdown expansion for other users' tickets.
  // Expanding would require a server-side per-user ticket listing endpoint
  // which does not yet exist. Showing count only is safe and accurate.
  return (
    <span style={{ fontSize: 13, fontWeight: 700, color }}>{count}</span>
  );
}

// ── Inline role selector ───────────────────────────────────────────────────────

function RoleSelector({
  userId,
  currentRole,
  onUpdated,
  isSelf,
}: {
  userId: string;
  currentRole: Role;
  onUpdated: (updated: UserRow) => void;
  isSelf: boolean;
}) {
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState('');
  const [role, setRole]       = useState<Role>(currentRole);

  // Keep local state in sync if parent refreshes the user list
  useEffect(() => { setRole(currentRole); }, [currentRole]);

  async function handleChange(newRole: Role) {
    if (newRole === role) return;
    setSaving(true);
    setError('');
    const prev = role;
    setRole(newRole); // optimistic
    try {
      const r = await apiFetch(`/api/users/${encodeURIComponent(userId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole }),
      });
      const d = await r.json();
      if (d.error) { setRole(prev); setError(d.message || d.error); }
      else onUpdated(d as UserRow);
    } catch {
      setRole(prev);
      setError('Save failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <select
        value={role}
        disabled={saving}
        onChange={e => handleChange(e.target.value as Role)}
        style={{ ...S.select, opacity: saving ? 0.6 : 1 }}
        title={isSelf ? 'You cannot change your own role here' : undefined}
      >
        {VALID_ROLES.map(r => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
      {error && <div style={{ fontSize: 11, color: '#f87171', marginTop: 4 }}>{error}</div>}
    </div>
  );
}

// ── Add User modal/inline form ────────────────────────────────────────────────

function AddUserForm({ onAdded, onCancel }: { onAdded: (u: UserRow) => void; onCancel: () => void }) {
  const [email, setEmail]   = useState('');
  const [role, setRole]     = useState<Role>('viewer');
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmed)) {
      setError('Enter a valid email address.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const r = await apiFetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: trimmed, role }),
      });
      const d = await r.json();
      if (!r.ok) { setError(d.message || d.error || 'Failed to add user.'); }
      else { onAdded(d as UserRow); }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{
      margin: '0 0 0 0',
      padding: '16px 18px',
      borderBottom: '1px solid var(--card-border)',
      background: 'rgba(99,102,241,0.04)',
    }}>
      <form onSubmit={handleSubmit}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 240px' }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6 }}>
              Email
            </label>
            <input
              type="email"
              autoFocus
              placeholder="user@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              style={S.input}
            />
          </div>
          <div style={{ flex: '0 0 130px' }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6 }}>
              Role
            </label>
            <select value={role} onChange={e => setRole(e.target.value as Role)} style={{ ...S.select, width: '100%', padding: '8px 10px' }}>
              {VALID_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, paddingBottom: 1 }}>
            <button type="submit" disabled={saving} style={{ ...S.btnPrimary, opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Adding…' : 'Add'}
            </button>
            <button type="button" onClick={onCancel} style={S.btnSecondary}>Cancel</button>
          </div>
        </div>
        {error && <div style={S.errorMsg}>{error}</div>}
      </form>
    </div>
  );
}

// ── Admin Users section ───────────────────────────────────────────────────────

function AdminUsersSection({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers]           = useState<UserRow[]>([]);
  const [loadingUsers, setLoading]  = useState(true);
  const [fetchError, setFetchError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [removeMode, setRemoveMode] = useState(false);
  const [selected, setSelected]     = useState<Set<string>>(new Set());
  const [removing, setRemoving]     = useState(false);
  const [removeError, setRemoveError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const loadUsers = useCallback(() => {
    setLoading(true);
    setFetchError('');
    apiFetch('/api/users')
      .then(r => r.json())
      .then((d: UserRow[]) => { setUsers(Array.isArray(d) ? d : []); })
      .catch(() => setFetchError('Failed to load users.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  function handleUserAdded(u: UserRow) {
    setUsers(prev => [u, ...prev]);
    setShowAddForm(false);
    flash('User added successfully.');
  }

  function handleRoleUpdated(updated: UserRow) {
    setUsers(prev => prev.map(u => u.id === updated.id ? { ...u, role: updated.role } : u));
  }

  function toggleSelect(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleRemoveConfirmed() {
    if (selected.size === 0) return;
    const toDelete = [...selected];
    const names = users.filter(u => toDelete.includes(u.id)).map(u => u.email).join(', ');
    if (!window.confirm(`Permanently delete ${toDelete.length} user(s)?\n\n${names}\n\nThis cannot be undone.`)) return;

    setRemoving(true);
    setRemoveError('');
    const errors: string[] = [];
    for (const id of toDelete) {
      try {
        const r = await apiFetch(`/api/users/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!r.ok && r.status !== 204) {
          const d = await r.json();
          errors.push(d.message || d.error || `Failed to delete ${id}`);
        }
      } catch {
        errors.push(`Network error deleting ${id}`);
      }
    }
    setRemoving(false);
    if (errors.length > 0) {
      setRemoveError(errors.join(' | '));
    } else {
      setUsers(prev => prev.filter(u => !toDelete.includes(u.id)));
      setSelected(new Set());
      setRemoveMode(false);
      flash(`${toDelete.length} user(s) removed.`);
    }
  }

  function flash(msg: string) {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(''), 3500);
  }

  return (
    <section style={S.card}>
      <div style={S.cardHeader}>
        <span style={S.cardTitle}>Users</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {!removeMode && (
            <button
              onClick={() => { setShowAddForm(f => !f); setRemoveMode(false); }}
              style={S.btnPrimary}
            >
              {showAddForm ? 'Cancel' : '+ Add user'}
            </button>
          )}
          {!showAddForm && (
            removeMode ? (
              <>
                <button
                  onClick={handleRemoveConfirmed}
                  disabled={selected.size === 0 || removing}
                  style={{ ...S.btnDanger, opacity: (selected.size === 0 || removing) ? 0.5 : 1 }}
                >
                  {removing ? 'Removing…' : `Remove (${selected.size})`}
                </button>
                <button
                  onClick={() => { setRemoveMode(false); setSelected(new Set()); setRemoveError(''); }}
                  style={S.btnSecondary}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button onClick={() => { setRemoveMode(true); setShowAddForm(false); }} style={S.btnSecondary}>
                Remove user
              </button>
            )
          )}
        </div>
      </div>

      {showAddForm && <AddUserForm onAdded={handleUserAdded} onCancel={() => setShowAddForm(false)} />}

      {successMsg && <div style={{ ...S.successMsg, margin: '10px 18px 0' }}>{successMsg}</div>}
      {removeError && <div style={{ ...S.errorMsg, margin: '10px 18px 0' }}>{removeError}</div>}

      {loadingUsers ? (
        <div style={{ padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }}>Loading users…</div>
      ) : fetchError ? (
        <div style={{ padding: '16px 18px', fontSize: 13, color: '#f87171' }}>{fetchError}</div>
      ) : users.length === 0 ? (
        <div style={{ padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }}>No users found.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={S.th}>Email</th>
                <th style={S.th}>Role</th>
                <th style={S.th}>Resolved Tickets</th>
                <th style={S.th}>Open Tickets</th>
                {removeMode && <th style={{ ...S.th, textAlign: 'center' as const }}>Select</th>}
              </tr>
            </thead>
            <tbody>
              {users.map((u, idx) => {
                const isLast = idx === users.length - 1;
                const tdStyle: React.CSSProperties = { ...S.td, borderBottom: isLast ? 'none' : '1px solid var(--card-border)' };
                const isSelf = u.id === currentUserId;
                return (
                  <tr key={u.id}
                    style={{ background: selected.has(u.id) ? 'rgba(239,68,68,0.04)' : 'transparent', transition: 'background 0.12s' }}
                  >
                    <td style={tdStyle}>
                      <span style={{ fontSize: 13.5 }}>{u.email}</span>
                      {isSelf && (
                        <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, background: 'rgba(99,102,241,0.12)', padding: '2px 6px', borderRadius: 999 }}>
                          You
                        </span>
                      )}
                    </td>
                    <td style={tdStyle}>
                      <RoleSelector
                        userId={u.id}
                        currentRole={u.role}
                        onUpdated={handleRoleUpdated}
                        isSelf={isSelf}
                      />
                    </td>
                    <td style={tdStyle}>
                      <AdminTicketCell userId={u.id} status="resolved" color="#34d399" />
                    </td>
                    <td style={tdStyle}>
                      <AdminTicketCell userId={u.id} status="open" color="#818cf8" />
                    </td>
                    {removeMode && (
                      <td style={{ ...tdStyle, textAlign: 'center' as const }}>
                        <input
                          type="checkbox"
                          checked={selected.has(u.id)}
                          onChange={() => toggleSelect(u.id)}
                          disabled={isSelf}
                          title={isSelf ? 'You cannot delete yourself' : undefined}
                          style={{ cursor: isSelf ? 'not-allowed' : 'pointer', width: 15, height: 15 }}
                        />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Projects section ──────────────────────────────────────────────────────────

function ProjectsSection({ users }: { users: UserRow[] }) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');

  useEffect(() => {
    setLoading(true);
    apiFetch('/api/projects')
      .then(r => r.json())
      .then((d: ProjectRow[]) => setProjects(Array.isArray(d) ? d : []))
      .catch(() => setError('Failed to load projects.'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section style={S.card}>
      <div style={S.cardHeader}>
        <span style={S.cardTitle}>Projects</span>
      </div>

      {loading ? (
        <div style={{ padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }}>Loading projects…</div>
      ) : error ? (
        <div style={{ padding: '16px 18px', fontSize: 13, color: '#f87171' }}>{error}</div>
      ) : projects.length === 0 ? (
        <div style={{ padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }}>No projects found.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={S.th}>Project</th>
                <th style={S.th}>Category</th>
                <th style={S.th}>Responsible User</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p, idx) => {
                const isLast = idx === projects.length - 1;
                const tdStyle: React.CSSProperties = { ...S.td, borderBottom: isLast ? 'none' : '1px solid var(--card-border)' };
                return (
                  <tr key={p.id}>
                    <td style={tdStyle}>
                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                    </td>
                    <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }}>
                      {p.category || '—'}
                    </td>
                    <td style={tdStyle}>
                      <ResponsibleUserSelector
                        project={p}
                        users={users}
                        onUpdated={updated => setProjects(prev => prev.map(x => x.id === updated.id ? updated : x))}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Responsible user selector (per project row) ───────────────────────────────

function ResponsibleUserSelector({
  project,
  users,
  onUpdated,
}: {
  project: ProjectRow;
  users: UserRow[];
  onUpdated: (updated: ProjectRow) => void;
}) {
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState('');
  const [value, setValue]     = useState(project.responsible_user_id || '');

  useEffect(() => { setValue(project.responsible_user_id || ''); }, [project.responsible_user_id]);

  async function handleChange(newUserId: string) {
    if (newUserId === value) return;
    setSaving(true);
    setError('');
    const prev = value;
    setValue(newUserId); // optimistic
    try {
      const r = await apiFetch(
        `/api/projects/${encodeURIComponent(project.id)}/responsible-user`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: newUserId || null }),
        },
      );
      const d = await r.json();
      if (!r.ok) { setValue(prev); setError(d.message || d.error || 'Save failed.'); }
      else onUpdated(d as ProjectRow);
    } catch {
      setValue(prev);
      setError('Network error.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <select
        value={value}
        disabled={saving}
        onChange={e => handleChange(e.target.value)}
        style={{ ...S.select, opacity: saving ? 0.6 : 1, minWidth: 200 }}
      >
        <option value="">Unassigned</option>
        {users.map(u => (
          <option key={u.id} value={u.id}>{u.email}</option>
        ))}
      </select>
      {error && <div style={{ fontSize: 11, color: '#f87171', marginTop: 4 }}>{error}</div>}
    </div>
  );
}

// ── Non-admin own-row section ─────────────────────────────────────────────────
// Shows only the current user's own email, role, and their Jira ticket counts.

function OwnUserSection({ currentUser }: { currentUser: { id: string; email: string; role: string } }) {
  return (
    <section style={S.card}>
      <div style={S.cardHeader}>
        <span style={S.cardTitle}>Users</span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={S.th}>Email</th>
            <th style={S.th}>Role</th>
            <th style={S.th}>Resolved Tickets</th>
            <th style={S.th}>Open Tickets</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ ...S.td, borderBottom: 'none' }}>
              {currentUser.email}
            </td>
            <td style={{ ...S.td, borderBottom: 'none', color: 'var(--text-muted)' }}>
              {currentUser.role}
            </td>
            <td style={{ ...S.td, borderBottom: 'none' }}>
              <TicketDropdown userId={currentUser.id} status="resolved" color="#34d399" />
            </td>
            <td style={{ ...S.td, borderBottom: 'none' }}>
              <TicketDropdown userId={currentUser.id} status="open" color="#818cf8" />
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

// ── Root Settings component ───────────────────────────────────────────────────

interface Props {
  readonly role: Role;
}

export function Settings({ role }: Props) {
  const { user } = useAuth();
  // Admin fetches the full user list so the Projects section can populate
  // its responsible-user dropdowns without a second round trip.
  const [allUsers, setAllUsers] = useState<UserRow[]>([]);

  const isAdmin = role === 'admin';

  useEffect(() => {
    if (!isAdmin) return;
    apiFetch('/api/users')
      .then(r => r.json())
      .then((d: UserRow[]) => setAllUsers(Array.isArray(d) ? d : []))
      .catch(() => {/* non-fatal — projects section degrades gracefully */});
  }, [isAdmin]);

  if (!isAdmin) {
    // Non-admin: own row + Jira integration only
    return (
      <div data-testid="settings">
        <div style={{ marginBottom: 28 }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Settings</h2>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {user && <OwnUserSection currentUser={user} />}
          <JiraSettings />
        </div>
      </div>
    );
  }

  return (
    <div data-testid="settings">
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Settings</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Manage users, projects, and integrations.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        {/* Users — full management table for admins */}
        <AdminUsersSection currentUserId={user?.id ?? ''} />

        {/* Projects — responsible user assignment */}
        <ProjectsSection users={allUsers} />

        {/* Jira Integration */}
        <JiraSettings />
      </div>
    </div>
  );
}
