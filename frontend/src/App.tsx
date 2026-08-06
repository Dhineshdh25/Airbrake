import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
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

function AppShell() {
  const role = getRole();
  return (
    <Layout>
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
