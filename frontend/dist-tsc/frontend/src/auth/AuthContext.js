"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.setCsrfTokenMemory = setCsrfTokenMemory;
exports.getCsrfTokenMemory = getCsrfTokenMemory;
exports.AuthProvider = AuthProvider;
exports.useAuth = useAuth;
exports.getCsrfToken = getCsrfToken;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const api_1 = require("../lib/api");
const AuthContext = (0, react_1.createContext)({
    user: null,
    loading: true,
    initializationError: null,
    login: async () => false,
    refresh: () => { },
    logout: async () => { },
    onUnauthorized: () => { },
    getCsrfToken: () => '',
});
// ─── In-memory CSRF token store ────────────────────────────────────────────
// Module-level so it survives re-renders. Not in localStorage / sessionStorage
// — only the CSRF token (not the session token) is stored here.
let _csrfTokenMemory = '';
/** Update the in-memory CSRF token (called after login / /api/auth/me). */
function setCsrfTokenMemory(token) {
    _csrfTokenMemory = token || '';
}
/** Read the in-memory CSRF token. Falls back to cookie for same-origin setups. */
function getCsrfTokenMemory() {
    if (_csrfTokenMemory)
        return _csrfTokenMemory;
    // Same-origin fallback: try to read the cookie (works only when frontend
    // and backend share the same domain — e.g. local dev with Vite proxy).
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}
// ─── Provider ─────────────────────────────────────────────────────────────────
function AuthProvider({ children }) {
    const [user, setUser] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [initializationError, setInitializationError] = (0, react_1.useState)(null);
    // Ref so getCsrfToken() closure always reads the latest value without
    // forcing a re-render on every token update.
    const csrfRef = (0, react_1.useRef)('');
    /** Store CSRF token from any auth response in both the ref and module-level var */
    const _storeCsrf = (0, react_1.useCallback)((token) => {
        csrfRef.current = token;
        setCsrfTokenMemory(token);
    }, []);
    /** Clear all session state */
    const _clearSession = (0, react_1.useCallback)(() => {
        setUser(null);
        csrfRef.current = '';
        setCsrfTokenMemory('');
    }, []);
    const checkSession = (0, react_1.useCallback)(async () => {
        setInitializationError(null);
        try {
            const url = `${api_1.API_BASE_URL}/api/auth/me`;
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
                }
                else {
                    _clearSession();
                }
            }
            else {
                _clearSession();
                if (res.status >= 500) {
                    setInitializationError('The authentication service is unavailable. Please try again.');
                }
            }
        }
        catch {
            _clearSession();
            setInitializationError('Unable to check your sign-in session. Please try again.');
        }
        finally {
            setLoading(false);
        }
    }, [_storeCsrf, _clearSession]);
    (0, react_1.useEffect)(() => {
        checkSession();
    }, [checkSession]);
    const refresh = (0, react_1.useCallback)(() => {
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
    const login = (0, react_1.useCallback)(async (username, password) => {
        const url = `${api_1.API_BASE_URL}/api/auth/login`;
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
    const logout = (0, react_1.useCallback)(async () => {
        try {
            const url = `${api_1.API_BASE_URL}/api/auth/logout`;
            await fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'X-CSRF-Token': csrfRef.current || getCsrfTokenMemory(),
                },
            });
        }
        catch {
            // Best-effort — clear local state regardless
        }
        _clearSession();
    }, [_clearSession]);
    const onUnauthorized = (0, react_1.useCallback)(() => {
        _clearSession();
    }, [_clearSession]);
    const getCsrfToken = (0, react_1.useCallback)(() => {
        return csrfRef.current || getCsrfTokenMemory();
    }, []);
    return ((0, jsx_runtime_1.jsx)(AuthContext.Provider, { value: {
            user,
            loading,
            initializationError,
            login,
            refresh,
            logout,
            onUnauthorized,
            getCsrfToken,
        }, children: children }));
}
// ─── Hook ─────────────────────────────────────────────────────────────────────
function useAuth() {
    return (0, react_1.useContext)(AuthContext);
}
// ─── Legacy getCsrfToken export ────────────────────────────────────────────
// Kept for backward compatibility — existing callers use this.
function getCsrfToken() {
    return getCsrfTokenMemory();
}
//# sourceMappingURL=AuthContext.js.map