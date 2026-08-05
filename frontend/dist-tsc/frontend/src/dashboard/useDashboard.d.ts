/**
 * Dashboard data hook — fetches all dashboard aggregation data from the REST API.
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */
export interface BreakCountData {
    last24h: number;
    last7d: number;
}
export interface TrendPoint {
    timestamp: string;
    count: number;
}
export interface ServiceBreakCount {
    service: string;
    count: number;
}
export interface SeverityCount {
    severity: string;
    count: number;
}
export interface DeploymentEvent {
    timestamp: string;
    version: string;
    service: string;
}
export interface DashboardData {
    breakCounts: BreakCountData;
    errorRateTrend: TrendPoint[];
    topServices: ServiceBreakCount[];
    timeSeries: TrendPoint[];
    severityBreakdown: SeverityCount[];
    deploymentEvents: DeploymentEvent[];
    airbrakeUnreachable: boolean;
}
export declare function useDashboard(apiBase?: string): {
    data: DashboardData;
    loading: boolean;
    error: string | null;
};
