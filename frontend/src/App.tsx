import React, { useEffect } from 'react';
import { HashRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
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
 * With HashRouter all routes are under the hash (e.g. /#/settings) so S3
 * always serves index.html for the root path and the hash never reaches S3.
 *
 * The backend redirects to:
 *   https://airbrake.s3-website.../  ?jira_connected=true
 *
 * The SPA loads at root, this handler reads the query params, then
 * navigates to /#/settings?jira_connected=true via React Router.
 */
function OAuthRedirectHandler() {
  const navigate = useNavigate();

  useEffect(() => {
    // Read params from the real URL query string (before the hash)
    const params = new URLSearchParams(window.location.search);
    const jiraConnected = params.get('jira_connected');
    const jiraError     = params.get('jira_error');

    if (!jiraConnected && !jiraError) return;

    // Clean the real URL (remove query params — they're now handled by React)
    window.history.replaceState({}, '', window.location.pathname);

    // Navigate to settings within the SPA, preserving the OAuth result param
    if (jiraConnected) {
      navigate('/settings?jira_connected=true', { replace: true });
    } else if (jiraError) {
      navigate(`/settings?jira_error=${jiraError}`, { replace: true });
    }
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
      <HashRouter>
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
      </HashRouter>
    </ThemeProvider>
  );
}
