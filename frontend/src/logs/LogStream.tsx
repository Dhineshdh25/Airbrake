/**
 * AI Services Dashboard — tiles for all projects with category filter and detail modal.
 */

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../lib/api';

interface Project {
  id: string;
  name: string;
  category: string;
}

interface LogRow {
  file_name: string | null;
  timestamp: string | null;
  success_count: number;
  failure_count: number;
  error: string | null;
  llm_usage: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  calculated_cost: string | null;
  word_count: number | null;
  file_type: string | null;
  error_group_id?: string | null;
  error_group_name?: string | null;
  isResolved?: boolean; // Added to identify resolved errors
}

interface ProjectStats {
  exists: boolean;
  tableName: string;
  total: number;
  filesProcessed: number;
  success: number;
  failure: number;
  resolved?: number; // Added to track resolved errors
  totalCost: string | null;
  errors: { timestamp: string | null; message: string }[];
  logs: LogRow[];
  pagination?: {
    currentPage: number;
    totalPages: number;
    totalRecords: number;
    limit: number;
    hasNextPage: boolean;
    hasPreviousPage: boolean;
  };
}

interface SemanticGroup {
  error_group_id: string;
  error_group_name: string;
  occurrence_count: number;
}

const CATEGORIES = ['All', 'Gen AI', 'Computer Vision', 'Traditional Model', 'RAG', 'Analytics'];

const CATEGORY_COLOR: Record<string, string> = {
  'Gen AI': '#6366f1',
  'Computer Vision': '#10b981',
  'Traditional Model': '#f59e0b',
  'RAG': '#8b5cf6',
  'Analytics': '#3b82f6',
};

const TILE_PALETTE = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];
function tileColor(i: number) { return TILE_PALETTE[i % TILE_PALETTE.length]; }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts: string | null) {
  if (!ts) return '—';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
}

function fmtDate(ts: string | null) {
  if (!ts) return '';
  return new Date(ts).toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// ─── Sub-components ───────────────────────────────────────────────────────────

type TimePeriod = 'daily' | 'weekly' | 'custom';

function SummaryCard({ label, value, color, icon }: { label: string; value: string | number; color: string; icon: string }) {
  return (
    <div style={{
      flex: '1 1 auto', minWidth: 90,
      background: `linear-gradient(135deg, ${color}18 0%, ${color}08 100%)`,
      border: `1px solid ${color}30`,
      borderRadius: 12, padding: '14px 16px',
      display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      <div style={{ fontSize: 18, lineHeight: 1 }}>{icon}</div>
      <div style={{
        fontSize: 20, fontWeight: 800, color, lineHeight: 1.2,
        wordBreak: 'break-all', overflowWrap: 'anywhere',
      }}>{value}</div>
      <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>{label}</div>
    </div>
  );
}

function SuccessBar({ success, total }: { success: number; total: number }) {
  const pct = total > 0 ? Math.round((success / total) * 100) : 0;
  const color = pct >= 80 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>Success Rate</span>
        <span style={{ fontSize: 12, fontWeight: 700, color }}>{pct}%</span>
      </div>
      <div style={{ height: 6, borderRadius: 99, background: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, borderRadius: 99,
          background: `linear-gradient(90deg, ${color}, ${color}aa)`,
          transition: 'width 0.6s ease',
          boxShadow: `0 0 8px ${color}66`,
        }} />
      </div>
    </div>
  );
}

function StatusBadge({ isError, isResolved }: { isError: boolean; isResolved?: boolean }) {
  const bgColor = isResolved
    ? 'rgba(139,92,246,0.15)'
    : (isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)');
  const textColor = isResolved
    ? '#a78bfa'
    : (isError ? '#f87171' : '#34d399');
  const borderColor = isResolved
    ? 'rgba(139,92,246,0.3)'
    : (isError ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)');
  const label = isResolved ? 'Resolved' : (isError ? 'Failed' : 'Success');

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
      background: bgColor,
      color: textColor,
      border: `1px solid ${borderColor}`,
    }}>
      <span style={{ fontSize: 8 }}>●</span>
      {label}
    </span>
  );
}

function FileCard({ row, onGroupClick }: { row: LogRow; onGroupClick?: (groupId: string, groupName: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const isError = !!row.error;
  const isResolved = row.isResolved ?? false;
  const hasDetails = row.llm_usage || row.input_tokens || row.output_tokens || row.calculated_cost || row.word_count;

  const borderColor = isResolved
    ? 'rgba(139,92,246,0.25)'
    : (isError ? 'rgba(239,68,68,0.25)' : 'rgba(255,255,255,0.07)');
  const bgColor = isResolved
    ? 'rgba(139,92,246,0.04)'
    : (isError ? 'rgba(239,68,68,0.04)' : 'rgba(255,255,255,0.02)');
  const iconBg = isResolved
    ? 'rgba(139,92,246,0.15)'
    : (isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.12)');
  const icon = isResolved ? '✔️' : (isError ? '📄' : '✅');

  return (
    <div style={{
      borderRadius: 10,
      border: `1px solid ${borderColor}`,
      background: bgColor,
      overflow: 'hidden',
      transition: 'border-color 0.15s',
    }}>
      {/* Card row */}
      <div
        onClick={() => hasDetails && setExpanded((v) => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '10px 14px',
          cursor: hasDetails ? 'pointer' : 'default',
        }}
      >
        {/* File icon */}
        <div style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          background: iconBg,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14,
        }}>
          {icon}
        </div>

        {/* File info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 600, color: '#e2e8f0',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {row.file_name ?? 'Unknown file'}
          </div>
          {isError && (
            <div style={{
              fontSize: 11,
              color: isResolved ? '#a78bfa' : '#f87171',
              marginTop: 2,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              textDecoration: isResolved ? 'line-through' : 'none',
            }}>
              {row.error}
            </div>
          )}
        </div>

        {/* Time */}
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'ui-monospace, monospace' }}>{fmtTime(row.timestamp)}</div>
          <div style={{ fontSize: 10, color: '#475569' }}>{fmtDate(row.timestamp)}</div>
        </div>

        {/* Badge */}
        <div style={{ flexShrink: 0 }}>
          <StatusBadge isError={isError} isResolved={isResolved} />
        </div>

        {/* Semantic group tag */}
        {row.error_group_name && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (onGroupClick && row.error_group_id && row.error_group_name) {
                onGroupClick(row.error_group_id, row.error_group_name);
              }
            }}
            style={{
              marginLeft: 8,
              border: 'none',
              background: 'rgba(56,189,248,0.16)',
              color: '#38bdf8',
              borderRadius: 999,
              padding: '4px 10px',
              fontSize: 11,
              cursor: onGroupClick ? 'pointer' : 'default',
              whiteSpace: 'nowrap',
            }}
          >
            {row.error_group_name}
          </button>
        )}

        {/* Expand chevron */}
        {hasDetails && (
          <div style={{ color: '#475569', fontSize: 12, flexShrink: 0, transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none' }}>
            ▾
          </div>
        )}
      </div>

      {/* Expanded details */}
      {expanded && hasDetails && (
        <div style={{
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '12px 14px',
          display: 'flex', flexWrap: 'wrap', gap: 10,
          background: 'rgba(0,0,0,0.15)',
        }}>
          {row.input_tokens != null && <DetailChip label="Input Tokens" value={String(row.input_tokens)} color="#3b82f6" />}
          {row.output_tokens != null && <DetailChip label="Output Tokens" value={String(row.output_tokens)} color="#6366f1" />}
          {row.calculated_cost && <DetailChip label="Cost" value={row.calculated_cost} color="#10b981" />}
          {row.word_count != null && <DetailChip label="Words" value={String(row.word_count)} color="#f59e0b" />}
          {row.file_type && <DetailChip label="Type" value={row.file_type} color="#14b8a6" />}
        </div>
      )}
    </div>
  );
}

function DetailChip({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: `${color}15`, border: `1px solid ${color}30`,
      borderRadius: 8, padding: '5px 10px',
      display: 'flex', flexDirection: 'column', gap: 1,
    }}>
      <span style={{ fontSize: 10, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ fontSize: 12, color, fontWeight: 700 }}>{value}</span>
    </div>
  );
}

function SectionHeader({ title, count, color, collapsed, onToggle }: {
  title: string; count: number; color: string; collapsed: boolean; onToggle: () => void;
}) {
  return (
    <button onClick={onToggle} style={{
      width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: 'transparent', border: 'none', cursor: 'pointer',
      padding: '10px 0', marginBottom: collapsed ? 0 : 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>{title}</span>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
          background: `${color}20`, color,
        }}>{count}</span>
      </div>
      <span style={{ color, fontSize: 28, lineHeight: 1, transition: 'transform 0.2s', transform: collapsed ? 'none' : 'rotate(180deg)', display: 'inline-block' }}>▾</span>
    </button>
  );
}

// ─── Main Modal ───────────────────────────────────────────────────────────────

function ProjectModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [failedStats, setFailedStats] = useState<ProjectStats | null>(null);
  const [resolvedStats, setResolvedStats] = useState<ProjectStats | null>(null);
  const [successStats, setSuccessStats] = useState<ProjectStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [failedPage, setFailedPage] = useState(1);
  const [resolvedPage, setResolvedPage] = useState(1);
  const [successPage, setSuccessPage] = useState(1);
  const [failedCollapsed, setFailedCollapsed] = useState(false);
  const [resolvedCollapsed, setResolvedCollapsed] = useState(true);
  const [successCollapsed, setSuccessCollapsed] = useState(true);
  const [failedSearchTerm, setFailedSearchTerm] = useState('');
  const [failedGroupFilter, setFailedGroupFilter] = useState<string | null>(null);

  // Time period filter states
  const [timePeriod, setTimePeriod] = useState<TimePeriod>('daily');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [customApplyTick, setCustomApplyTick] = useState(0);

  const buildDateParams = () => {
    let dateParams = '';
    if (timePeriod === 'daily') {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const tomorrow = new Date(today);
      tomorrow.setDate(tomorrow.getDate() + 1);
      dateParams = `&from=${today.toISOString()}&to=${tomorrow.toISOString()}`;
    } else if (timePeriod === 'weekly') {
      const weekAgo = new Date();
      weekAgo.setDate(weekAgo.getDate() - 7);
      weekAgo.setHours(0, 0, 0, 0);
      const now = new Date();
      dateParams = `&from=${weekAgo.toISOString()}&to=${now.toISOString()}`;
    } else if (timePeriod === 'custom' && customFrom && customTo && customApplyTick > 0) {
      const fromDate = new Date(customFrom);
      fromDate.setHours(0, 0, 0, 0);
      const toDate = new Date(customTo);
      toDate.setHours(23, 59, 59, 999);
      dateParams = `&from=${fromDate.toISOString()}&to=${toDate.toISOString()}`;
    }
    return dateParams;
  };

  useEffect(() => {
    setLoading(true);
    const dateParams = buildDateParams();
    const apiUrl = `/api/projects/${encodeURIComponent(project.name)}/logs?page=1&limit=1${dateParams}`;

    apiFetch(apiUrl)
      .then((r) => r.json())
      .then((d) => setStats(d as ProjectStats))
      .catch((err) => console.error('[LogStream] Stats error:', err))
      .finally(() => setLoading(false));
  }, [project.name, timePeriod, customApplyTick]);

  const fetchSectionStats = (
    status: string,
    page: number,
    setter: React.Dispatch<React.SetStateAction<ProjectStats | null>>,
    searchTerm = '',
    groupFilter?: string | null,
  ) => {
    setLoading(true);
    const dateParams = buildDateParams();
    let apiUrl = `/api/projects/${encodeURIComponent(project.name)}/logs?status=${status}&page=${page}&limit=5${dateParams}`;
    if (searchTerm) apiUrl += `&search=${encodeURIComponent(searchTerm)}`;
    if (groupFilter) apiUrl += `&group=${encodeURIComponent(groupFilter)}`;

    apiFetch(apiUrl)
      .then((r) => r.json())
      .then((d) => setter(d as ProjectStats))
      .catch((err) => console.error(`[LogStream] ${status} section error:`, err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setFailedPage(1);
    setResolvedPage(1);
    setSuccessPage(1);
  }, [project.name, timePeriod, customApplyTick, failedSearchTerm]);

  const paginationButtonStyle = (enabled: boolean) => ({
    padding: '6px 12px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    cursor: enabled ? 'pointer' : 'not-allowed',
    background: enabled ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.05)',
    border: `1px solid ${enabled ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.1)'}`,
    color: enabled ? '#818cf8' : '#475569',
  });

  useEffect(() => {
    fetchSectionStats('active', failedPage, setFailedStats, failedSearchTerm);
  }, [project.name, timePeriod, customApplyTick, failedPage, failedSearchTerm]);

  useEffect(() => {
    // refetch failed section when group filter changes
    fetchSectionStats('active', failedPage, setFailedStats, failedSearchTerm, failedGroupFilter ?? undefined);
  }, [failedGroupFilter]);

  useEffect(() => {
    fetchSectionStats('resolved', resolvedPage, setResolvedStats);
  }, [project.name, timePeriod, customApplyTick, resolvedPage]);

  useEffect(() => {
    fetchSectionStats('success', successPage, setSuccessStats);
  }, [project.name, timePeriod, customApplyTick, successPage]);

  const failedLogs = failedStats?.logs ?? [];
  const resolvedLogs = resolvedStats?.logs ?? [];
  const successLogs = successStats?.logs ?? [];

  // Count totals
  const totalFailedLogs = failedLogs.length;
  const totalResolvedLogs = resolvedLogs.length;
  const totalSuccessLogs = successLogs.length;

  const hasFailureTotals = totalFailedLogs > 0;
  const hasResolvedTotals = totalResolvedLogs > 0;
  const hasSuccessTotals = totalSuccessLogs > 0;

  // Aggregate token/cost totals if available
  const totalInputTokens = stats?.logs?.reduce((s, r) => s + (r.input_tokens ?? 0), 0) ?? 0;
  const totalOutputTokens = stats?.logs?.reduce((s, r) => s + (r.output_tokens ?? 0), 0) ?? 0;
  const hasTokenData = totalInputTokens > 0 || totalOutputTokens > 0;

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0,
      background: 'rgba(0,0,0,0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000, padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: '#0f172a',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 16,
        width: '95%', maxWidth: 720,
        maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 25px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04)',
      }}>

        {/* ── Header ── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '18px 22px',
          borderBottom: '1px solid rgba(255,255,255,0.07)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16, boxShadow: '0 0 16px rgba(99,102,241,0.4)',
            }}>
              🤖
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>{project.name}</div>
              <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
                {stats?.exists ? `${stats.total} total files` : 'Loading…'}
              </div>
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
            color: '#94a3b8', fontSize: 16, cursor: 'pointer',
            width: 32, height: 32, borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>✕</button>
        </div>

        {/* ── Body ── */}
        <div style={{ overflow: 'auto', padding: '20px 22px', flex: 1 }}>

          {/* ── Time Period Filter ── */}
          <div style={{
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 10,
            padding: '12px 14px',
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: 10,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Time Period:
              </span>
              <div style={{
                display: 'flex', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 8, padding: 3, gap: 2,
              }}>
                {(['daily', 'weekly', 'custom'] as TimePeriod[]).map((period) => (
                  <button
                    key={period}
                    onClick={() => {
                      setTimePeriod(period);
                      setFailedPage(1);
                      setResolvedPage(1);
                      setSuccessPage(1);
                    }}
                    style={{
                      padding: '5px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                      border: 'none', cursor: 'pointer', textTransform: 'capitalize',
                      background: timePeriod === period ? '#6366f1' : 'transparent',
                      color: timePeriod === period ? '#fff' : '#94a3b8',
                      transition: 'background 0.15s, color 0.15s',
                    }}
                  >
                    {period}
                  </button>
                ))}
              </div>

              {timePeriod === 'custom' && (
                <>
                  <input
                    type="date"
                    value={customFrom}
                    onChange={(e) => setCustomFrom(e.target.value)}
                    style={{
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6, color: '#e2e8f0',
                      padding: '5px 8px', fontSize: 11, outline: 'none',
                      cursor: 'pointer', colorScheme: 'dark',
                    } as React.CSSProperties}
                  />
                  <span style={{ fontSize: 11, color: '#64748b' }}>to</span>
                  <input
                    type="date"
                    value={customTo}
                    onChange={(e) => setCustomTo(e.target.value)}
                    style={{
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6, color: '#e2e8f0',
                      padding: '5px 8px', fontSize: 11, outline: 'none',
                      cursor: 'pointer', colorScheme: 'dark',
                    } as React.CSSProperties}
                  />
                  <button
                    onClick={() => {
                      setCustomApplyTick((t) => t + 1);
                      setFailedPage(1);
                      setResolvedPage(1);
                      setSuccessPage(1);
                    }}
                    disabled={!customFrom || !customTo}
                    style={{
                      padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
                      cursor: (!customFrom || !customTo) ? 'not-allowed' : 'pointer',
                      background: '#6366f1', color: '#fff', border: 'none',
                      opacity: (!customFrom || !customTo) ? 0.5 : 1,
                    }}
                  >
                    Apply
                  </button>
                </>
              )}
            </div>

            <span style={{ fontSize: 10, color: '#64748b', fontStyle: 'italic' }}>
              {timePeriod === 'daily' && 'Today\'s data'}
              {timePeriod === 'weekly' && 'Last 7 days'}
              {timePeriod === 'custom' && customFrom && customTo && `${new Date(customFrom).toLocaleDateString()} - ${new Date(customTo).toLocaleDateString()}`}
              {timePeriod === 'custom' && (!customFrom || !customTo) && 'Select date range'}
            </span>
          </div>

          {loading && (
            <div style={{ textAlign: 'center', color: '#475569', padding: '60px 0', fontSize: 14 }}>
              <div style={{ fontSize: 28, marginBottom: 12 }}>⏳</div>
              Loading logs…
            </div>
          )}

          {!loading && stats && !stats.exists && (
            <div style={{ textAlign: 'center', color: '#475569', padding: '60px 0', fontSize: 14 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>📭</div>
              No data table found for this project yet.
            </div>
          )}

          {!loading && stats && stats.exists && (
            <>
              {/* ── Summary cards ── */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'stretch' }}>
                <SummaryCard label="Files Processed" value={stats.filesProcessed} color="#3b82f6" icon="📁" />
                <SummaryCard label="Total Success" value={stats.success} color="#10b981" icon="✅" />
                <SummaryCard label="Total Failures" value={stats.failure} color="#ef4444" icon="❌" />
                {(stats.resolved ?? 0) > 0 && (
                  <SummaryCard label="Resolved Errors" value={stats.resolved ?? 0} color="#8b5cf6" icon="✔️" />
                )}
                {hasTokenData && (
                  <SummaryCard label="Input Tokens" value={totalInputTokens.toLocaleString()} color="#8b5cf6" icon="🔢" />
                )}
                {hasTokenData && (
                  <SummaryCard label="Output Tokens" value={totalOutputTokens.toLocaleString()} color="#6366f1" icon="📤" />
                )}
                {stats.totalCost && (
                  <SummaryCard label="Total Cost" value={stats.totalCost} color="#f59e0b" icon="💰" />
                )}
              </div>

              {/* ── Success rate bar ── */}
              <SuccessBar success={stats.success} total={stats.filesProcessed} />

              {/* ── Failed files ── */}
              {failedStats && (
                <div style={{ marginBottom: 16 }}>
                      <SectionHeader
                        title="Failed Files"
                        count={failedStats?.pagination?.totalRecords ?? 0}
                        color="#f87171"
                        collapsed={failedCollapsed}
                        onToggle={() => setFailedCollapsed((v) => !v)}
                      />
                  {!failedCollapsed && (
                    <>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
                        <input
                          value={failedSearchTerm}
                          onChange={(e) => setFailedSearchTerm(e.target.value)}
                          placeholder="Search failed files or errors"
                          style={{
                            flex: '1 1 240px', minWidth: 180,
                            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: 8, color: '#e2e8f0', padding: '8px 10px', fontSize: 12,
                          }}
                        />
                        {failedSearchTerm && (
                          <button
                            onClick={() => setFailedSearchTerm('')}
                            style={{
                              background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)',
                              borderRadius: 8, color: '#e2e8f0', padding: '8px 12px', fontSize: 12,
                              cursor: 'pointer', height: 40,
                            }}
                          >
                            Clear
                          </button>
                        )}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {failedLogs.map((row, i) => (
                        <FileCard
                          key={i}
                          row={row}
                          onGroupClick={(groupId) => {
                            setFailedSearchTerm('');
                            setFailedGroupFilter(groupId);
                            setFailedPage(1);
                            setFailedCollapsed(false);
                          }}
                        />
                      ))}
                      </div>
                      {failedStats?.pagination && (failedStats.pagination.totalPages ?? 0) > 1 && (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.07)' }}>
                          <div style={{ fontSize: 12, color: '#94a3b8' }}>
                            Page {failedStats?.pagination?.currentPage ?? 1} of {failedStats?.pagination?.totalPages ?? 1}
                            <span style={{ marginLeft: 8, color: '#64748b' }}>(showing {failedLogs.length})</span>
                          </div>
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button onClick={() => setFailedPage(1)} disabled={!failedStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!failedStats?.pagination?.hasPreviousPage)}>First</button>
                            <button onClick={() => setFailedPage((failedStats?.pagination?.currentPage ?? 1) - 1)} disabled={!failedStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!failedStats?.pagination?.hasPreviousPage)}>← Previous</button>
                            <button onClick={() => setFailedPage((failedStats?.pagination?.currentPage ?? 1) + 1)} disabled={!failedStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!failedStats?.pagination?.hasNextPage)}>Next →</button>
                            <button onClick={() => setFailedPage(failedStats?.pagination?.totalPages ?? 1)} disabled={!failedStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!failedStats?.pagination?.hasNextPage)}>Last</button>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ── Resolved files ── */}
              {resolvedStats && (
                <div style={{ marginBottom: 16 }}>
                  <SectionHeader
                    title="Resolved Files"
                    count={resolvedStats?.pagination?.totalRecords ?? 0}
                    color="#8b5cf6"
                    collapsed={resolvedCollapsed}
                    onToggle={() => setResolvedCollapsed((v) => !v)}
                  />
                  {!resolvedCollapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {resolvedLogs.map((row, i) => <FileCard key={i} row={row} />)}
                    </div>
                  )}
                  {resolvedStats?.pagination && (resolvedStats.pagination.totalPages ?? 0) > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.07)' }}>
                      <div style={{ fontSize: 12, color: '#94a3b8' }}>
                        Page {resolvedStats?.pagination?.currentPage ?? 1} of {resolvedStats?.pagination?.totalPages ?? 1}
                        <span style={{ marginLeft: 8, color: '#64748b' }}>(showing {resolvedLogs.length})</span>
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={() => setResolvedPage(1)} disabled={!resolvedStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!resolvedStats?.pagination?.hasPreviousPage)}>First</button>
                        <button onClick={() => setResolvedPage((resolvedStats?.pagination?.currentPage ?? 1) - 1)} disabled={!resolvedStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!resolvedStats?.pagination?.hasPreviousPage)}>← Previous</button>
                        <button onClick={() => setResolvedPage((resolvedStats?.pagination?.currentPage ?? 1) + 1)} disabled={!resolvedStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!resolvedStats?.pagination?.hasNextPage)}>Next →</button>
                        <button onClick={() => setResolvedPage(resolvedStats?.pagination?.totalPages ?? 1)} disabled={!resolvedStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!resolvedStats?.pagination?.hasNextPage)}>Last</button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ── Successful files ── */}
              {successStats && (
                <div style={{ marginBottom: 8 }}>
                  <SectionHeader
                    title="Successful Files"
                    count={successStats?.pagination?.totalRecords ?? 0}
                    color="#34d399"
                    collapsed={successCollapsed}
                    onToggle={() => setSuccessCollapsed((v) => !v)}
                  />
                  {!successCollapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {successLogs.map((row, i) => <FileCard key={i} row={row} />)}
                    </div>
                  )}
                  {successStats?.pagination && (successStats.pagination.totalPages ?? 0) > 1 && !successCollapsed && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.07)' }}>
                      <div style={{ fontSize: 12, color: '#94a3b8' }}>
                        Page {successStats?.pagination?.currentPage ?? 1} of {successStats?.pagination?.totalPages ?? 1}
                        <span style={{ marginLeft: 8, color: '#64748b' }}>(showing {successLogs.length})</span>
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={() => setSuccessPage(1)} disabled={!successStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!successStats?.pagination?.hasPreviousPage)}>First</button>
                        <button onClick={() => setSuccessPage((successStats?.pagination?.currentPage ?? 1) - 1)} disabled={!successStats?.pagination?.hasPreviousPage} style={paginationButtonStyle(!!successStats?.pagination?.hasPreviousPage)}>← Previous</button>
                        <button onClick={() => setSuccessPage((successStats?.pagination?.currentPage ?? 1) + 1)} disabled={!successStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!successStats?.pagination?.hasNextPage)}>Next →</button>
                        <button onClick={() => setSuccessPage(successStats?.pagination?.totalPages ?? 1)} disabled={!successStats?.pagination?.hasNextPage} style={paginationButtonStyle(!!successStats?.pagination?.hasNextPage)}>Last</button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ── No logs ── */}
              {stats.logs?.length === 0 && (
                <div style={{ textAlign: 'center', color: '#475569', padding: '30px 0', fontSize: 13 }}>
                  No file logs recorded yet.
                </div>
              )}

            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Tile ─────────────────────────────────────────────────────────────────────

function ProjectTile({ project, index, onClick }: { project: Project; index: number; onClick: () => void }) {
  const tc = tileColor(index);
  const cc = CATEGORY_COLOR[project.category] ?? '#64748b';
  const initials = project.name.split(' ').slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('');

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--surface)', border: '1px solid var(--card-border)',
        borderTop: `3px solid ${tc}`, borderRadius: 'var(--radius-md)',
        padding: '18px 16px', display: 'flex', flexDirection: 'column', gap: 10,
        cursor: 'pointer', transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 16px rgba(0,0,0,0.18)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = 'none'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8, background: tc, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700, color: '#fff',
        }}>
          {initials}
        </div>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3, wordBreak: 'break-word' }}>
          {project.name}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, color: '#fff', background: cc, padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
          {project.category}
        </span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: tc, boxShadow: `0 0 6px ${tc}` }} />
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function LogStream() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [projectFilter, setProjectFilter] = useState(''); // New: project name filter

  useEffect(() => {
    setLoading(true);
    const params = activeCategory !== 'All' ? `?category=${encodeURIComponent(activeCategory)}` : '';
    apiFetch(`/api/projects${params}`)
      .then((r) => r.json())
      .then((data) => {
        setProjects(data as Project[]);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [activeCategory]);

  // Apply both search and project filter
  const filtered = projects.filter((p) => {
    const matchesSearch = p.name.toLowerCase().includes(search.toLowerCase());
    const matchesProjectFilter = !projectFilter || p.name === projectFilter;
    return matchesSearch && matchesProjectFilter;
  });

  // Get unique project names for the filter dropdown
  const projectNames = Array.from(new Set(projects.map((p) => p.name))).sort();

  return (
    <div data-testid="log-stream">
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>AI Services</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>All projects at a glance — click a tile to view data</p>
      </div>

      {/* Category filter tabs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        {CATEGORIES.map((cat) => {
          const active = activeCategory === cat;
          const color = CATEGORY_COLOR[cat] ?? '#6366f1';
          return (
            <button key={cat} onClick={() => { setActiveCategory(cat); setSearch(''); }}
              style={{
                padding: '6px 14px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                border: active ? `2px solid ${color}` : '1px solid var(--card-border)',
                background: active ? color : 'var(--surface)',
                color: active ? '#fff' : 'var(--text-muted)',
                fontWeight: active ? 700 : 400, transition: 'all 0.15s',
              }}
            >
              {cat}
            </button>
          );
        })}
      </div>

      {/* Search and Filter */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <input
          placeholder="Search projects…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: 'var(--input-bg)', border: '1px solid var(--input-border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text)',
            padding: '8px 14px', fontSize: 13, outline: 'none', flex: '1 1 auto', minWidth: 200,
          }}
        />
        <select
          value={projectFilter}
          onChange={(e) => {
            setProjectFilter(e.target.value);
            setSearch(''); // Clear search when using dropdown
          }}
          style={{
            background: 'var(--input-bg)', border: '1px solid var(--input-border)',
            borderRadius: 6, color: 'var(--text)',
            padding: '8px 12px', fontSize: 13, outline: 'none',
            cursor: 'pointer', minWidth: 200,
          }}
        >
          <option value="">All Projects</option>
          {projectNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          {filtered.length} project{filtered.length !== 1 ? 's' : ''} shown
        </span>
      </div>

      {/* Tiles */}
      {loading ? (
        <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
          Loading projects…
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14 }}>
          {filtered.map((project, i) => (
            <ProjectTile key={project.id} project={project} index={i} onClick={() => setSelectedProject(project)} />
          ))}
          {filtered.length === 0 && (
            <div style={{ gridColumn: '1/-1', padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
              No projects match
            </div>
          )}
        </div>
      )}

      {/* Modal */}
      {selectedProject && (
        <ProjectModal project={selectedProject} onClose={() => setSelectedProject(null)} />
      )}
    </div>
  );
}
