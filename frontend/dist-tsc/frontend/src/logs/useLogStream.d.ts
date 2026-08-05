/**
 * WebSocket-based live log stream hook.
 * Requirements: 1.1, 1.2, 1.3
 */
import type { LogRecord } from '@portal/shared';
export type ConnectionState = 'connected' | 'disconnected' | 'reconnecting';
export interface UseLogStreamOptions {
    wsUrl: string;
    maxEntries?: number;
}
export declare function useLogStream({ wsUrl, maxEntries }: UseLogStreamOptions): {
    logs: LogRecord[];
    connectionState: ConnectionState;
};
