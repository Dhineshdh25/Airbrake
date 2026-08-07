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

// __API_BASE_URL__ is injected at build time by vite.config.ts `define`.
// In Jest (Node/commonjs), it falls back to empty string (tests mock fetch directly).
declare const __API_BASE_URL__: string | undefined;

export const API_BASE_URL: string =
  typeof __API_BASE_URL__ !== 'undefined' ? __API_BASE_URL__ : '';

// ─── Stable device identity ───────────────────────────────────────────────────
// Generated once per browser profile, never rotated.
// Seeded here at module load time so it exists before any apiFetch call,
// regardless of whether the user has visited ProtectedRoute yet.
// This is the key used for Jira token storage — isolates each browser session.
import { getSafeUUID } from './uuid';

function _ensureDeviceId(): string {
  let id = localStorage.getItem('device_id');
  if (!id) {
    id = getSafeUUID().replace(/-/g, '').slice(0, 16);
    localStorage.setItem('device_id', id);
  }
  return id;
}
// Seed immediately on import
const _deviceId = _ensureDeviceId();

export function getDeviceId(): string {
  return _deviceId || _ensureDeviceId();
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}: ${statusText}`);
    this.name = 'ApiError';
  }

  /** True for any client-side mistake (400–499). */
  get isClientError() { return this.status >= 400 && this.status < 500; }

  /** True for any server-side failure (500–599). */
  get isServerError() { return this.status >= 500; }

  /** Human-readable label for display in the UI. */
  get label(): string {
    switch (this.status) {
      case 400: return 'Bad Request — the request was malformed.';
      case 401: return 'Unauthorised — please log in again.';
      case 403: return 'Forbidden — you do not have permission.';
      case 404: return 'Not Found — the resource does not exist.';
      case 500: return 'Server Error — something went wrong on the server.';
      case 502: return 'Bad Gateway — the server received an invalid response.';
      case 504: return 'Gateway Timeout — the server took too long to respond.';
      default:  return `Unexpected error (HTTP ${this.status}).`;
    }
  }
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────

/**
 * Drop-in replacement for `fetch()` that:
 *  1. Prepends API_BASE_URL to every relative path.
 *  2. Throws `ApiError` for non-2xx responses.
 *  3. Forwards all other fetch options unchanged.
 */
export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  // Absolute URLs (e.g. external services) are passed through unchanged.
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;

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
export async function apiGet<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  return res.json() as Promise<T>;
}

/** POST JSON body and parse JSON response. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<T>;
}

/** PUT JSON body and parse JSON response. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<T>;
}

/** DELETE and parse JSON response. */
export async function apiDelete<T>(path: string): Promise<T> {
  const res = await apiFetch(path, { method: 'DELETE' });
  return res.json() as Promise<T>;
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
export function getWsBaseUrl(): string {
  if (!API_BASE_URL) {
    // Vite proxy mode — connect to the Vite dev server which proxies /ws
    const { protocol, host } = window.location;
    return `${protocol === 'https:' ? 'wss' : 'ws'}://${host}`;
  }
  return API_BASE_URL.replace(/^https/, 'wss').replace(/^http/, 'ws');
}
