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
export declare const API_BASE_URL: string;
/** The Airbrake frontend base URL, baked in at build time.
 *  Used to generate deep-link URLs that must stay on HTTP (S3 static site)
 *  and must include the hash prefix for HashRouter compatibility.
 *  e.g. http://airbrake.s3-website-us-east-1.amazonaws.com
 */
export declare const FRONTEND_BASE_URL: string;
/** Build a deep-link URL to a specific error occurrence in Airbrake.
 *  Uses HashRouter format: <origin>/#/breaks/<hash>?project_name=<project>&log_id=<id>
 *  log_id targets the exact occurrence so the modal opens that specific row.
 */
export declare function buildAirbrakeErrorUrl(errorHash: string, projectName?: string, logId?: string | null): string;
export declare function getDeviceId(): string;
/** Register the 401 handler. Called once by AuthProvider on mount. */
export declare function setOnUnauthorized(handler: () => void): void;
export declare class ApiError extends Error {
    readonly status: number;
    readonly statusText: string;
    constructor(status: number, statusText: string, message?: string);
    /** True for any client-side mistake (400–499). */
    get isClientError(): boolean;
    /** True for any server-side failure (500–599). */
    get isServerError(): boolean;
    /** Human-readable label for display in the UI. */
    get label(): string;
}
/**
 * Drop-in replacement for `fetch()` that:
 *  1. Prepends API_BASE_URL to every relative path.
 *  2. Includes credentials (cookies) for cross-origin requests.
 *  3. Attaches CSRF token for state-changing methods.
 *  4. Throws `ApiError` for non-2xx responses.
 *  5. Notifies the auth layer on 401.
 */
export declare function apiFetch(path: string, init?: RequestInit): Promise<Response>;
/** GET and parse JSON. */
export declare function apiGet<T>(path: string): Promise<T>;
/** POST JSON body and parse JSON response. */
export declare function apiPost<T>(path: string, body: unknown): Promise<T>;
/** PUT JSON body and parse JSON response. */
export declare function apiPut<T>(path: string, body: unknown): Promise<T>;
/** DELETE and parse JSON response. */
export declare function apiDelete<T>(path: string): Promise<T>;
/**
 * Converts the HTTP(S) base URL to a WS(S) URL for WebSocket connections.
 *
 * Examples:
 *   https://abc.lambda-url.us-east-1.on.aws  →  wss://abc.lambda-url.us-east-1.on.aws
 *   http://localhost:3001                     →  ws://localhost:3001
 *   '' (empty, Vite proxy)                   →  ws://localhost:3000  (Vite dev server)
 */
export declare function getWsBaseUrl(): string;
