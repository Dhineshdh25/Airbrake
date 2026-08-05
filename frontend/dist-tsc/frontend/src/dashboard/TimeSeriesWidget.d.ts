import type { DeploymentEvent, TrendPoint } from './useDashboard';
interface Props {
    timeSeries: TrendPoint[];
    deploymentEvents: DeploymentEvent[];
}
export declare function TimeSeriesWidget({ timeSeries, deploymentEvents }: Props): import("react/jsx-runtime").JSX.Element;
export {};
