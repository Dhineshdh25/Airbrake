/**
 * Settings view — Admin only.
 * Requirements: 6.5, 9.1
 */

import React, { useEffect, useState } from 'react';
import type { RetentionPolicy, Role, User } from '@portal/shared';
import { apiFetch } from '../lib/api';
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

const btnStyle = (variant: 'ghost' | 'danger'): React.CSSProperties => ({
  padding: '5px 12px',
  borderRadius: 'var(--radius-sm)' as unknown as number,
  fontSize: 12,
  fontWeight: 500,
  cursor: 'pointer',
  border: '1px solid var(--card-border)',
  background: variant === 'danger' ? 'rgba(239,68,68,0.1)' : 'transparent',
  color: variant === 'danger' ? '#ef4444' : 'var(--text-muted)',
  transition: 'all var(--transition)',
});

export function Settings({ role }: Props) {
  const [users, setUsers] = useState<User[]>([]);
  const [retention, setRetention] = useState<RetentionPolicy | null>(null);
  const [loading, setLoading] = useState(true);

  const isAdmin = role === 'admin';

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;

    Promise.all([
      apiFetch('/api/users').then((r) => r.json()),
      apiFetch('/api/retention').then((r) => r.json()),
    ])
      .then(([usersData, retentionData]) => {
        if (!cancelled) {
          setUsers(usersData as User[]);
          setRetention(retentionData as RetentionPolicy);
          setLoading(false);
        }
      })
      .catch(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [isAdmin]);

  if (!isAdmin) {
    // Non-admin users still see the Jira integration panel
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
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Manage users and data retention policies</p>
      </div>

      {loading ? (
        <div data-testid="settings-loading" style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
          Loading…
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* User management */}
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
              <thead>
                <tr style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: 0.8,
                  borderBottom: '1px solid var(--card-border)',
                }}>
                  <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>Email</th>
                  <th style={{ padding: '10px 18px', textAlign: 'left', fontWeight: 600 }}>Role</th>
                  <th style={{ padding: '10px 18px', textAlign: 'right', fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr
                    key={u.id}
                    data-testid="user-row"
                    style={{ borderBottom: i < users.length - 1 ? '1px solid var(--card-border)' : 'none' }}
                  >
                    <td data-testid="user-email" style={{ padding: '12px 18px', fontSize: 13.5 }}>{u.email}</td>
                    <td data-testid="user-role" style={{ padding: '12px 18px', fontSize: 13, color: 'var(--text-muted)' }}>{u.role}</td>
                    <td style={{ padding: '12px 18px', textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button data-testid="edit-user" aria-label={`Edit ${u.email}`} style={btnStyle('ghost')}>Edit</button>
                        <button data-testid="delete-user" aria-label={`Delete ${u.email}`} style={btnStyle('danger')}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Retention settings */}
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <label htmlFor="retention-select" style={{ fontSize: 13, color: 'var(--text-muted)' }}>Retention period</label>
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
          </section>

          {/* Jira integration — shown to all authenticated users, not admin-only */}
          <JiraSettings />
        </div>
      )}
    </div>
  );
}
