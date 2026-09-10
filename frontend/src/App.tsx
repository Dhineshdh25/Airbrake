import React, { useEffect } from 'react';
import { HashRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
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
import { setOnUnauthorized } from './lib/api';

/**
 * Handles Jira OAuth callback redirects from the backend.
 *
 * With HashRouter all routes are under the hash (e.g. /#/settings) so S3
 * always serves index.html for the root path and the hash never reaches S3.
 *
 * The backend redirects to:
 *   https://airbrake.s3-website.../  ?jira_connected=true
 *   https://airbrake.s3-website.../  ?jira_error=<code>
 *
 * The SPA loads at root, this handler reads the query params from the real
 * URL, then navigates within React Router.
 *
 * Note: Google OAuth auth_success handling has been removed. Login now uses
 * the local username+password form (POST /api/auth/login) which responds
 * directly with a JSON session — no OAuth redirect round-trip needed.
 */
function JiraOAuthRedirectHandler() {
  const navigate = useNavigate();

  useEffect(() => {
    // Read params from the real URL query string (before the hash)
    const params = new URLSearchParams(window.location.search);
    const jiraConnected = params.get('jira_connected');
    const jiraError     = params.get('jira_error');

    if (!jiraConnected && !jiraError) return;

    // Clean the real URL (remove query params — they're now handled by React)
    window.history.replaceState({}, '', window.location.pathname);

    // Handle Jira OAuth result
    if (jiraConnected) {
      navigate('/settings?jira_connected=true', { replace: true });
    } else if (jiraError) {
      navigate(`/settings?jira_error=${jiraError}`, { replace: true });
    }
  }, [navigate]);

  return null;
}

function RootRoute() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <Navigate to={user ? '/dashboard' : '/auth/login'} replace />;
}

/**
 * Wires the API layer's 401 handler to the auth context.
 */
function AuthApiWiring() {
  const { onUnauthorized } = useAuth();
  useEffect(() => {
    setOnUnauthorized(onUnauthorized);
  }, [onUnauthorized]);
  return null;
}

function AppShell() {
  const { user } = useAuth();
  const role = user?.role ?? 'viewer';

  return (
    <Layout>
      <Routes>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/logs" element={<LogStream />} />
        <Route path="/breaks" element={<BreaksList />} />
        <Route path="/breaks/:errorHash" element={<ErrorDetail />} />
        <Route path="/jira" element={<JiraOverview />} />
        <Route path="/settings" element={<Settings role={role} />} />
        <Route path="/" element={<RootRoute />} />
      </Routes>
    </Layout>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <HashRouter>
          <AuthApiWiring />
          <JiraOAuthRedirectHandler />
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
      </AuthProvider>
    </ThemeProvider>
  );
}
