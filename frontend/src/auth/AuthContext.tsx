import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { API_BASE_URL } from '../lib/api';
import type { Role } from '@portal/shared';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  email: string;
  role: Role;
}

interface AuthState {
  /** The authenticated user, or null if not logged in. */
  user: AuthUser | null;
  /** True while the initial /api/auth/me check is in flight. */
  loading: boolean;
  /** Force a re-check of the session (e.g. after OAuth redirect). */
  refresh: () => void;
  /** Log out — calls POST /api/auth/logout, clears state. */
  logout: () => Promise<void>;
  /** Called by the API layer when a 401 is received. */
  onUnauthorized: () => void;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  refresh: () => {},
  logout: async () => {},
  onUnauthorized: () => {},
});

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const checkSession = useCallback(async () => {
    try {
      const url = `${API_BASE_URL}/api/auth/me`;
      const res = await fetch(url, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setUser(data.user);
        } else {
          setUser(null);
        }
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const refresh = useCallback(() => {
    setLoading(true);
    checkSession();
  }, [checkSession]);

  const logout = useCallback(async () => {
    try {
      const url = `${API_BASE_URL}/api/auth/logout`;
      await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': getCsrfToken() },
      });
    } catch {
      // Best-effort — clear local state regardless
    }
    setUser(null);
  }, []);

  const onUnauthorized = useCallback(() => {
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout, onUnauthorized }}>
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

// ─── CSRF helper ──────────────────────────────────────────────────────────────

/**
 * Read the csrf_token cookie value from document.cookie.
 * This cookie is NOT HttpOnly so JavaScript can read it.
 */
export function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}
