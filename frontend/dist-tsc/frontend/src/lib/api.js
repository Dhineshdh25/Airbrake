"use strict";
/**
 * Centralized API client for the Airbrake frontend.
 *
 * All fetch calls go through `apiFetch()` so that:
 *  - The base URL is read from VITE_API_BASE_URL (falls back to '' for
 *    local Vite-proxy dev mode).
 *  - HTTP error codes (4xx / 5xx) are turned into typed ApiError instances
 *    instead of silently returning bad JSON.
 *  - Auth headers can be injected in one place when needed.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.ApiError = exports.API_BASE_URL = void 0;
exports.getDeviceId = getDeviceId;
exports.apiFetch = apiFetch;
exports.apiGet = apiGet;
exports.apiPost = apiPost;
exports.apiPut = apiPut;
exports.apiDelete = apiDelete;
exports.getWsBaseUrl = getWsBaseUrl;
exports.API_BASE_URL = typeof __API_BASE_URL__ !== 'undefined' ? __API_BASE_URL__ : '';
// ─── Stable device identity ───────────────────────────────────────────────────
// Generated once per browser profile, never rotated.
// Seeded here at module load time so it exists before any apiFetch call,
// regardless of whether the user has visited ProtectedRoute yet.
// This is the key used for Jira token storage — isolates each browser session.
const uuid_1 = require("./uuid");
function _ensureDeviceId() {
    let id = localStorage.getItem('device_id');
    if (!id) {
        id = (0, uuid_1.getSafeUUID)().replace(/-/g, '').slice(0, 16);
        localStorage.setItem('device_id', id);
    }
    return id;
}
// Seed immediately on import
const _deviceId = _ensureDeviceId();
function getDeviceId() {
    return _deviceId || _ensureDeviceId();
}
class ApiError extends Error {
    constructor(status, statusText, message, body) {
        super(message ?? `HTTP ${status}: ${statusText}`);
        this.status = status;
        this.statusText = statusText;
        this.body = body;
        this.name = 'ApiError';
    }
    /** True for any client-side mistake (400–499). */
    get isClientError() { return this.status >= 400 && this.status < 500; }
    /** True for any server-side failure (500–599). */
    get isServerError() { return this.status >= 500; }
    /** Human-readable label for display in the UI. */
    get label() {
        switch (this.status) {
            case 400: return 'Bad Request — the request was malformed.';
            case 401: return 'Unauthorised — please log in again.';
            case 403: return 'Forbidden — you do not have permission.';
            case 404: return 'Not Found — the resource does not exist.';
            case 500: return 'Server Error — something went wrong on the server.';
            case 502: return 'Bad Gateway — the server received an invalid response.';
            case 504: return 'Gateway Timeout — the server took too long to respond.';
            default: return `Unexpected error (HTTP ${this.status}).`;
        }
    }
}
exports.ApiError = ApiError;
// ─── Core fetch wrapper ───────────────────────────────────────────────────────
/**
 * Drop-in replacement for `fetch()` that:
 *  1. Prepends API_BASE_URL to every relative path.
 *  2. Throws `ApiError` for non-2xx responses.
 *  3. Forwards all other fetch options unchanged.
 */
async function apiFetch(path, init) {
    // Absolute URLs (e.g. external services) are passed through unchanged.
    const url = path.startsWith('http') ? path : `${exports.API_BASE_URL}${path}`;
    // Ensure we have a session token for authenticated endpoints.
    const token = localStorage.getItem('session_token') || '';
    // Build headers with sensible defaults. Allow caller to override via init.headers.
    const headers = {
        // Attach Authorization header (may be empty if no token).
        Authorization: `Bearer ${token}`,
        // Stable device identity — always present, seeded at module load time.
        'X-Device-ID': getDeviceId(),
        // Default to JSON for API requests. Caller may override.
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
    };
    // Log header presence for debugging (only in dev).
    try {
        console.debug('[apiFetch] Authorization header present:', Boolean(token));
    }
    catch (e) {
        // ignore in non-browser environments (jest)
    }
    // If there's no token, proactively redirect to login instead of calling the API.
    if (!token && path.startsWith('/api')) {
        // Clear any partial session state and send user to login.
        localStorage.removeItem('session_token');
        try {
            window.location.href = '/auth/login';
        }
        catch (e) { }
        throw new ApiError(401, 'Unauthorized', 'No session token', { error: 'Session expired' });
    }
    const response = await fetch(url, {
        ...init,
        headers,
    });
    if (!response.ok) {
        // Try to parse JSON body for richer errors
        let parsedBody = undefined;
        try {
            const txt = await response.text();
            parsedBody = txt ? JSON.parse(txt) : undefined;
        }
        catch (e) {
            parsedBody = undefined;
        }
        const apiErr = new ApiError(response.status, response.statusText, undefined, parsedBody);
        // On 401, clear session and redirect to login automatically.
        if (response.status === 401) {
            try {
                console.warn('[apiFetch] Received 401 — clearing session and redirecting to login');
                localStorage.removeItem('session_token');
                localStorage.removeItem('session_role');
                window.location.href = '/auth/login';
            }
            catch (e) {
                // ignore
            }
        }
        throw apiErr;
    }
    return response;
}
// ─── Convenience helpers ──────────────────────────────────────────────────────
/** GET and parse JSON. */
async function apiGet(path) {
    const res = await apiFetch(path);
    return res.json();
}
/** POST JSON body and parse JSON response. */
async function apiPost(path, body) {
    const res = await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}
/** PUT JSON body and parse JSON response. */
async function apiPut(path, body) {
    const res = await apiFetch(path, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}
/** DELETE and parse JSON response. */
async function apiDelete(path) {
    const res = await apiFetch(path, { method: 'DELETE' });
    return res.json();
}
// ─── WebSocket URL helper ─────────────────────────────────────────────────────
/**
 * Converts the HTTP(S) base URL to a WS(S) URL for WebSocket connections.
 *
 * Examples:
 *   https://abc.lambda-url.us-east-1.on.aws  →  wss://abc.lambda-url.us-east-1.on.aws
 *   http://localhost:3001                     →  ws://localhost:3001
 *   '' (empty, Vite proxy)                   →  ws://localhost:3000  (Vite dev server)
 */
function getWsBaseUrl() {
    if (!exports.API_BASE_URL) {
        // Vite proxy mode — connect to the Vite dev server which proxies /ws
        const { protocol, host } = window.location;
        return `${protocol === 'https:' ? 'wss' : 'ws'}://${host}`;
    }
    return exports.API_BASE_URL.replace(/^https/, 'wss').replace(/^http/, 'ws');
}
//# sourceMappingURL=api.js.map