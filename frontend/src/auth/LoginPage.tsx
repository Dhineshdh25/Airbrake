import React, { FormEvent, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from './AuthContext';

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { login, initializationError } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  // auth_error query param covers server-side redirects (e.g. jira errors)
  const authError = params.get('auth_error');
  const AUTH_ERROR_MESSAGES: Record<string, string> = {
    authentication_failed: 'Authentication failed. Please try again.',
    session_expired: 'Your session has expired. Please sign in again.',
  };
  const paramErrorMessage = authError
    ? AUTH_ERROR_MESSAGES[authError] ?? 'Authentication failed. Please try again.'
    : null;

  const displayError = loginError ?? paramErrorMessage ?? initializationError;

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setLoginError(null);
    setSubmitting(true);

    try {
      const redirectUri = params.get('redirect_uri') ?? '/dashboard';
      const ok = await login(username, password);
      if (ok) {
        navigate(redirectUri, { replace: true });
      } else {
        setLoginError('Invalid username or password.');
      }
    } catch {
      setLoginError('Unable to connect. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#0a0f1e',
      fontFamily: 'var(--font, system-ui, sans-serif)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Subtle dot-grid background */}
      <div style={{
        position: 'absolute',
        inset: 0,
        backgroundImage:
          'radial-gradient(circle, rgba(99,102,241,0.15) 1px, transparent 1px)',
        backgroundSize: '28px 28px',
        pointerEvents: 'none',
      }} />

      {/* Auth card */}
      <div style={{
        position: 'relative',
        width: 420,
        maxWidth: 'calc(100vw - 32px)',
        background: 'rgba(15,23,42,0.95)',
        border: '1px solid rgba(99,102,241,0.25)',
        borderRadius: 16,
        padding: '44px 40px 40px',
        boxShadow: '0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(99,102,241,0.1)',
        backdropFilter: 'blur(12px)',
      }}>
        {/* Branding */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          {/* MPS Labs logo mark */}
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 52,
            height: 52,
            borderRadius: 14,
            background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
            marginBottom: 16,
            boxShadow: '0 8px 24px rgba(99,102,241,0.4)',
          }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                stroke="#fff"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.1em',
            color: '#6366f1', textTransform: 'uppercase', marginBottom: 8 }}>
            MPS Labs
          </div>

          <h1 style={{
            fontSize: 22,
            fontWeight: 700,
            color: '#f1f5f9',
            margin: 0,
            marginBottom: 8,
            letterSpacing: '-0.3px',
          }}>
            Airbrake Dashboard
          </h1>
          <p style={{ fontSize: 14, color: '#94a3b8', margin: 0 }}>
            Sign in to your account
          </p>
        </div>

        {/* Error banner */}
        {displayError && (
          <div role="alert" style={{
            marginBottom: 20,
            padding: '10px 14px',
            background: 'rgba(239,68,68,0.12)',
            border: '1px solid rgba(239,68,68,0.35)',
            borderRadius: 8,
            fontSize: 13,
            color: '#fca5a5',
            lineHeight: 1.5,
          }}>
            {displayError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {/* Username field */}
          <div style={{ marginBottom: 18 }}>
            <label htmlFor="login-username" style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 500,
              color: '#cbd5e1',
              marginBottom: 7,
            }}>
              Username
            </label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              placeholder="Enter your username"
              value={username}
              onChange={e => setUsername(e.target.value)}
              disabled={submitting}
              required
              style={{
                width: '100%',
                padding: '11px 14px',
                background: 'rgba(30,41,59,0.8)',
                border: '1px solid rgba(99,102,241,0.3)',
                borderRadius: 8,
                fontSize: 14,
                color: '#f1f5f9',
                outline: 'none',
                boxSizing: 'border-box',
                transition: 'border-color 0.2s',
              }}
              onFocus={e => { e.target.style.borderColor = 'rgba(99,102,241,0.7)'; }}
              onBlur={e => { e.target.style.borderColor = 'rgba(99,102,241,0.3)'; }}
            />
          </div>

          {/* Password field */}
          <div style={{ marginBottom: 20 }}>
            <label htmlFor="login-password" style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 500,
              color: '#cbd5e1',
              marginBottom: 7,
            }}>
              Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                disabled={submitting}
                required
                style={{
                  width: '100%',
                  padding: '11px 44px 11px 14px',
                  background: 'rgba(30,41,59,0.8)',
                  border: '1px solid rgba(99,102,241,0.3)',
                  borderRadius: 8,
                  fontSize: 14,
                  color: '#f1f5f9',
                  outline: 'none',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.2s',
                }}
                onFocus={e => { e.target.style.borderColor = 'rgba(99,102,241,0.7)'; }}
                onBlur={e => { e.target.style.borderColor = 'rgba(99,102,241,0.3)'; }}
              />
              {/* Eye icon */}
              <button
                type="button"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword(v => !v)}
                style={{
                  position: 'absolute',
                  right: 12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  padding: 4,
                  cursor: 'pointer',
                  color: '#64748b',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                {showPassword ? (
                  /* Eye-off */
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  /* Eye */
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {/* Remember me */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
            <input
              id="remember-me"
              type="checkbox"
              checked={rememberMe}
              onChange={e => setRememberMe(e.target.checked)}
              style={{ width: 15, height: 15, accentColor: '#6366f1', cursor: 'pointer' }}
            />
            <label htmlFor="remember-me" style={{
              fontSize: 13,
              color: '#94a3b8',
              cursor: 'pointer',
              userSelect: 'none',
            }}>
              Remember me
            </label>
          </div>

          {/* Sign In button */}
          <button
            type="submit"
            disabled={submitting || !username || !password}
            style={{
              width: '100%',
              padding: '12px',
              background: submitting || !username || !password
                ? 'rgba(99,102,241,0.4)'
                : 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              fontSize: 15,
              fontWeight: 600,
              cursor: submitting || !username || !password ? 'not-allowed' : 'pointer',
              transition: 'opacity 0.2s, background 0.2s',
              letterSpacing: '0.02em',
              boxShadow: submitting || !username || !password
                ? 'none'
                : '0 4px 16px rgba(99,102,241,0.4)',
            }}
          >
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
