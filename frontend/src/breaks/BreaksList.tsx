import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { PaginationControls } from '../components/PaginationControls';

// ── Types ─────────────────────────────────────────────────────────────────────

interface BreakRow {
  project_name: string;
  error_message: string;
  error_hash: string;
  error_group_id: string;
  error_group_name: string | null;
  representative_id: string | null;
  occurrence_count: number;
  first_seen: string | null;
  last_seen: string | null;
  status: 'new' | 'existing' | 'regression' | 'resolved';
}

interface BreaksPage {
  data: BreakRow[];
  total: number;
  page: number;
  limit: number;
}

interface SemanticGroup {
  error_group_id: string;
  error_group_name: string | null;
  occurrence_count: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const LIMIT = 20;

// ── Shared styles ─────────────────────────────────────────────────────────────

const selectStyle: React.CSSProperties = {
  background: 'var(--input-bg)',
  border: '1px solid var(--input-border)',
  borderRadius: 6,
  color: 'var(--text)',
  padding: '7px 28px 7px 11px',
  fontSize: 13,
  outline: 'none',
  cursor: 'pointer',
  appearance: 'none',
  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' fill='none'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2364748b' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 10px center',
};

const inputStyle: React.CSSProperties = {
  background: 'var(--input-bg)',
  border: '1px solid var(--input-border)',
  borderRadius: 6,
  color: 'var(--text)',
  padding: '7px 11px',
  fontSize: 13,
  outline: 'none',
};

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: 'new' | 'existing' | 'regression' | 'resolved' }) {
  const styles: Record<string, { bg: string; color: string; border: string; label: string }> = {
    new:        { bg: 'rgba(99,102,241,0.15)',  color: '#818cf8', border: 'rgba(99,102,241,0.3)',  label: '● New' },
    existing:   { bg: 'rgba(245,158,11,0.15)',  color: '#fbbf24', border: 'rgba(245,158,11,0.3)',  label: '◎ Existing' },
    regression: { bg: 'rgba(239,68,68,0.15)',   color: '#f87171', border: 'rgba(239,68,68,0.3)',   label: '⚠ Regression' },
    resolved:   { bg: 'rgba(52,211,153,0.15)',  color: '#34d399', border: 'rgba(52,211,153,0.3)',  label: '✓ Resolved' },
  };
  const s = styles[status] ?? styles.new;
  return (
    <span style={{
      padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, flexShrink: 0,
    }}>{s.label}</span>
  );
}

function GroupBadge({ name, active, onClick }: { name: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={name}
      style={{
        padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 600,
        background: active ? 'rgba(56,189,248,0.18)' : 'rgba(56,189,248,0.07)',
        color: active ? '#38bdf8' : 'var(--text-muted)',
        border: `1px solid ${active ? 'rgba(56,189,248,0.5)' : 'rgba(56,189,248,0.2)'}`,
        cursor: 'pointer', whiteSpace: 'nowrap', maxWidth: 180,
        overflow: 'hidden', textOverflow: 'ellipsis',
        transition: 'all 0.15s',
      }}
    >
      {active ? '✕ ' : ''}{name}
    </button>
  );
}

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

// ── Main component ────────────────────────────────────────────────────────────

export function BreaksList() {
  const navigate = useNavigate();
  const location = useLocation();

  // ── Filter state ─────────────────────────────────────────────────────────
  const [page, setPage]               = useState(1);
  const [statusFilter, setStatusFilter]   = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [groupFilter, setGroupFilter]     = useState('');   // error_group_id
  const [fromDate, setFromDate]       = useState('');
  const [toDate, setToDate]           = useState('');
  const [appliedFrom, setAppliedFrom] = useState('');
  const [appliedTo, setAppliedTo]     = useState('');

  // ── Remote data ───────────────────────────────────────────────────────────
  const [result, setResult]       = useState<BreaksPage | null>(null);
  const [loading, setLoading]     = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  // ── Semantic groups ───────────────────────────────────────────────────────
  const [semanticGroups, setSemanticGroups]         = useState<SemanticGroup[]>([]);
  const [groupsLoading, setGroupsLoading]           = useState(false);
  const [showGroupPanel, setShowGroupPanel]         = useState(false);

  // ── Projects list (for filter dropdown) ──────────────────────────────────
  const [projects, setProjects] = useState<string[]>([]);

  // ── Fetch project list ────────────────────────────────────────────────────
  useEffect(() => {
    apiFetch('/api/projects')
      .then(r => r.json())
      .then((rows: { name: string }[]) => setProjects(rows.map(r => r.name).sort()))
      .catch(e => console.error('[Breaks] failed to load project list:', e));
  }, []);

  // ── Fetch semantic groups ─────────────────────────────────────────────────
  useEffect(() => {
    if (!showGroupPanel) return;
    setGroupsLoading(true);
    const qs = projectFilter ? `?project_name=${encodeURIComponent(projectFilter)}` : '';
    apiFetch(`/api/error-groups${qs}`)
      .then(r => r.json())
      .then(d => setSemanticGroups((d.groups ?? []) as SemanticGroup[]))
      .catch(e => console.error('[Breaks] failed to load semantic groups:', e))
      .finally(() => setGroupsLoading(false));
  }, [showGroupPanel, projectFilter]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const projectFromUrl = params.get('project') ?? '';
    const groupFromUrl = params.get('semantic_group') ?? '';
    if (projectFromUrl) setProjectFilter(projectFromUrl);
    if (groupFromUrl) setGroupFilter(groupFromUrl);
  }, [location.search]);

  // ── Fetch breaks ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    const params = new URLSearchParams({
      page:  String(page),
      limit: String(LIMIT),
      ...(statusFilter  ? { status:         statusFilter  } : {}),
      ...(projectFilter ? { project:         projectFilter } : {}),
      ...(groupFilter   ? { semantic_group:  groupFilter   } : {}),
      ...(appliedFrom   ? { from:            appliedFrom   } : {}),
      ...(appliedTo     ? { to:              appliedTo     } : {}),
    });
    apiFetch(`/api/breaks/grouped?${params}`)
      .then(r => r.json())
      .then(d => {
        if (!cancelled) {
          if (d.error && !d.data) setLoadError(`Failed to load grouped breaks: ${d.error}`);
          else setResult(d as BreaksPage);
          setLoading(false);
        }
      })
      .catch(e => {
        if (!cancelled) {
          console.error('[Breaks] grouped fetch failed:', e);
          setLoadError('Unable to load grouped breaks. Please try again.');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [page, statusFilter, projectFilter, groupFilter, appliedFrom, appliedTo, retryTick]);

  const totalPages = result ? Math.ceil(result.total / LIMIT) : 1;

  function applyDateFilter() {
    setAppliedFrom(fromDate ? `${fromDate}T00:00:00Z` : '');
    setAppliedTo(toDate     ? `${toDate}T23:59:59Z`   : '');
    setPage(1);
  }
  function clearDateFilter() {
    setFromDate(''); setToDate('');
    setAppliedFrom(''); setAppliedTo('');
    setPage(1);
  }

  // Active group label for display
  const activeGroup = semanticGroups.find(g => g.error_group_id === groupFilter);
  const activeGroupLabel = activeGroup?.error_group_name || groupFilter;

  return (
    <div data-testid="breaks-list">

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>Breaks</h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Grouped error occurrences across all projects — New vs Existing
        </p>
      </div>

      {/* ── Main filters ───────────────────────────────────────────────────── */}
      <div data-testid="breaks-filters" style={{
        display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap',
        padding: '12px 14px',
        background: 'var(--surface)', border: '1px solid var(--card-border)', borderRadius: 8,
        alignItems: 'center',
      }}>
        <select value={projectFilter}
          onChange={e => { setProjectFilter(e.target.value); setPage(1); }}
          aria-label="Project" style={selectStyle}>
          <option value="">All Projects</option>
          {projects.map(p => <option key={p} value={p}>{p}</option>)}
        </select>

        <select data-testid="filter-status" value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
          aria-label="Status" style={selectStyle}>
          <option value="">All Statuses</option>
          <option value="new">New</option>
          <option value="existing">Existing</option>
          <option value="regression">Regression</option>
          <option value="resolved">Resolved</option>
        </select>

        {/* Semantic group toggle */}
        <button
          onClick={() => setShowGroupPanel(p => !p)}
          title="Filter by AI semantic error group"
          style={{
            padding: '7px 12px', borderRadius: 6, fontSize: 13, fontWeight: 600,
            background: (showGroupPanel || groupFilter) ? 'rgba(56,189,248,0.15)' : 'var(--input-bg)',
            color: (showGroupPanel || groupFilter) ? '#38bdf8' : 'var(--text-muted)',
            border: `1px solid ${(showGroupPanel || groupFilter) ? 'rgba(56,189,248,0.4)' : 'var(--input-border)'}`,
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          🧠 {groupFilter ? `Group: ${activeGroupLabel.slice(0, 22)}${activeGroupLabel.length > 22 ? '…' : ''}` : 'Semantic Group'}
          {groupFilter && (
            <span
              onClick={e => { e.stopPropagation(); setGroupFilter(''); setPage(1); }}
              style={{ marginLeft: 4, opacity: 0.7, fontWeight: 700 }}
            >✕</span>
          )}
        </button>

        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>From:</span>
        <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} style={inputStyle} />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>To:</span>
        <input type="date" value={toDate} onChange={e => setToDate(e.target.value)} style={inputStyle} />

        <button onClick={applyDateFilter} style={{
          padding: '7px 16px', borderRadius: 6, fontSize: 13, fontWeight: 600,
          background: '#6366f1', color: '#fff', border: 'none', cursor: 'pointer',
        }}>Apply</button>

        {(appliedFrom || appliedTo) && (
          <button onClick={clearDateFilter} style={{
            padding: '7px 12px', borderRadius: 6, fontSize: 13,
            background: 'transparent', color: 'var(--text-muted)',
            border: '1px solid var(--card-border)', cursor: 'pointer',
          }}>Clear</button>
        )}

        {result && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
            {result.total} break{result.total !== 1 ? 's' : ''} found
          </span>
        )}
      </div>

      {/* ── Semantic group panel (chips) ───────────────────────────────────── */}
      {showGroupPanel && (
        <div style={{
          padding: '12px 14px', marginBottom: 10,
          background: 'var(--surface)', border: '1px solid rgba(56,189,248,0.2)',
          borderRadius: 8,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.07em', color: '#38bdf8', marginBottom: 8,
          }}>
            🧠 Semantic Error Groups
            <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8, textTransform: 'none' }}>
              — AI-classified root causes, cross-project
            </span>
          </div>
          {groupsLoading ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading groups…</div>
          ) : semanticGroups.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              No groups yet. Errors are classified automatically after each ingest, or run
              <code style={{ marginLeft: 4, padding: '1px 5px', borderRadius: 3, background: 'rgba(255,255,255,0.06)' }}>
                POST /api/error-groups/backfill
              </code> to classify existing errors.
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {semanticGroups.map(g => (
                <GroupBadge
                  key={g.error_group_id}
                  name={`${g.error_group_name || 'Unnamed'} (${g.occurrence_count})`}
                  active={groupFilter === g.error_group_id}
                  onClick={() => {
                    setGroupFilter(prev => prev === g.error_group_id ? '' : g.error_group_id);
                    setPage(1);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Table / error / loading ─────────────────────────────────────────── */}
      {loading ? (
        <div data-testid="breaks-loading" style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
          Loading…
        </div>
      ) : loadError ? (
        <div style={{
          padding: '24px 20px', borderRadius: 8, fontSize: 13, textAlign: 'center',
          background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
          color: '#f87171',
        }}>
          <div style={{ marginBottom: 12 }}>⚠ {loadError}</div>
          <button onClick={() => setRetryTick(t => t + 1)} style={{
            padding: '6px 16px', borderRadius: 6, fontSize: 12, fontWeight: 600,
            background: 'rgba(239,68,68,0.15)', color: '#f87171',
            border: '1px solid rgba(239,68,68,0.3)', cursor: 'pointer',
          }}>Retry</button>
        </div>
      ) : (
        <>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--card-border)', borderRadius: 8, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--input-bg)' }}>
                  {['Project', 'Error Message', 'Group', 'Occurrences', 'First Seen', 'Last Seen', 'Status'].map(h => (
                    <th key={h} style={{
                      padding: '10px 16px', textAlign: 'left', fontWeight: 600,
                      color: 'var(--text-muted)', borderBottom: '1px solid var(--card-border)',
                      fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(result?.data ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
                      No breaks found
                    </td>
                  </tr>
                ) : (result?.data ?? []).map((b, i) => (
                  <tr key={i} data-testid="break-item" data-status={b.status}
                    onClick={() => navigate(`/breaks/${b.error_hash}?project_name=${encodeURIComponent(b.project_name)}`, {
                      state: {
                        project:            b.project_name,
                        file_name:          null,
                        error:              b.error_message,
                        error_hash:         b.error_hash,
                        error_detail:       null,
                        timestamp:          b.first_seen,
                        representative_id:  b.representative_id ?? null,
                      },
                    })}
                    style={{
                      borderBottom: '1px solid var(--card-border)',
                      background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                      cursor: 'pointer',
                    }}>

                    {/* Project */}
                    <td style={{ padding: '11px 16px', whiteSpace: 'nowrap' }}>
                      <span style={{
                        fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                        background: '#6366f120', color: '#818cf8',
                      }}>{b.project_name}</span>
                    </td>

                    {/* Error message */}
                    <td style={{ padding: '11px 16px', color: '#f87171', fontFamily: 'ui-monospace, monospace', fontSize: 12, maxWidth: 300, wordBreak: 'break-word' }}>
                      {b.error_message}
                    </td>

                    {/* Semantic group */}
                    <td style={{ padding: '11px 16px', maxWidth: 180 }}>
                      {b.error_group_name ? (
                        <button
                          onClick={e => {
                            e.stopPropagation();
                            setGroupFilter(prev => prev === b.error_group_id ? '' : b.error_group_id);
                            setShowGroupPanel(true);
                            setPage(1);
                          }}
                          title={`Filter by group: ${b.error_group_name}`}
                          style={{
                            padding: '2px 8px', borderRadius: 99, fontSize: 11, fontWeight: 600,
                            background: groupFilter === b.error_group_id ? 'rgba(56,189,248,0.2)' : 'rgba(56,189,248,0.07)',
                            color: '#38bdf8',
                            border: '1px solid rgba(56,189,248,0.25)',
                            cursor: 'pointer', whiteSpace: 'nowrap',
                            maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis',
                            display: 'block',
                          }}
                        >
                          {b.error_group_name}
                        </button>
                      ) : (
                        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>—</span>
                      )}
                    </td>

                    {/* Occurrences — stable sequential number, coloured by status */}
                    <td style={{ padding: '11px 16px', textAlign: 'center' }}>
                      <span style={{
                        fontWeight: 700, fontSize: 13,
                        color: b.status === 'new' ? '#818cf8'
                             : b.status === 'regression' ? '#f87171'
                             : '#fbbf24',
                      }}>
                        {b.occurrence_count}
                      </span>
                    </td>

                    {/* First seen */}
                    <td style={{ padding: '11px 16px', color: 'var(--text-muted)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                      {fmt(b.first_seen)}
                    </td>

                    {/* Last seen */}
                    <td style={{ padding: '11px 16px', color: 'var(--text-muted)', whiteSpace: 'nowrap', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                      {b.status === 'new' ? <span style={{ color: '#475569' }}>—</span> : fmt(b.last_seen)}
                    </td>

                    {/* Status */}
                    <td style={{ padding: '11px 16px' }}>
                      <StatusBadge status={b.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div data-testid="pagination">
            <PaginationControls currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        </>
      )}
    </div>
  );
}
