import React from 'react';
import type { Role } from '@portal/shared';
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
