import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
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
  /** A network/server failure while checking the session, if any. */
  initializationError: string | null;
  /** Force a re-check of the session (e.g. after OAuth redirect). */
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
   * CSRF token returned in the /api/auth/me JSON body in a module-level ref.
   * This avoids localStorage (too persistent) and sessionStorage (fine for
   * CSRF tokens but requires an explicit key).
   *
   * The token is never null once the user is authenticated.
   */
  getCsrfToken: () => string;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  initializationError: null,
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

  const checkSession = useCallback(async () => {
    setInitializationError(null);
    try {
      const url = `${API_BASE_URL}/api/auth/me`;
      const res = await fetch(url, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setUser(data.user);
          // Persist the CSRF token that the backend includes in the response
          // body — the only reliable cross-domain delivery mechanism.
          if (data.csrf_token) {
            csrfRef.current = data.csrf_token;
            setCsrfTokenMemory(data.csrf_token);
          }
        } else {
          setUser(null);
          csrfRef.current = '';
          setCsrfTokenMemory('');
        }
      } else {
        setUser(null);
        csrfRef.current = '';
        setCsrfTokenMemory('');
        if (res.status >= 500) {
          setInitializationError('The authentication service is unavailable. Please try again.');
        }
      }
    } catch {
      setUser(null);
      setInitializationError('Unable to check your sign-in session. Please try again.');
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
        headers: {
          'X-CSRF-Token': csrfRef.current || getCsrfTokenMemory(),
        },
      });
    } catch {
      // Best-effort — clear local state regardless
    }
    setUser(null);
    csrfRef.current = '';
    setCsrfTokenMemory('');
  }, []);

  const onUnauthorized = useCallback(() => {
    setUser(null);
    csrfRef.current = '';
    setCsrfTokenMemory('');
  }, []);

  const getCsrfToken = useCallback((): string => {
    return csrfRef.current || getCsrfTokenMemory();
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, initializationError, refresh, logout, onUnauthorized, getCsrfToken }}>
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
// In cross-domain setups this reads from the in-memory store; in same-origin
// it also tries document.cookie as fallback.
export function getCsrfToken(): string {
  return getCsrfTokenMemory();
}
