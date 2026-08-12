import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { API_BASE_URL } from '../lib/api';

export function LoginPage() {
  const [params] = useSearchParams();
  const authError = params.get('auth_error');

  const handleGoogleLogin = () => {
    // Redirect to the backend Google OAuth endpoint.
    // The backend will redirect to Google, then back to /api/auth/google/callback,
    // which sets the session cookie and redirects to the frontend.
    const redirectUri = params.get('redirect_uri') ?? '/dashboard';
    const url = `${API_BASE_URL}/api/auth/google?redirect_uri=${encodeURIComponent(redirectUri)}`;
    window.location.href = url;
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
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Sign in to continue</p>
        </div>

        {/* Error message */}
        {authError && (
          <div style={{
            marginBottom: 16,
            padding: '10px 14px',
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 'var(--radius-sm)' as unknown as number,
            fontSize: 13,
            color: '#ef4444',
          }}>
            {authError === 'access_denied'
              ? 'Access denied. Your account is not provisioned for this application.'
              : `Authentication failed: ${authError.replace(/_/g, ' ')}`}
          </div>
        )}

        {/* Google sign in button */}
        <button
          onClick={handleGoogleLogin}
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
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Continue with Google
        </button>
      </div>
    </div>
  );
}
