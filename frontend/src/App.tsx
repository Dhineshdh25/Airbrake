import React from 'react';
import React, { useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { LoginPage } from './auth/LoginPage';
import { ThemeProvider } from './theme/ThemeContext';
import { Layout } from './layout/Layout';
import { Dashboard } from './dashboard/Dashboard';
import { LogStream } from './logs/LogStream';
import { BreaksList } from './breaks/BreaksList';
import { ErrorDetail } from './breaks/ErrorDetail';
import { JiraOverview } from './jira/JiraOverview';
import { Settings } from './settings/Settings';
import type { Role } from '@portal/shared';

function getRole(): Role {
  const stored = localStorage.getItem('session_role');
  if (stored === 'admin' || stored === 'developer' || stored === 'viewer') return stored;
  return 'viewer';
}

/**
 * Handles OAuth callback redirects from the backend.
 *
 * S3 static hosting can only serve index.html at the root path. The backend
 * callback redirects to the root URL with ?redirect=/settings&jira_connected=true
 * instead of directly to /settings (which S3 would 404).
 *
 * This component runs on every page load and immediately navigates to the
 * intended path, preserving the OAuth result query params for JiraSettings.tsx.
 */
function OAuthRedirectHandler() {
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const redirectTo = params.get('redirect');
    if (!redirectTo) return;

    // Build destination URL with OAuth params preserved, minus the redirect param
    params.delete('redirect');
    const qs = params.toString();
    const destination = redirectTo + (qs ? `?${qs}` : '');

    // Replace current history entry so back button doesn't loop
    navigate(destination, { replace: true });
  }, [navigate]);

  return null;
}

function AppShell() {
  const role = getRole();
  return (
    <Layout>
      <OAuthRedirectHandler />
      <Routes>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/logs" element={<LogStream />} />
        <Route path="/breaks" element={<BreaksList />} />
        <Route path="/breaks/:errorHash" element={<ErrorDetail />} />
        <Route path="/jira" element={<JiraOverview />} />
        <Route path="/settings" element={<Settings role={role} />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth/login" element={<LoginPage />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
