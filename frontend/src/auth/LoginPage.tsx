import React, { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getSafeUUID } from '../lib/uuid';

const ROLES = ['admin', 'developer', 'viewer'] as const;

export function LoginPage() {
  const [role, setRole] = useState<string>('admin');
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const bannerMessage = useMemo(() => {
    if (params.get('reason') === 'session_expired') {
      return 'Your session has expired. Please log in again.';
    }
    return null;
  }, [params]);

  const handleLogin = () => {
    // Session token identifies the role for this session.
    // Kept as a fixed pattern so the backend can resolve it.
    const token = `dev-token-${role}`;
    localStorage.setItem('session_token', token);
    localStorage.setItem('session_role', role);

    // device_id is a stable, permanent identity for this browser profile.
    // It is generated once and never rotated — survives logout/login cycles.
    // This is what the backend uses as the Jira token store key, so the
    // user only needs to connect Jira once regardless of how many times
    // they log out and back in.
    if (!localStorage.getItem('device_id')) {
      localStorage.setItem('device_id', getSafeUUID().replace(/-/g, '').slice(0, 16));
    }

    const redirect = params.get('redirect_uri') ?? '/dashboard';
    navigate(decodeURIComponent(redirect), { replace: true });
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg)',
      fontFamily: 'var(--font)',
    }}>
      <div style={{
        width: 360,
        background: 'var(--surface)',
        border: '1px solid var(--card-border)',
        borderRadius: 'var(--radius-lg)' as unknown as number,
        padding: '36px 32px',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>🔥</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
            Airbrake Portal
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Dev login — pick a role to continue</p>
        </div>

        {/* Role selector */}
        <div style={{ marginBottom: 16 }}>
          <label htmlFor="role-select" style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Role
          </label>
          <select
            id="role-select"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px',
              background: 'var(--input-bg)',
              border: '1px solid var(--input-border)',
              borderRadius: 'var(--radius-sm)' as unknown as number,
              color: 'var(--text)',
              fontSize: 14,
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
            ))}
          </select>
        </div>

        {bannerMessage ? (
          <div style={{
            marginBottom: 16,
            padding: '10px 12px',
            borderRadius: 8,
            background: 'rgba(248, 113, 113, 0.16)',
            color: '#f87171',
            fontSize: 13,
            border: '1px solid rgba(248, 113, 113, 0.25)',
          }}>
            {bannerMessage}
          </div>
        ) : null}

        {/* Sign in button */}
        <button
          onClick={handleLogin}
          style={{
            width: '100%',
            padding: '11px',
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 'var(--radius-sm)' as unknown as number,
            fontSize: 14,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background var(--transition)',
          }}
        >
          Sign in
        </button>
      </div>
    </div>
  );
}
