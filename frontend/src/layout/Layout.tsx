import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';

const NAV_LINKS = [
  { to: '/dashboard', label: 'Dashboard', icon: '▦' },
  { to: '/logs', label: 'Log Stream', icon: '≡' },
  { to: '/breaks', label: 'Breaks', icon: '⚡' },
  { to: '/jira', label: 'Jira', icon: '🔗' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
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

  const handleLogout = async () => {
    await logout();
    navigate('/auth/login', { replace: true });
  };

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
          {NAV_LINKS.map(({ to, label, icon }) => {
            const active = location.pathname === to || location.pathname.startsWith(to + '/');
            return (
              <Link
                key={to}
                to={to}
                style={{
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
                }}
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
