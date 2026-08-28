"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Settings = Settings;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * Settings view — admin and non-admin layouts.
 *
 * ADMIN:
 *   - Users section: full table of all users, role editing, add/remove workflow
 *   - Projects section: all projects with responsible-user assignment
 *   - Jira Integration section
 *
 * NON-ADMIN (viewer / developer):
 *   - Own row only: email, role, own Jira ticket counts
 *   - Jira Integration section
 *
 * Security:
 *   - All mutations go through the backend; the backend derives the caller's
 *     identity from the session cookie — never from a frontend-supplied user_id.
 *   - Ticket counts for other users are fetched via GET /api/users/<id>/tickets
 *     which is admin-gated server-side.
 *   - No user's oauth_subject or raw metadata is rendered.
 */
const react_1 = require("react");
const api_1 = require("../lib/api");
const AuthContext_1 = require("../auth/AuthContext");
const PaginationControls_1 = require("../components/PaginationControls");
const JiraSettings_1 = require("./JiraSettings");
// ── Existing VALID_ROLES from the backend (must stay in sync with middleware.py) ─
const VALID_ROLES = ['admin', 'developer', 'viewer'];
const PAGE_SIZE = 5;
// ── Shared visual tokens (matching existing dark-theme UI) ────────────────────
const S = {
    card: {
        background: 'var(--surface)',
        border: '1px solid var(--card-border)',
        borderRadius: 10,
        overflow: 'hidden',
    },
    cardHeader: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--card-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    cardTitle: { fontSize: 14, fontWeight: 600 },
    th: {
        padding: '10px 18px',
        textAlign: 'left',
        fontWeight: 600,
        fontSize: 11,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: 0.8,
        borderBottom: '1px solid var(--card-border)',
        whiteSpace: 'nowrap',
    },
    td: {
        padding: '13px 18px',
        fontSize: 13,
        verticalAlign: 'middle',
        borderBottom: '1px solid var(--card-border)',
    },
    btnPrimary: {
        padding: '6px 14px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        background: '#6366f1',
        color: '#fff',
        border: 'none',
        cursor: 'pointer',
    },
    btnSecondary: {
        padding: '6px 14px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 500,
        background: 'transparent',
        color: 'var(--text-muted)',
        border: '1px solid var(--card-border)',
        cursor: 'pointer',
    },
    btnDanger: {
        padding: '6px 14px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        background: 'rgba(239,68,68,0.1)',
        color: '#f87171',
        border: '1px solid rgba(239,68,68,0.25)',
        cursor: 'pointer',
    },
    input: {
        width: '100%',
        padding: '8px 10px',
        borderRadius: 6,
        border: '1px solid var(--input-border)',
        background: 'var(--input-bg)',
        color: 'var(--text)',
        fontSize: 13,
        outline: 'none',
        boxSizing: 'border-box',
    },
    select: {
        padding: '6px 10px',
        borderRadius: 6,
        border: '1px solid var(--input-border)',
        background: 'var(--input-bg)',
        color: 'var(--text)',
        fontSize: 12,
        cursor: 'pointer',
        outline: 'none',
    },
    errorMsg: {
        marginTop: 8,
        padding: '7px 11px',
        borderRadius: 6,
        fontSize: 12,
        color: '#f87171',
        background: 'rgba(239,68,68,0.08)',
        border: '1px solid rgba(239,68,68,0.2)',
    },
    successMsg: {
        marginTop: 8,
        padding: '7px 11px',
        borderRadius: 6,
        fontSize: 12,
        color: '#34d399',
        background: 'rgba(52,211,153,0.08)',
        border: '1px solid rgba(52,211,153,0.2)',
    },
};
// ── Ticket dropdown (unchanged from previous implementation) ──────────────────
function TicketDropdown({ userId, status, color, }) {
    const [total, setTotal] = (0, react_1.useState)(null);
    const [open, setOpen] = (0, react_1.useState)(false);
    const [page, setPage] = (0, react_1.useState)(0);
    const [tickets, setTickets] = (0, react_1.useState)([]);
    const [loading, setLoading] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
    const fetched = (0, react_1.useRef)(false);
    // Fetch total count once on mount, using the per-user endpoint
    (0, react_1.useEffect)(() => {
        if (fetched.current)
            return;
        fetched.current = true;
        (0, api_1.apiFetch)(`/api/jira/my-tickets?status=${status}&limit=1&offset=0`)
            .then(r => r.json())
            .then((d) => setTotal(d.total ?? 0))
            .catch(() => setTotal(0));
        // userId prop used to prevent stale closures when row changes
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [userId, status]);
    // Fetch page data whenever expanded or page changes
    (0, react_1.useEffect)(() => {
        if (!open)
            return;
        setLoading(true);
        setError('');
        (0, api_1.apiFetch)(`/api/jira/my-tickets?status=${status}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`)
            .then(r => r.json())
            .then((d) => setTickets(d.tickets ?? []))
            .catch(() => setError('Failed to load tickets.'))
            .finally(() => setLoading(false));
    }, [open, page, status, userId]);
    if (total === null) {
        return (0, jsx_runtime_1.jsx)("span", { style: { color: 'var(--text-muted)', fontSize: 12 }, children: "\u2014" });
    }
    if (total === 0) {
        return (0, jsx_runtime_1.jsx)("span", { style: { color: 'var(--text-muted)', fontSize: 12 }, children: "\u2014" });
    }
    const totalPages = Math.ceil(total / PAGE_SIZE);
    return ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("button", { onClick: () => { setOpen(o => !o); setPage(0); }, style: {
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    background: 'none', border: 'none', cursor: 'pointer', padding: 0, color,
                }, "aria-expanded": open, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 13, fontWeight: 700 }, children: total }), (0, jsx_runtime_1.jsx)("span", { style: {
                            fontSize: 9, opacity: 0.7, display: 'inline-block', transition: 'transform 0.15s',
                            transform: open ? 'rotate(180deg)' : 'none',
                        }, children: "\u25BC" })] }), open && ((0, jsx_runtime_1.jsx)("div", { style: {
                    marginTop: 8, background: 'var(--bg)', border: '1px solid var(--card-border)',
                    borderRadius: 8, overflow: 'hidden', minWidth: 280, position: 'relative', zIndex: 10,
                }, children: loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '10px 14px', fontSize: 12, color: 'var(--text-muted)' }, children: "Loading\u2026" })) : error ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '10px 14px', fontSize: 12, color: '#f87171' }, children: error })) : tickets.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '10px 14px', fontSize: 12, color: 'var(--text-muted)' }, children: "No tickets found." })) : ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [tickets.map((t, i) => ((0, jsx_runtime_1.jsxs)("div", { style: {
                                padding: '9px 13px',
                                borderBottom: i < tickets.length - 1 ? '1px solid var(--card-border)' : 'none',
                                display: 'flex', flexDirection: 'column', gap: 3,
                            }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }, children: [t.jira_url ? ((0, jsx_runtime_1.jsx)("a", { href: t.jira_url, target: "_blank", rel: "noreferrer", style: { fontSize: 11, fontWeight: 700, color: '#818cf8', fontFamily: 'ui-monospace, monospace', textDecoration: 'none' }, children: t.issue_key })) : ((0, jsx_runtime_1.jsx)("span", { style: { fontSize: 11, fontWeight: 700, color: '#818cf8', fontFamily: 'ui-monospace, monospace' }, children: t.issue_key })), t.jira_status && ((0, jsx_runtime_1.jsx)("span", { style: { fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 999, background: `${color}1a`, color }, children: t.jira_status }))] }), (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 340 }, children: t.error || '—' }), t.project_name && ((0, jsx_runtime_1.jsx)("div", { style: { fontSize: 10, color: 'var(--text-muted)' }, children: t.project_name }))] }, t.log_id))), totalPages > 1 && ((0, jsx_runtime_1.jsxs)("div", { style: {
                                padding: '7px 13px', borderTop: '1px solid var(--card-border)',
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11,
                            }, children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => setPage(p => Math.max(0, p - 1)), disabled: page === 0, style: { ...S.btnSecondary, padding: '3px 8px', opacity: page === 0 ? 0.4 : 1 }, children: "\u2190 Prev" }), (0, jsx_runtime_1.jsxs)("span", { style: { color: 'var(--text-muted)' }, children: [page + 1, " / ", totalPages] }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setPage(p => Math.min(totalPages - 1, p + 1)), disabled: page >= totalPages - 1, style: { ...S.btnSecondary, padding: '3px 8px', opacity: page >= totalPages - 1 ? 0.4 : 1 }, children: "Next \u2192" })] }))] })) }))] }));
}
// ── Per-user ticket counts for the admin users table ──────────────────────────
// Fetches GET /api/users/<id>/tickets — admin-gated on the backend.
// Shows the COUNT only. Expanding to show ticket detail is intentionally
// disabled for other users: the only available listing endpoint (/api/jira/my-tickets)
// is session-scoped and would return the admin's own tickets instead of the
// target user's — which would be cross-user ticket leakage.
// The currently-logged-in admin's own row uses TicketDropdown (below) which
// calls my-tickets correctly.
function AdminTicketCell({ userId, status, color, }) {
    const [count, setCount] = (0, react_1.useState)(null);
    const fetched = (0, react_1.useRef)(false);
    // Reset and re-fetch whenever userId changes (defensive guard)
    (0, react_1.useEffect)(() => {
        fetched.current = false;
        setCount(null);
    }, [userId]);
    (0, react_1.useEffect)(() => {
        if (fetched.current)
            return;
        fetched.current = true;
        (0, api_1.apiFetch)(`/api/users/${encodeURIComponent(userId)}/tickets`)
            .then(r => r.json())
            .then((d) => {
            setCount(status === 'resolved' ? (d.resolved ?? 0) : (d.open ?? 0));
        })
            .catch(() => setCount(0));
    }, [userId, status]);
    if (count === null)
        return (0, jsx_runtime_1.jsx)("span", { style: { color: 'var(--text-muted)', fontSize: 12 }, children: "\u2014" });
    if (count === 0)
        return (0, jsx_runtime_1.jsx)("span", { style: { color: 'var(--text-muted)', fontSize: 12 }, children: "\u2014" });
    // Count only — no dropdown expansion for other users' tickets.
    // Expanding would require a server-side per-user ticket listing endpoint
    // which does not yet exist. Showing count only is safe and accurate.
    return ((0, jsx_runtime_1.jsx)("span", { style: { fontSize: 13, fontWeight: 700, color }, children: count }));
}
// ── Inline role selector ───────────────────────────────────────────────────────
function RoleSelector({ userId, currentRole, onUpdated, isSelf, }) {
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
    const [role, setRole] = (0, react_1.useState)(currentRole);
    // Keep local state in sync if parent refreshes the user list
    (0, react_1.useEffect)(() => { setRole(currentRole); }, [currentRole]);
    async function handleChange(newRole) {
        if (newRole === role)
            return;
        setSaving(true);
        setError('');
        const prev = role;
        setRole(newRole); // optimistic
        try {
            const r = await (0, api_1.apiFetch)(`/api/users/${encodeURIComponent(userId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: newRole }),
            });
            const d = await r.json();
            if (d.error) {
                setRole(prev);
                setError(d.message || d.error);
            }
            else
                onUpdated(d);
        }
        catch {
            setRole(prev);
            setError('Save failed.');
        }
        finally {
            setSaving(false);
        }
    }
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("select", { value: role, disabled: saving, onChange: e => handleChange(e.target.value), style: { ...S.select, opacity: saving ? 0.6 : 1 }, title: isSelf ? 'You cannot change your own role here' : undefined, children: VALID_ROLES.map(r => ((0, jsx_runtime_1.jsx)("option", { value: r, children: r }, r))) }), error && (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#f87171', marginTop: 4 }, children: error })] }));
}
// ── Add User modal/inline form ────────────────────────────────────────────────
function AddUserForm({ onAdded, onCancel }) {
    const [email, setEmail] = (0, react_1.useState)('');
    const [role, setRole] = (0, react_1.useState)('viewer');
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
    async function handleSubmit(e) {
        e.preventDefault();
        const trimmed = email.trim().toLowerCase();
        if (!trimmed || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmed)) {
            setError('Enter a valid email address.');
            return;
        }
        setSaving(true);
        setError('');
        try {
            const r = await (0, api_1.apiFetch)('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: trimmed, role }),
            });
            const d = await r.json();
            if (!r.ok) {
                setError(d.message || d.error || 'Failed to add user.');
            }
            else {
                onAdded(d);
            }
        }
        catch {
            setError('Network error. Please try again.');
        }
        finally {
            setSaving(false);
        }
    }
    return ((0, jsx_runtime_1.jsx)("div", { style: {
            margin: '0 0 0 0',
            padding: '16px 18px',
            borderBottom: '1px solid var(--card-border)',
            background: 'rgba(99,102,241,0.04)',
        }, children: (0, jsx_runtime_1.jsxs)("form", { onSubmit: handleSubmit, children: [(0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }, children: [(0, jsx_runtime_1.jsxs)("div", { style: { flex: '1 1 240px' }, children: [(0, jsx_runtime_1.jsx)("label", { style: { display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6 }, children: "Email" }), (0, jsx_runtime_1.jsx)("input", { type: "email", autoFocus: true, placeholder: "user@example.com", value: email, onChange: e => setEmail(e.target.value), style: S.input })] }), (0, jsx_runtime_1.jsxs)("div", { style: { flex: '0 0 130px' }, children: [(0, jsx_runtime_1.jsx)("label", { style: { display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6 }, children: "Role" }), (0, jsx_runtime_1.jsx)("select", { value: role, onChange: e => setRole(e.target.value), style: { ...S.select, width: '100%', padding: '8px 10px' }, children: VALID_ROLES.map(r => (0, jsx_runtime_1.jsx)("option", { value: r, children: r }, r)) })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 8, paddingBottom: 1 }, children: [(0, jsx_runtime_1.jsx)("button", { type: "submit", disabled: saving, style: { ...S.btnPrimary, opacity: saving ? 0.7 : 1 }, children: saving ? 'Adding…' : 'Add' }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: onCancel, style: S.btnSecondary, children: "Cancel" })] })] }), error && (0, jsx_runtime_1.jsx)("div", { style: S.errorMsg, children: error })] }) }));
}
// ── Admin Users section ───────────────────────────────────────────────────────
function AdminUsersSection({ currentUserId }) {
    const [users, setUsers] = (0, react_1.useState)([]);
    const [loadingUsers, setLoading] = (0, react_1.useState)(true);
    const [fetchError, setFetchError] = (0, react_1.useState)('');
    const [showAddForm, setShowAddForm] = (0, react_1.useState)(false);
    const [removeMode, setRemoveMode] = (0, react_1.useState)(false);
    const [selected, setSelected] = (0, react_1.useState)(new Set());
    const [removing, setRemoving] = (0, react_1.useState)(false);
    const [removeError, setRemoveError] = (0, react_1.useState)('');
    const [successMsg, setSuccessMsg] = (0, react_1.useState)('');
    const [page, setPage] = (0, react_1.useState)(1);
    const loadUsers = (0, react_1.useCallback)(() => {
        setLoading(true);
        setFetchError('');
        (0, api_1.apiFetch)('/api/users')
            .then(r => r.json())
            .then((d) => { setUsers(Array.isArray(d) ? d : []); })
            .catch(() => setFetchError('Failed to load users.'))
            .finally(() => setLoading(false));
    }, []);
    (0, react_1.useEffect)(() => { loadUsers(); }, [loadUsers]);
    function handleUserAdded(u) {
        setUsers(prev => [u, ...prev]);
        setShowAddForm(false);
        flash('User added successfully.');
    }
    function handleRoleUpdated(updated) {
        setUsers(prev => prev.map(u => u.id === updated.id ? { ...u, role: updated.role } : u));
    }
    function toggleSelect(id) {
        setSelected(prev => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    }
    async function handleRemoveConfirmed() {
        if (selected.size === 0)
            return;
        const toDelete = [...selected];
        const names = users.filter(u => toDelete.includes(u.id)).map(u => u.email).join(', ');
        if (!window.confirm(`Permanently delete ${toDelete.length} user(s)?\n\n${names}\n\nThis cannot be undone.`))
            return;
        setRemoving(true);
        setRemoveError('');
        const errors = [];
        for (const id of toDelete) {
            try {
                const r = await (0, api_1.apiFetch)(`/api/users/${encodeURIComponent(id)}`, { method: 'DELETE' });
                if (!r.ok && r.status !== 204) {
                    const d = await r.json();
                    errors.push(d.message || d.error || `Failed to delete ${id}`);
                }
            }
            catch {
                errors.push(`Network error deleting ${id}`);
            }
        }
        setRemoving(false);
        if (errors.length > 0) {
            setRemoveError(errors.join(' | '));
        }
        else {
            setUsers(prev => prev.filter(u => !toDelete.includes(u.id)));
            setSelected(new Set());
            setRemoveMode(false);
            flash(`${toDelete.length} user(s) removed.`);
        }
    }
    function flash(msg) {
        setSuccessMsg(msg);
        setTimeout(() => setSuccessMsg(''), 3500);
    }
    const totalPages = Math.max(1, Math.ceil(users.length / PAGE_SIZE));
    const pagedUsers = users.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    (0, react_1.useEffect)(() => {
        setPage(1);
    }, [users.length]);
    (0, react_1.useEffect)(() => {
        if (page > totalPages)
            setPage(totalPages);
    }, [page, totalPages]);
    return ((0, jsx_runtime_1.jsxs)("section", { style: S.card, children: [(0, jsx_runtime_1.jsxs)("div", { style: S.cardHeader, children: [(0, jsx_runtime_1.jsx)("span", { style: S.cardTitle, children: "Users" }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 8 }, children: [!removeMode && ((0, jsx_runtime_1.jsx)("button", { onClick: () => { setShowAddForm(f => !f); setRemoveMode(false); }, style: S.btnPrimary, children: showAddForm ? 'Cancel' : '+ Add user' })), !showAddForm && (removeMode ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("button", { onClick: handleRemoveConfirmed, disabled: selected.size === 0 || removing, style: { ...S.btnDanger, opacity: (selected.size === 0 || removing) ? 0.5 : 1 }, children: removing ? 'Removing…' : `Remove (${selected.size})` }), (0, jsx_runtime_1.jsx)("button", { onClick: () => { setRemoveMode(false); setSelected(new Set()); setRemoveError(''); }, style: S.btnSecondary, children: "Cancel" })] })) : ((0, jsx_runtime_1.jsx)("button", { onClick: () => { setRemoveMode(true); setShowAddForm(false); }, style: S.btnSecondary, children: "Remove user" })))] })] }), showAddForm && (0, jsx_runtime_1.jsx)(AddUserForm, { onAdded: handleUserAdded, onCancel: () => setShowAddForm(false) }), successMsg && (0, jsx_runtime_1.jsx)("div", { style: { ...S.successMsg, margin: '10px 18px 0' }, children: successMsg }), removeError && (0, jsx_runtime_1.jsx)("div", { style: { ...S.errorMsg, margin: '10px 18px 0' }, children: removeError }), loadingUsers ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }, children: "Loading users\u2026" })) : fetchError ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '16px 18px', fontSize: 13, color: '#f87171' }, children: fetchError })) : users.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }, children: "No users found." })) : ((0, jsx_runtime_1.jsx)("div", { style: { overflowX: 'auto' }, children: (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse' }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Email" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Role" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Resolved Tickets" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Open Tickets" }), removeMode && (0, jsx_runtime_1.jsx)("th", { style: { ...S.th, textAlign: 'center' }, children: "Select" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: pagedUsers.map((u, idx) => {
                                const isLast = idx === pagedUsers.length - 1;
                                const tdStyle = { ...S.td, borderBottom: isLast ? 'none' : '1px solid var(--card-border)' };
                                const isSelf = u.id === currentUserId;
                                return ((0, jsx_runtime_1.jsxs)("tr", { style: { background: selected.has(u.id) ? 'rgba(239,68,68,0.04)' : 'transparent', transition: 'background 0.12s' }, children: [(0, jsx_runtime_1.jsxs)("td", { style: tdStyle, children: [(0, jsx_runtime_1.jsx)("span", { style: { fontSize: 13.5 }, children: u.email }), isSelf && ((0, jsx_runtime_1.jsx)("span", { style: { marginLeft: 8, fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, background: 'rgba(99,102,241,0.12)', padding: '2px 6px', borderRadius: 999 }, children: "You" }))] }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)(RoleSelector, { userId: u.id, currentRole: u.role, onUpdated: handleRoleUpdated, isSelf: isSelf }) }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)(AdminTicketCell, { userId: u.id, status: "resolved", color: "#34d399" }) }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)(AdminTicketCell, { userId: u.id, status: "open", color: "#818cf8" }) }), removeMode && ((0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, textAlign: 'center' }, children: (0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: selected.has(u.id), onChange: () => toggleSelect(u.id), disabled: isSelf, title: isSelf ? 'You cannot delete yourself' : undefined, style: { cursor: isSelf ? 'not-allowed' : 'pointer', width: 15, height: 15 } }) }))] }, u.id));
                            }) })] }) })), totalPages > 1 && ((0, jsx_runtime_1.jsx)("div", { style: { padding: '12px 18px 18px' }, children: (0, jsx_runtime_1.jsx)(PaginationControls_1.PaginationControls, { currentPage: page, totalPages: totalPages, onPageChange: setPage }) }))] }));
}
// ── Projects section ──────────────────────────────────────────────────────────
function ProjectsSection({ users }) {
    const [projects, setProjects] = (0, react_1.useState)([]);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const [error, setError] = (0, react_1.useState)('');
    const [page, setPage] = (0, react_1.useState)(1);
    (0, react_1.useEffect)(() => {
        setLoading(true);
        (0, api_1.apiFetch)('/api/projects')
            .then(r => r.json())
            .then((d) => setProjects(Array.isArray(d) ? d : []))
            .catch(() => setError('Failed to load projects.'))
            .finally(() => setLoading(false));
    }, []);
    const totalPages = Math.max(1, Math.ceil(projects.length / PAGE_SIZE));
    const pagedProjects = projects.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    (0, react_1.useEffect)(() => {
        setPage(1);
    }, [projects.length]);
    (0, react_1.useEffect)(() => {
        if (page > totalPages)
            setPage(totalPages);
    }, [page, totalPages]);
    return ((0, jsx_runtime_1.jsxs)("section", { style: S.card, children: [(0, jsx_runtime_1.jsx)("div", { style: S.cardHeader, children: (0, jsx_runtime_1.jsx)("span", { style: S.cardTitle, children: "Projects" }) }), loading ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }, children: "Loading projects\u2026" })) : error ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '16px 18px', fontSize: 13, color: '#f87171' }, children: error })) : projects.length === 0 ? ((0, jsx_runtime_1.jsx)("div", { style: { padding: '20px 18px', fontSize: 13, color: 'var(--text-muted)' }, children: "No projects found." })) : ((0, jsx_runtime_1.jsx)("div", { style: { overflowX: 'auto' }, children: (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse' }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Project" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Category" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Responsible User" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: pagedProjects.map((p, idx) => {
                                const isLast = idx === pagedProjects.length - 1;
                                const tdStyle = { ...S.td, borderBottom: isLast ? 'none' : '1px solid var(--card-border)' };
                                return ((0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)("span", { style: { fontWeight: 600 }, children: p.name }) }), (0, jsx_runtime_1.jsx)("td", { style: { ...tdStyle, color: 'var(--text-muted)', fontSize: 12 }, children: p.category || '—' }), (0, jsx_runtime_1.jsx)("td", { style: tdStyle, children: (0, jsx_runtime_1.jsx)(ResponsibleUserSelector, { project: p, users: users, onUpdated: updated => setProjects(prev => prev.map(x => x.id === updated.id ? updated : x)) }) })] }, p.id));
                            }) })] }) })), totalPages > 1 && ((0, jsx_runtime_1.jsx)("div", { style: { padding: '12px 18px 18px' }, children: (0, jsx_runtime_1.jsx)(PaginationControls_1.PaginationControls, { currentPage: page, totalPages: totalPages, onPageChange: setPage }) }))] }));
}
// ── Responsible user selector (per project row) ───────────────────────────────
function ResponsibleUserSelector({ project, users, onUpdated, }) {
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)('');
    const [value, setValue] = (0, react_1.useState)(project.responsible_user_id || '');
    (0, react_1.useEffect)(() => { setValue(project.responsible_user_id || ''); }, [project.responsible_user_id]);
    async function handleChange(newUserId) {
        if (newUserId === value)
            return;
        setSaving(true);
        setError('');
        const prev = value;
        setValue(newUserId); // optimistic
        try {
            const r = await (0, api_1.apiFetch)(`/api/projects/${encodeURIComponent(project.id)}/responsible-user`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: newUserId || null }),
            });
            const d = await r.json();
            if (!r.ok) {
                setValue(prev);
                setError(d.message || d.error || 'Save failed.');
            }
            else
                onUpdated(d);
        }
        catch {
            setValue(prev);
            setError('Network error.');
        }
        finally {
            setSaving(false);
        }
    }
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("select", { value: value, disabled: saving, onChange: e => handleChange(e.target.value), style: { ...S.select, opacity: saving ? 0.6 : 1, minWidth: 200 }, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "Unassigned" }), users.map(u => ((0, jsx_runtime_1.jsx)("option", { value: u.id, children: u.email }, u.id)))] }), error && (0, jsx_runtime_1.jsx)("div", { style: { fontSize: 11, color: '#f87171', marginTop: 4 }, children: error })] }));
}
// ── Non-admin own-row section ─────────────────────────────────────────────────
// Shows only the current user's own email, role, and their Jira ticket counts.
function OwnUserSection({ currentUser }) {
    return ((0, jsx_runtime_1.jsxs)("section", { style: S.card, children: [(0, jsx_runtime_1.jsx)("div", { style: S.cardHeader, children: (0, jsx_runtime_1.jsx)("span", { style: S.cardTitle, children: "Users" }) }), (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse' }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Email" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Role" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Resolved Tickets" }), (0, jsx_runtime_1.jsx)("th", { style: S.th, children: "Open Tickets" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("td", { style: { ...S.td, borderBottom: 'none' }, children: currentUser.email }), (0, jsx_runtime_1.jsx)("td", { style: { ...S.td, borderBottom: 'none', color: 'var(--text-muted)' }, children: currentUser.role }), (0, jsx_runtime_1.jsx)("td", { style: { ...S.td, borderBottom: 'none' }, children: (0, jsx_runtime_1.jsx)(TicketDropdown, { userId: currentUser.id, status: "resolved", color: "#34d399" }) }), (0, jsx_runtime_1.jsx)("td", { style: { ...S.td, borderBottom: 'none' }, children: (0, jsx_runtime_1.jsx)(TicketDropdown, { userId: currentUser.id, status: "open", color: "#818cf8" }) })] }) })] })] }));
}
function Settings({ role }) {
    const { user } = (0, AuthContext_1.useAuth)();
    // Admin fetches the full user list so the Projects section can populate
    // its responsible-user dropdowns without a second round trip.
    const [allUsers, setAllUsers] = (0, react_1.useState)([]);
    const isAdmin = role === 'admin';
    (0, react_1.useEffect)(() => {
        if (!isAdmin)
            return;
        (0, api_1.apiFetch)('/api/users')
            .then(r => r.json())
            .then((d) => setAllUsers(Array.isArray(d) ? d : []))
            .catch(() => { });
    }, [isAdmin]);
    if (!isAdmin) {
        // Non-admin: own row + Jira integration only
        return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "settings", children: [(0, jsx_runtime_1.jsx)("div", { style: { marginBottom: 28 }, children: (0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Settings" }) }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 24 }, children: [user && (0, jsx_runtime_1.jsx)(OwnUserSection, { currentUser: user }), (0, jsx_runtime_1.jsx)(JiraSettings_1.JiraSettings, {})] })] }));
    }
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "settings", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 28 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Settings" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Manage users, projects, and integrations." })] }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 24 }, children: [(0, jsx_runtime_1.jsx)(AdminUsersSection, { currentUserId: user?.id ?? '' }), (0, jsx_runtime_1.jsx)(ProjectsSection, { users: allUsers }), (0, jsx_runtime_1.jsx)(JiraSettings_1.JiraSettings, {})] })] }));
}
//# sourceMappingURL=Settings.js.map