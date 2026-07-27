/**
 * AI Services Dashboard — tiles for all projects with category filter and detail modal.
 */

import { useEffect, useState } from 'react';
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
}

interface ProjectStats {
  exists: boolean;
  tableName: string;
  total: number;
  filesProcessed: number;
  success: number;
  failure: number;
  totalCost: string | null;
  errors: { timestamp: string | null; message: string }[];
  logs: LogRow[];
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

function StatusBadge({ isError }: { isError: boolean }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
      background: isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
      color: isError ? '#f87171' : '#34d399',
      border: `1px solid ${isError ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`,
    }}>
      <span style={{ fontSize: 8 }}>●</span>
      {isError ? 'Failed' : 'Success'}
    </span>
  );
}

function FileCard({ row }: { row: LogRow }) {
  const [expanded, setExpanded] = useState(false);
  const isError = !!row.error;
  const hasDetails = row.llm_usage || row.input_tokens || row.output_tokens || row.calculated_cost || row.word_count;

  return (
    <div style={{
      borderRadius: 10,
      border: `1px solid ${isError ? 'rgba(239,68,68,0.25)' : 'rgba(255,255,255,0.07)'}`,
      background: isError ? 'rgba(239,68,68,0.04)' : 'rgba(255,255,255,0.02)',
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
          background: isError ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.12)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14,
        }}>
          {isError ? '📄' : '✅'}
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
            <div style={{ fontSize: 11, color: '#f87171', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
          <StatusBadge isError={isError} />
        </div>

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
  const [loading, setLoading] = useState(true);
  const [failedCollapsed, setFailedCollapsed] = useState(false);
  const [successCollapsed, setSuccessCollapsed] = useState(true);

  useEffect(() => {
    apiFetch(`/api/projects/${encodeURIComponent(project.name)}/logs`)
      .then((r) => r.json())
      .then((d) => { setStats(d as ProjectStats); setLoading(false); })
      .catch(() => setLoading(false));
  }, [project.name]);

  const failedLogs = (stats?.logs?.filter((r) => !!r.error) ?? []).slice(0, 50);
  const successLogs = (stats?.logs?.filter((r) => !r.error) ?? []).slice(0, 50);

  // Count totals before slicing
  const totalFailedLogs = stats?.logs?.filter((r) => !!r.error).length ?? 0;
  const totalSuccessLogs = stats?.logs?.filter((r) => !r.error).length ?? 0;

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
                {stats?.exists ? `${stats.total} total records` : 'Loading…'}
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
              {totalFailedLogs > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <SectionHeader
                    title={totalFailedLogs > 50 ? `Failed Files (showing 50 of ${totalFailedLogs})` : "Failed Files"}
                    count={totalFailedLogs}
                    color="#f87171"
                    collapsed={failedCollapsed}
                    onToggle={() => setFailedCollapsed((v) => !v)}
                  />
                  {!failedCollapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {failedLogs.map((row, i) => <FileCard key={i} row={row} />)}
                    </div>
                  )}
                </div>
              )}

              {/* ── Successful files ── */}
              {totalSuccessLogs > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <SectionHeader
                    title={totalSuccessLogs > 50 ? `Successful Files (showing 50 of ${totalSuccessLogs})` : "Successful Files"}
                    count={totalSuccessLogs}
                    color="#34d399"
                    collapsed={successCollapsed}
                    onToggle={() => setSuccessCollapsed((v) => !v)}
                  />
                  {!successCollapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {successLogs.map((row, i) => <FileCard key={i} row={row} />)}
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

  const filtered = projects.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()));

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

      {/* Search */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <input
          placeholder="Search projects…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: 'var(--input-bg)', border: '1px solid var(--input-border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text)',
            padding: '8px 14px', fontSize: 13, outline: 'none', width: 260,
          }}
        />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
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
