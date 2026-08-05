/**
 * Log stream filter state hook.
 * Requirements: 1.4, 1.5, 1.6
 */
import type { LogRecord } from '@portal/shared';
export interface LogFilters {
    application: string;
    environment: string;
    severity: string;
    keyword: string;
    from: string;
    to: string;
}
export declare function useLogFilters(logs: LogRecord[]): {
    filters: LogFilters;
    updateFilter: (key: keyof LogFilters, value: string) => void;
    resetFilters: () => void;
    filtered: LogRecord[];
};
