"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
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
});
// ─── Provider ─────────────────────────────────────────────────────────────────
function AuthProvider({ children }) {
    const [user, setUser] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const checkSession = (0, react_1.useCallback)(async () => {
        try {
            const url = `${api_1.API_BASE_URL}/api/auth/me`;
            const res = await fetch(url, { credentials: 'include' });
            if (res.ok) {
                const data = await res.json();
                if (data.authenticated && data.user) {
                    setUser(data.user);
                }
                else {
                    setUser(null);
                }
            }
            else {
                setUser(null);
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
                headers: { 'X-CSRF-Token': getCsrfToken() },
            });
        }
        catch {
            // Best-effort — clear local state regardless
        }
        setUser(null);
    }, []);
    const onUnauthorized = (0, react_1.useCallback)(() => {
        setUser(null);
    }, []);
    return ((0, jsx_runtime_1.jsx)(AuthContext.Provider, { value: { user, loading, refresh, logout, onUnauthorized }, children: children }));
}
// ─── Hook ─────────────────────────────────────────────────────────────────────
function useAuth() {
    return (0, react_1.useContext)(AuthContext);
}
// ─── CSRF helper ──────────────────────────────────────────────────────────────
/**
 * Read the csrf_token cookie value from document.cookie.
 * This cookie is NOT HttpOnly so JavaScript can read it.
 */
function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}
//# sourceMappingURL=AuthContext.js.map