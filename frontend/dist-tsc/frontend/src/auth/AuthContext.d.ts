import React from 'react';
import type { Role } from '@portal/shared';
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
/** Update the in-memory CSRF token (called after login / /api/auth/me). */
export declare function setCsrfTokenMemory(token: string): void;
/** Read the in-memory CSRF token. Falls back to cookie for same-origin setups. */
export declare function getCsrfTokenMemory(): string;
export declare function AuthProvider({ children }: {
    children: React.ReactNode;
}): import("react/jsx-runtime").JSX.Element;
export declare function useAuth(): AuthState;
export declare function getCsrfToken(): string;
export {};
