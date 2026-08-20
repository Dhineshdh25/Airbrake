import React, { useCallback, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import { apiFetch } from '../lib/api';

// Non-Jira links — plain React Router <Link>
const PLAIN_NAV_LINKS = [
  { to: '/dashboard', label: 'Dashboard', icon: '▦' },
  { to: '/logs',      label: 'Log Stream', icon: '≡' },
  { to: '/breaks',    label: 'Breaks',     icon: '⚡' },
  { to: '/settings',  label: 'Settings',   icon: '⚙' },
];

interface Props {
  children: React.ReactNode;
}

export function Layout({ children }: Props) {
  const { theme, setTheme } = useTheme();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isDark = theme === 'dark';

  // Cache the last-known Jira connection status so repeated clicks don't
  // fire an extra network request. Invalidated after 60 s.
  const jiraStatusCache = useRef<{ connected: boolean; ts: number } | null>(null);

  const handleLogout = async () => {
    await logout();
    navigate('/auth/login', { replace: true });
  };

  /**
   * Jira nav click handler.
   *
   * 1. If the user has no Airbrake session yet → do nothing special; the
   *    ProtectedRoute will redirect to login. This path should never happen
   *    in practice because Layout is rendered inside ProtectedRoute.
   *
   * 2. If Jira IS connected → navigate to /jira normally.
   *
   * 3. If Jira is NOT connected → navigate to /settings and scroll to the
   *    Jira Integration section.  Do NOT start Google OAuth.
   *
   * We call /api/jira/status (already called by JiraSettings on mount, so
   * the Lambda response is usually cached at the CDN level and is fast).
   */
  const handleJiraClick = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();

      // No user session — let the normal ProtectedRoute handle it
      if (!user) {
        navigate('/jira');
        return;
      }

      // Use cached result if fresh (< 60 s)
      const now = Date.now();
      if (jiraStatusCache.current && now - jiraStatusCache.current.ts < 60_000) {
        if (jiraStatusCache.current.connected) {
          navigate('/jira');
        } else {
          navigate('/settings?jira_section=1', { replace: false });
        }
        return;
      }

      // Fetch fresh status
      try {
        const r = await apiFetch('/api/jira/status');
        const d = await r.json() as { connected: boolean };
        jiraStatusCache.current = { connected: d.connected, ts: Date.now() };
        if (d.connected) {
          navigate('/jira');
        } else {
          // Redirect to Settings → Jira Integration section.
          // Do NOT navigate to /auth/login or start Google OAuth.
          navigate('/settings?jira_section=1', { replace: false });
        }
      } catch {
        // Network error — fall through to /jira which shows its own error state
        navigate('/jira');
      }
    },
    [user, navigate],
  );

  // Shared nav item styles
  function navItemStyle(active: boolean): React.CSSProperties {
    return {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '9px 12px',
      borderRadius: 'var(--radius-sm)',
      color: active ? '#fff' : 'rgba(255,255,255,0.5)',
      fontWeight: active ? 600 : 400,
      fontSize: 13.5,
      background: active ? 'var(--accent-glow)' : 'transparent',
      boxShadow: active ? 'inset 0 0 0 1px rgba(99,102,241,0.3)' : 'none',
      transition: 'all var(--transition)',
      textDecoration: 'none',
      cursor: 'pointer',
      border: 'none',
      width: '100%',
      textAlign: 'left',
    };
  }

  const jiraActive = location.pathname === '/jira' || location.pathname.startsWith('/jira/');

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font)' }}>
      {/* Sidebar */}
      <nav style={{
        width: 220,
        background: 'var(--sidebar-bg)',
        borderRight: '1px solid var(--sidebar-border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        position: 'sticky',
        top: 0,
        height: '100vh',
      }}>
        {/* Logo */}
        <div style={{
          padding: '20px 20px 18px',
          borderBottom: '1px solid var(--sidebar-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <span style={{ fontSize: 20 }}>🔥</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: 0.3 }}>Airbrake</div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: 0.5, textTransform: 'uppercase' }}>Portal</div>
          </div>
        </div>

        {/* Nav links */}
        <div style={{ flex: 1, padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {PLAIN_NAV_LINKS.map(({ to, label, icon }) => {
            const active = location.pathname === to || location.pathname.startsWith(to + '/');
            return (
              <Link
                key={to}
                to={to}
                style={navItemStyle(active) as React.CSSProperties}
              >
                <span style={{ fontSize: 14, opacity: active ? 1 : 0.6, width: 18, textAlign: 'center' }}>{icon}</span>
                {label}
                {active && (
                  <span style={{
                    marginLeft: 'auto',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    boxShadow: '0 0 6px var(--accent)',
                  }} />
                )}
              </Link>
            );
          })}

          {/* Jira — connection-aware nav item */}
          <button
            onClick={handleJiraClick}
            style={navItemStyle(jiraActive) as React.CSSProperties}
            aria-current={jiraActive ? 'page' : undefined}
          >
            <span style={{ fontSize: 14, opacity: jiraActive ? 1 : 0.6, width: 18, textAlign: 'center' }}>🔗</span>
            Jira
            {jiraActive && (
              <span style={{
                marginLeft: 'auto',
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--accent)',
                boxShadow: '0 0 6px var(--accent)',
              }} />
            )}
          </button>
        </div>

        {/* Theme toggle */}
        <div style={{ padding: '14px 10px', borderTop: '1px solid var(--sidebar-border)' }}>
          {user && (
            <div style={{
              marginBottom: 8,
              padding: '6px 12px',
              fontSize: 11.5,
              color: 'rgba(255,255,255,0.5)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {user.email}
            </div>
          )}
          <button
            onClick={handleLogout}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              marginBottom: 6,
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.15)',
              borderRadius: 'var(--radius-sm)',
              color: 'rgba(255,255,255,0.6)',
              cursor: 'pointer',
              fontSize: 12.5,
              transition: 'all var(--transition)',
            }}
          >
            <span>↪</span>
            Sign out
          </button>
          <button
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 'var(--radius-sm)',
              color: 'rgba(255,255,255,0.6)',
              cursor: 'pointer',
              fontSize: 12.5,
              transition: 'all var(--transition)',
            }}
          >
            <span>{isDark ? '☀️' : '🌙'}</span>
            {isDark ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, padding: '32px 36px', overflowY: 'auto', minWidth: 0 }}>
        {children}
      </main>
    </div>
  );
}
