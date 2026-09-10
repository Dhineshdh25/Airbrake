import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../lib/api';
import type { Role } from '@portal/shared';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  /** username for local-auth users; falls back to email for legacy DB users */
  username: string;
  role: Role;
}

interface AuthState {
  /** The authenticated user, or null if not logged in. */
  user: AuthUser | null;
  /** True while the initial /api/auth/me check is in flight. */
  loading: boolean;
  /** A network/server failure while checking the session, if any. */
  initializationError: string | null;
  /**
   * Log in with username + password.
   * Calls POST /api/auth/login, stores the session token/CSRF token,
   * updates the user state, and returns true on success.
   * The password is never stored anywhere — only the session token is kept.
   */
  login: (username: string, password: string) => Promise<boolean>;
  /** Force a re-check of the session (e.g. after Jira OAuth redirect). */
  refresh: () => void;
  /** Log out — calls POST /api/auth/logout, clears state. */
  logout: () => Promise<void>;
  /** Called by the API layer when a 401 is received. */
  onUnauthorized: () => void;
  /**
   * Return the current in-memory CSRF token.
   *
   * In cross-domain deployments (frontend on S3, backend on Lambda) the
   * browser cannot read cookies set by a different domain, so we store the
   * CSRF token returned in the /api/auth/me (or /api/auth/login) JSON body
   * in a module-level ref.
   */
  getCsrfToken: () => string;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  initializationError: null,
  login: async () => false,
  refresh: () => {},
  logout: async () => {},
  onUnauthorized: () => {},
  getCsrfToken: () => '',
});

// ─── In-memory CSRF token store ────────────────────────────────────────────
// Module-level so it survives re-renders. Not in localStorage / sessionStorage
// — only the CSRF token (not the session token) is stored here.
let _csrfTokenMemory = '';

/** Update the in-memory CSRF token (called after login / /api/auth/me). */
export function setCsrfTokenMemory(token: string): void {
  _csrfTokenMemory = token || '';
}

/** Read the in-memory CSRF token. Falls back to cookie for same-origin setups. */
export function getCsrfTokenMemory(): string {
  if (_csrfTokenMemory) return _csrfTokenMemory;
  // Same-origin fallback: try to read the cookie (works only when frontend
  // and backend share the same domain — e.g. local dev with Vite proxy).
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [initializationError, setInitializationError] = useState<string | null>(null);
  // Ref so getCsrfToken() closure always reads the latest value without
  // forcing a re-render on every token update.
  const csrfRef = useRef('');

  /** Store CSRF token from any auth response in both the ref and module-level var */
  const _storeCsrf = useCallback((token: string) => {
    csrfRef.current = token;
    setCsrfTokenMemory(token);
  }, []);

  /** Clear all session state */
  const _clearSession = useCallback(() => {
    setUser(null);
    csrfRef.current = '';
    setCsrfTokenMemory('');
  }, []);

  const checkSession = useCallback(async () => {
    setInitializationError(null);
    try {
      const url = `${API_BASE_URL}/api/auth/me`;
      const res = await fetch(url, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setUser({
            id: data.user.id,
            username: data.user.username ?? data.user.email ?? data.user.id,
            role: data.user.role,
          });
          // Persist the CSRF token returned in the response body
          if (data.csrf_token) {
            _storeCsrf(data.csrf_token);
          }
        } else {
          _clearSession();
        }
      } else {
        _clearSession();
        if (res.status >= 500) {
          setInitializationError('The authentication service is unavailable. Please try again.');
        }
      }
    } catch {
      _clearSession();
      setInitializationError('Unable to check your sign-in session. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [_storeCsrf, _clearSession]);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const refresh = useCallback(() => {
    setLoading(true);
    checkSession();
  }, [checkSession]);

  /**
   * Log in with username + password.
   *
   * Sends POST /api/auth/login. On success:
   *   - session cookie is set by the backend response
   *   - CSRF token is stored in memory from the response body
   *   - user state is updated
   *   - returns true
   *
   * The password is NEVER stored in localStorage, sessionStorage, cookies,
   * or global React state. Only the session token (via cookie) persists.
   *
   * Returns false on invalid credentials (401). Throws on network failure.
   */
  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    const url = `${API_BASE_URL}/api/auth/login`;
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      // Only username and password are sent — role is never sent from the client
      body: JSON.stringify({ username, password }),
    });

    if (res.status === 401) {
      return false;
    }

    if (!res.ok) {
      throw new Error(`Login failed with status ${res.status}`);
    }

    const data = await res.json();
    if (!data.authenticated || !data.user) {
      return false;
    }

    // Update auth state from the login response
    setUser({
      id: data.user.id,
      username: data.user.username ?? data.user.id,
      role: data.user.role,
    });

    // Store CSRF token from login response body (cross-domain delivery)
    if (data.csrf_token) {
      _storeCsrf(data.csrf_token);
    }

    return true;
  }, [_storeCsrf]);

  const logout = useCallback(async () => {
    try {
      const url = `${API_BASE_URL}/api/auth/logout`;
      await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRF-Token': csrfRef.current || getCsrfTokenMemory(),
        },
      });
    } catch {
      // Best-effort — clear local state regardless
    }
    _clearSession();
  }, [_clearSession]);

  const onUnauthorized = useCallback(() => {
    _clearSession();
  }, [_clearSession]);

  const getCsrfToken = useCallback((): string => {
    return csrfRef.current || getCsrfTokenMemory();
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      initializationError,
      login,
      refresh,
      logout,
      onUnauthorized,
      getCsrfToken,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

// ─── Legacy getCsrfToken export ────────────────────────────────────────────
// Kept for backward compatibility — existing callers use this.
export function getCsrfToken(): string {
  return getCsrfTokenMemory();
}
