import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';

interface ProtectedRouteProps {
  readonly children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();
  const { user, loading, initializationError, refresh } = useAuth();

  // Show nothing while checking the session
  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        color: 'var(--text-muted)',
        fontFamily: 'var(--font)',
        fontSize: 14,
      }}>
        Loading…
      </div>
    );
  }

  if (initializationError && !user) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        background: 'var(--bg)',
        color: 'var(--text-muted)',
        fontFamily: 'var(--font)',
        fontSize: 14,
      }}>
        <div>{initializationError}</div>
        <button onClick={refresh}>Try again</button>
      </div>
    );
  }

  // Not authenticated — redirect to login
  if (!user) {
    const redirectUri = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/auth/login?redirect_uri=${redirectUri}`} replace />;
  }

  return <>{children}</>;
}
