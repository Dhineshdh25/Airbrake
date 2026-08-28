"use strict";
/**
 * Centralized API client for the Airbrake frontend.
 *
 * All fetch calls go through `apiFetch()` so that:
 *  - The base URL is read from VITE_API_BASE_URL (falls back to '' for
 *    local Vite-proxy dev mode).
 *  - HTTP error codes (4xx / 5xx) are turned into typed ApiError instances
 *    instead of silently returning bad JSON.
 *  - Session cookies are included automatically (credentials: 'include').
 *  - CSRF token is attached for state-changing methods.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.ApiError = exports.FRONTEND_BASE_URL = exports.API_BASE_URL = void 0;
exports.buildAirbrakeErrorUrl = buildAirbrakeErrorUrl;
exports.getDeviceId = getDeviceId;
exports.setOnUnauthorized = setOnUnauthorized;
exports.apiFetch = apiFetch;
exports.apiGet = apiGet;
exports.apiPost = apiPost;
exports.apiPut = apiPut;
exports.apiDelete = apiDelete;
exports.getWsBaseUrl = getWsBaseUrl;
exports.API_BASE_URL = typeof __API_BASE_URL__ !== 'undefined' ? __API_BASE_URL__ : '';
/** The Airbrake frontend base URL, baked in at build time.
 *  Used to generate deep-link URLs that must stay on HTTP (S3 static site)
 *  and must include the hash prefix for HashRouter compatibility.
 *  e.g. http://airbrake.s3-website-us-east-1.amazonaws.com
 */
exports.FRONTEND_BASE_URL = typeof __FRONTEND_BASE_URL__ !== 'undefined'
    ? __FRONTEND_BASE_URL__
    : window.location.origin;
/** Build a deep-link URL to a specific error occurrence in Airbrake.
 *  Uses HashRouter format: <origin>/#/breaks/<hash>?project_name=<project>&log_id=<id>
 *  log_id targets the exact occurrence so the modal opens that specific row.
 */
function buildAirbrakeErrorUrl(errorHash, projectName, logId) {
    const base = exports.FRONTEND_BASE_URL.replace(/\/$/, '');
    const qs = new URLSearchParams();
    if (projectName)
        qs.set('project_name', projectName);
    if (logId)
        qs.set('log_id', logId);
    const qsStr = qs.toString();
    return `${base}/#/breaks/${errorHash}${qsStr ? `?${qsStr}` : ''}`;
}
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
// ─── CSRF helper ──────────────────────────────────────────────────────────────
/**
 * Return the current CSRF token for attaching to state-changing requests.
 *
 * Cross-domain deployments (frontend on S3, backend on Lambda):
 *   JavaScript cannot read cookies set by a different domain.
 *   The CSRF token is therefore stored in memory by AuthContext after it
 *   is received from the /api/auth/me response body.
 *   We import getCsrfTokenMemory() from AuthContext for this purpose.
 *
 * Same-origin deployments (Vite proxy, localhost):
 *   Falls back to reading document.cookie directly.
 */
const AuthContext_1 = require("../auth/AuthContext");
function getCsrfToken() {
    // Primary: in-memory store populated from /api/auth/me response body.
    const mem = (0, AuthContext_1.getCsrfTokenMemory)();
    if (mem)
        return mem;
    // Fallback: document.cookie works in same-origin setups only.
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}
/** Methods that require CSRF token. */
const CSRF_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
// ─── 401 handler ──────────────────────────────────────────────────────────────
/** Callback invoked when a 401 is received. Set by AuthContext. */
let _onUnauthorized = null;
/** Register the 401 handler. Called once by AuthProvider on mount. */
function setOnUnauthorized(handler) {
    _onUnauthorized = handler;
}
// ─── ApiError ─────────────────────────────────────────────────────────────────
class ApiError extends Error {
    constructor(status, statusText, message) {
        super(message ?? `HTTP ${status}: ${statusText}`);
        this.status = status;
        this.statusText = statusText;
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
 *  2. Includes credentials (cookies) for cross-origin requests.
 *  3. Attaches CSRF token for state-changing methods.
 *  4. Throws `ApiError` for non-2xx responses.
 *  5. Notifies the auth layer on 401.
 */
async function apiFetch(path, init) {
    // Absolute URLs (e.g. external services) are passed through unchanged.
    const url = path.startsWith('http') ? path : `${exports.API_BASE_URL}${path}`;
    const method = (init?.method ?? 'GET').toUpperCase();
    // Build headers
    const headers = {
        // Stable device identity — always present, seeded at module load time.
        'X-Device-ID': getDeviceId(),
    };
    // Attach CSRF token for state-changing methods.
    // Always attach when the token is available — the backend accepts it
    // from the header regardless of whether the cookie is also present.
    if (CSRF_METHODS.has(method)) {
        const csrf = getCsrfToken();
        if (csrf) {
            headers['X-CSRF-Token'] = csrf;
        }
    }
    const response = await fetch(url, {
        ...init,
        credentials: 'include',
        headers: {
            ...headers,
            ...(init?.headers ?? {}),
        },
    });
    if (!response.ok) {
        // Notify auth layer on 401 so it can redirect to login
        if (response.status === 401 && _onUnauthorized) {
            _onUnauthorized();
        }
        throw new ApiError(response.status, response.statusText);
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