import React, { useEffect } from 'react';
import { HashRouter, Navigate, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
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
 * Handles OAuth callback redirects from the backend.
 *
 * With HashRouter all routes are under the hash (e.g. /#/settings) so S3
 * always serves index.html for the root path and the hash never reaches S3.
 *
 * The backend redirects to:
 *   https://airbrake.s3-website.../  ?jira_connected=true
 *   https://airbrake.s3-website.../  ?auth_success=true&redirect=/dashboard
 *
 * The SPA loads at root, this handler reads the query params, then
 * navigates within React Router.
 */
function OAuthRedirectHandler() {
  const navigate = useNavigate();
  const { refresh } = useAuth();

  useEffect(() => {
    // Read params from the real URL query string (before the hash)
    const params = new URLSearchParams(window.location.search);
    const jiraConnected = params.get('jira_connected');
    const jiraError     = params.get('jira_error');
    const authSuccess   = params.get('auth_success');
    const authError     = params.get('auth_error');
    const authRedirect  = params.get('redirect');

    if (!jiraConnected && !jiraError && !authSuccess && !authError) return;

    // Clean the real URL (remove query params — they're now handled by React)
    window.history.replaceState({}, '', window.location.pathname);

    // Handle auth success — refresh the session state
    if (authSuccess) {
      refresh();
      const target = authRedirect ?? '/dashboard';
      navigate(target, { replace: true });
      return;
    }

    // Handle auth error — redirect to login with error
    if (authError) {
      const knownError = ['access_denied', 'organization_only', 'email_not_verified'].includes(authError)
        ? authError
        : 'authentication_failed';
      navigate(`/auth/login?auth_error=${knownError}`, { replace: true });
      return;
    }

    // Handle Jira OAuth result
    if (jiraConnected) {
      navigate('/settings?jira_connected=true', { replace: true });
    } else if (jiraError) {
      navigate(`/settings?jira_error=${jiraError}`, { replace: true });
    }
  }, [navigate, refresh]);

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

function LoginWithError() {
  return <LoginPage />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <HashRouter>
          <AuthApiWiring />
          <OAuthRedirectHandler />
          <Routes>
            <Route path="/auth/login" element={<LoginWithError />} />
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
