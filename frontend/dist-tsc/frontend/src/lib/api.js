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
exports.ApiError = exports.FRONTEND_BASE_URL = exports.API_BASE_URL = void 0;
exports.buildAirbrakeErrorUrl = buildAirbrakeErrorUrl;
exports.getDeviceId = getDeviceId;
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
/** Build a deep-link URL to a specific error in Airbrake.
 *  Uses HashRouter format: <origin>/#/breaks/<hash>?project_name=<project>
 */
function buildAirbrakeErrorUrl(errorHash, projectName) {
    const base = exports.FRONTEND_BASE_URL.replace(/\/$/, '');
    const qs = projectName ? `?project_name=${encodeURIComponent(projectName)}` : '';
    return `${base}/#/breaks/${errorHash}${qs}`;
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
 *  2. Throws `ApiError` for non-2xx responses.
 *  3. Forwards all other fetch options unchanged.
 */
async function apiFetch(path, init) {
    // Absolute URLs (e.g. external services) are passed through unchanged.
    const url = path.startsWith('http') ? path : `${exports.API_BASE_URL}${path}`;
    const response = await fetch(url, {
        ...init,
        headers: {
            // Attach auth token when present (dev token or real JWT).
            ...(localStorage.getItem('session_token')
                ? { Authorization: `Bearer ${localStorage.getItem('session_token')}` }
                : {}),
            // Stable device identity — always present, seeded at module load time.
            'X-Device-ID': getDeviceId(),
            ...(init?.headers ?? {}),
        },
    });
    if (!response.ok) {
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