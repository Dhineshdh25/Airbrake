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
}
export declare function AuthProvider({ children }: {
    children: React.ReactNode;
}): import("react/jsx-runtime").JSX.Element;
export declare function useAuth(): AuthState;
/**
 * Read the csrf_token cookie value from document.cookie.
 * This cookie is NOT HttpOnly so JavaScript can read it.
 */
export declare function getCsrfToken(): string;
export {};
