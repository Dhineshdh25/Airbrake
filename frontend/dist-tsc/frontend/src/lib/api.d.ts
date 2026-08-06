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
export declare const API_BASE_URL: string;
export declare function getDeviceId(): string;
export declare class ApiError extends Error {
    readonly status: number;
    readonly statusText: string;
    readonly body?: unknown | undefined;
    constructor(status: number, statusText: string, message?: string, body?: unknown | undefined);
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
 *  2. Throws `ApiError` for non-2xx responses.
 *  3. Forwards all other fetch options unchanged.
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
