import { useLocation, useNavigate, useParams } from 'react-router-dom';
import type { CSSProperties } from 'react';
import { ErrorDetailModal } from '../components/ErrorDetailModal';

const linkBtnStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#818cf8',
  cursor: 'pointer',
  fontSize: 13,
  padding: 0,
  fontWeight: 500,
};

export function ErrorDetail() {
  const { errorHash } = useParams<{ errorHash: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const projectName = params.get('project_name') ?? params.get('project') ?? undefined;

  // Read log_id from the URL query string.
  // This is present when navigating from a Jira deep-link, a bookmark,
  // a browser refresh, or any direct URL that includes ?log_id=<uuid>.
  // Without this, the backend receives no log_id and falls back to
  // the group-aggregate status path, which can show the wrong occurrence.
  const logIdFromUrl = params.get('log_id') ?? undefined;

  if (!errorHash) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
        <p style={{ marginBottom: 16 }}>Invalid error detail route.</p>
        <button onClick={() => navigate('/breaks')} style={linkBtnStyle}>← Back to Breaks</button>
      </div>
    );
  }

  // After a resolve or reopen the BreaksList state is stale — navigate back
  // with a replace so the list re-mounts and re-fetches from the server.
  function handleClose() { navigate('/breaks', { replace: true }); }
  function handleRefresh() { /* navigation on close already causes a re-mount */ }

  // Navigation state (set by BreaksList.navigate()) takes priority.
  // If absent (direct URL, Jira link, refresh, new tab, incognito), synthesise
  // a minimal row with representative_id = logIdFromUrl so ErrorDetailModal
  // sends ?log_id=<uuid> to the backend and gets the exact occurrence back.
  const stateRow = location.state as import('../components/ErrorDetailModal').ErrorRow | undefined;
  const effectiveRow: import('../components/ErrorDetailModal').ErrorRow | undefined =
    stateRow ??
    (logIdFromUrl
      ? {
          project:           projectName ?? '',
          file_name:         null,
          error:             '',
          error_hash:        errorHash,
          timestamp:         null,
          representative_id: logIdFromUrl,
        }
      : undefined);

  return (
    <ErrorDetailModal
      row={effectiveRow}
      errorHash={errorHash}
      projectName={projectName}
      onClose={handleClose}
      onRefresh={handleRefresh}
    />
  );
}
