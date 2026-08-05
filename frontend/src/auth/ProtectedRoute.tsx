import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getSafeUUID } from '../lib/uuid';

const SESSION_TOKEN_KEY = 'session_token';

interface ProtectedRouteProps {
  readonly children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();
  const token = localStorage.getItem(SESSION_TOKEN_KEY);

  if (!token) {
    const redirectUri = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/auth/login?redirect_uri=${redirectUri}`} replace />;
  }

  // Ensure every authenticated browser session has a stable device_id.
  // This runs on every page load so already-logged-in users get one
  // immediately without needing to log out and back in.
  if (!localStorage.getItem('device_id')) {
    localStorage.setItem(
      'device_id',
      getSafeUUID().replace(/-/g, '').slice(0, 16),
    );
  }

  return <>{children}</>;
}
