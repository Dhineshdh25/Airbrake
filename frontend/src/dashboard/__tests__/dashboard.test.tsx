/**
 * Unit tests for dashboard widget rendering.
 * Requirements: 3.1, 3.2, 3.3
 */

import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { BreakCountWidget } from '../BreakCountWidget';
import { ErrorRateTrendWidget } from '../ErrorRateTrendWidget';
import { SeverityBreakdownWidget } from '../SeverityBreakdownWidget';
import { TimeSeriesWidget } from '../TimeSeriesWidget';
import { TopServicesWidget } from '../TopServicesWidget';
import { summarizeSemanticGroupsForToday, normalizeSemanticGroupName } from '../Dashboard';

describe('BreakCountWidget', () => {
  it('renders 24h and 7d counts', () => {
    render(<BreakCountWidget data={{ last24h: 42, last7d: 300 }} />);
    expect(screen.getByTestId('break-count-24h')).toHaveTextContent('42');
    expect(screen.getByTestId('break-count-7d')).toHaveTextContent('300');
  });

  it('renders zero counts', () => {
    render(<BreakCountWidget data={{ last24h: 0, last7d: 0 }} />);
    expect(screen.getByTestId('break-count-24h')).toHaveTextContent('0');
    expect(screen.getByTestId('break-count-7d')).toHaveTextContent('0');
  });
});

describe('ErrorRateTrendWidget', () => {
  it('renders trend points', () => {
    const trend = [
      { timestamp: '2026-03-17T00:00:00Z', count: 5 },
      { timestamp: '2026-03-17T01:00:00Z', count: 10 },
    ];
    render(<ErrorRateTrendWidget trend={trend} />);
    expect(screen.getAllByTestId('trend-point')).toHaveLength(2);
  });

  it('shows empty state when no data', () => {
    render(<ErrorRateTrendWidget trend={[]} />);
    expect(screen.getByTestId('trend-empty')).toBeInTheDocument();
  });
});

describe('TopServicesWidget', () => {
  it('renders services in order', () => {
    const services = [
      { service: 'api', count: 100 },
      { service: 'worker', count: 50 },
    ];
    render(<TopServicesWidget services={services} />);
    const rows = screen.getAllByTestId('service-row');
    expect(rows[0]).toHaveTextContent('api');
    expect(rows[1]).toHaveTextContent('worker');
  });

  it('shows empty state when no services', () => {
    render(<TopServicesWidget services={[]} />);
    expect(screen.getByTestId('services-empty')).toBeInTheDocument();
  });
});

describe('TimeSeriesWidget', () => {
  it('renders time series points', () => {
    const ts = [{ timestamp: '2026-03-17T00:00:00Z', count: 3 }];
    render(<TimeSeriesWidget timeSeries={ts} deploymentEvents={[]} />);
    expect(screen.getAllByTestId('ts-point')).toHaveLength(1);
  });

  it('renders deployment overlays when present', () => {
    const events = [{ timestamp: '2026-03-17T12:00:00Z', version: 'v1.2.3', service: 'api' }];
    render(<TimeSeriesWidget timeSeries={[]} deploymentEvents={events} />);
    expect(screen.getByTestId('deployment-overlays')).toBeInTheDocument();
    expect(screen.getByTestId('deployment-event')).toHaveTextContent('v1.2.3');
  });

  it('does not render deployment section when empty', () => {
    render(<TimeSeriesWidget timeSeries={[]} deploymentEvents={[]} />);
    expect(screen.queryByTestId('deployment-overlays')).not.toBeInTheDocument();
  });
});

describe('SeverityBreakdownWidget', () => {
  it('renders severity rows', () => {
    const breakdown = [
      { severity: 'critical', count: 5 },
      { severity: 'error', count: 20 },
    ];
    render(<SeverityBreakdownWidget breakdown={breakdown} />);
    expect(screen.getAllByTestId('severity-row')).toHaveLength(2);
  });

  it('shows empty state when no data', () => {
    render(<SeverityBreakdownWidget breakdown={[]} />);
    expect(screen.getByTestId('severity-empty')).toBeInTheDocument();
  });
});

describe('summarizeSemanticGroupsForToday', () => {
  it('prefers semantic group names and falls back for JSON-format errors', () => {
    const rows = [
      { error: 'LLM output was not valid JSON', error_group_name: 'JSON format error' },
      { error: 'LLM output was not valid JSON' },
      { error: 'File not found: uploads/missing.txt' },
    ];

    expect(normalizeSemanticGroupName(rows[1])).toBe('JSON format error');
    expect(summarizeSemanticGroupsForToday(rows)).toEqual([
      { name: 'JSON format error', value: 2 },
      { name: 'File not found', value: 1 },
    ]);
  });
});
