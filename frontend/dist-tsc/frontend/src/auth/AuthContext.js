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
    // Ref so getCsrfToken() closure always reads the latest value without
    // forcing a re-render on every token update.
    const csrfRef = (0, react_1.useRef)('');
    const checkSession = (0, react_1.useCallback)(async () => {
        try {
            const url = `${api_1.API_BASE_URL}/api/auth/me`;
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
                }
                else {
                    setUser(null);
                    csrfRef.current = '';
                    setCsrfTokenMemory('');
                }
            }
            else {
                setUser(null);
                csrfRef.current = '';
                setCsrfTokenMemory('');
            }
        }
        catch {
            setUser(null);
        }
        finally {
            setLoading(false);
        }
    }, []);
    (0, react_1.useEffect)(() => {
        checkSession();
    }, [checkSession]);
    const refresh = (0, react_1.useCallback)(() => {
        setLoading(true);
        checkSession();
    }, [checkSession]);
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
        setUser(null);
        csrfRef.current = '';
        setCsrfTokenMemory('');
    }, []);
    const onUnauthorized = (0, react_1.useCallback)(() => {
        setUser(null);
        csrfRef.current = '';
        setCsrfTokenMemory('');
    }, []);
    const getCsrfToken = (0, react_1.useCallback)(() => {
        return csrfRef.current || getCsrfTokenMemory();
    }, []);
    return ((0, jsx_runtime_1.jsx)(AuthContext.Provider, { value: { user, loading, refresh, logout, onUnauthorized, getCsrfToken }, children: children }));
}
// ─── Hook ─────────────────────────────────────────────────────────────────────
function useAuth() {
    return (0, react_1.useContext)(AuthContext);
}
// ─── Legacy getCsrfToken export ────────────────────────────────────────────
// Kept for backward compatibility — existing callers use this.
// In cross-domain setups this reads from the in-memory store; in same-origin
// it also tries document.cookie as fallback.
function getCsrfToken() {
    return getCsrfTokenMemory();
}
//# sourceMappingURL=AuthContext.js.map