/**
 * JiraSettings — per-user Jira OAuth connection panel.
 *
 * Shown inside the Settings page.
 * Each developer connects their own Jira account here (one-time).
 * After connecting, every "Create Jira Ticket" click uses their identity.
 *
 * No Client ID / Client Secret is exposed here — those are administrator
 * environment variables, invisible to developers.
 */

import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

interface JiraStatusResponse {
  connected: boolean;
  email: string;
  account_id: string;
}

const cardStyle: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--card-border)',
  borderRadius: 10,
  padding: 20,
};

const btnPrimary: React.CSSProperties = {
  padding: '8px 18px',
  borderRadius: 6,
  fontSize: 13,
  fontWeight: 600,
  background: '#6366f1',
  color: '#fff',
  border: 'none',
  cursor: 'pointer',
};

const btnDanger: React.CSSProperties = {
  padding: '8px 18px',
  borderRadius: 6,
  fontSize: 13,
  fontWeight: 600,
  background: 'rgba(239,68,68,0.1)',
  color: '#f87171',
  border: '1px solid rgba(239,68,68,0.25)',
  cursor: 'pointer',
};

export function JiraSettings() {
  const [status, setStatus]   = useState<JiraStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy]       = useState(false);
  const [error, setError]     = useState('');

  // ── Check connection status on mount ──────────────────────────────────────
  useEffect(() => {
    apiFetch('/api/jira/status')
      .then(r => r.json())
      .then((j: JiraStatusResponse) => { setStatus(j); setLoading(false); })
      .catch(() => { setStatus({ connected: false, email: '', account_id: '' }); setLoading(false); });
  }, []);

  // ── Handle post-OAuth redirect params ────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('jira_connected') === 'true') {
      // Re-check status after successful OAuth round-trip
      apiFetch('/api/jira/status')
        .then(r => r.json())
        .then((j: JiraStatusResponse) => { setStatus(j); setLoading(false); })
        .catch(() => { setStatus({ connected: false, email: '', account_id: '' }); setLoading(false); });
      // Clean up the query param without a page reload
      const clean = window.location.pathname + window.location.hash;
      window.history.replaceState({}, '', clean);
    }
    if (params.get('jira_error')) {
      setError(`Jira connection failed: ${params.get('jira_error')}`);
      const clean = window.location.pathname + window.location.hash;
      window.history.replaceState({}, '', clean);
    }
  }, []);

  async function handleConnect() {
    setBusy(true);
    setError('');
    try {
      const r = await apiFetch('/api/jira/initiate', { method: 'POST' });
      const j = await r.json();
      if (j.redirect_url) {
        window.location.href = j.redirect_url;  // navigate to Atlassian — no credentials in URL
      } else {
        setError('Could not start Jira connection. Please try again.');
        setBusy(false);
      }
    } catch {
      setError('Could not start Jira connection. Please try again.');
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (!window.confirm('Disconnect your Jira account? You can reconnect at any time.')) return;
    setBusy(true);
    setError('');
    try {
      await apiFetch('/api/jira/disconnect', { method: 'POST' });
      setStatus({ connected: false, email: '', account_id: '' });
    } catch {
      setError('Failed to disconnect. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <section style={cardStyle}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 20 }}>🎫</span>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Jira Integration</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            Connect your Jira account to create tickets directly from error details.
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Checking connection…</div>
      ) : status?.connected ? (
        /* ── Connected state ─────────────────────────────────────────────── */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '8px 14px', borderRadius: 8,
            background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
          }}>
            <span style={{ color: '#34d399', fontWeight: 700, fontSize: 13 }}>✓ Connected</span>
            {status.email && (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                as <strong style={{ color: 'var(--text)' }}>{status.email}</strong>
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Tickets you create from Error Details will appear in Jira under your account.
          </div>
          <div>
            <button onClick={handleDisconnect} disabled={busy} style={{ ...btnDanger, opacity: busy ? 0.6 : 1 }}>
              {busy ? 'Disconnecting…' : 'Disconnect Jira'}
            </button>
          </div>
        </div>
      ) : (
        /* ── Not connected state ─────────────────────────────────────────── */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            You haven't connected your Jira account yet. Click below to authorise Airbrake
            to create tickets on your behalf. You only need to do this once.
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button onClick={handleConnect} style={btnPrimary}>
              Connect Jira
            </button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              You'll be redirected to Atlassian to sign in and grant access.
            </span>
          </div>
        </div>
      )}

      {error && (
        <div style={{
          marginTop: 10, fontSize: 12, color: '#f87171',
          padding: '8px 12px', borderRadius: 6,
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
        }}>
          {error}
        </div>
      )}
    </section>
  );
}
