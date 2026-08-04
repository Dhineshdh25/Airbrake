"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Settings = Settings;
const jsx_runtime_1 = require("react/jsx-runtime");
/**
 * Settings view — Admin only.
 * Requirements: 6.5, 9.1
 */
const react_1 = require("react");
const api_1 = require("../lib/api");
const JiraSettings_1 = require("./JiraSettings");
const selectStyle = {
    background: 'var(--input-bg)',
    border: '1px solid var(--input-border)',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
};
const btnStyle = (variant) => ({
    padding: '5px 12px',
    borderRadius: 'var(--radius-sm)',
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    border: '1px solid var(--card-border)',
    background: variant === 'danger' ? 'rgba(239,68,68,0.1)' : 'transparent',
    color: variant === 'danger' ? '#ef4444' : 'var(--text-muted)',
    transition: 'all var(--transition)',
});
function Settings({ role }) {
    const [users, setUsers] = (0, react_1.useState)([]);
    const [retention, setRetention] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(true);
    const isAdmin = role === 'admin';
    (0, react_1.useEffect)(() => {
        if (!isAdmin)
            return;
        let cancelled = false;
        Promise.all([
            (0, api_1.apiFetch)('/api/users').then((r) => r.json()),
            (0, api_1.apiFetch)('/api/retention').then((r) => r.json()),
        ])
            .then(([usersData, retentionData]) => {
            if (!cancelled) {
                setUsers(usersData);
                setRetention(retentionData);
                setLoading(false);
            }
        })
            .catch(() => { if (!cancelled)
            setLoading(false); });
        return () => { cancelled = true; };
    }, [isAdmin]);
    if (!isAdmin) {
        // Non-admin users still see the Jira integration panel
        return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "settings", children: [(0, jsx_runtime_1.jsx)("div", { style: { marginBottom: 28 }, children: (0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Settings" }) }), (0, jsx_runtime_1.jsx)(JiraSettings_1.JiraSettings, {})] }));
    }
    return ((0, jsx_runtime_1.jsxs)("div", { "data-testid": "settings", children: [(0, jsx_runtime_1.jsxs)("div", { style: { marginBottom: 28 }, children: [(0, jsx_runtime_1.jsx)("h2", { style: { fontSize: 22, fontWeight: 700, marginBottom: 4 }, children: "Settings" }), (0, jsx_runtime_1.jsx)("p", { style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Manage users and data retention policies" })] }), loading ? ((0, jsx_runtime_1.jsx)("div", { "data-testid": "settings-loading", style: { padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }, children: "Loading\u2026" })) : ((0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', flexDirection: 'column', gap: 24 }, children: [(0, jsx_runtime_1.jsxs)("section", { "data-testid": "user-management", style: {
                            background: 'var(--surface)',
                            border: '1px solid var(--card-border)',
                            borderRadius: 'var(--radius-md)',
                            overflow: 'hidden',
                        }, children: [(0, jsx_runtime_1.jsx)("div", { style: { padding: '14px 18px', borderBottom: '1px solid var(--card-border)' }, children: (0, jsx_runtime_1.jsx)("h3", { style: { fontSize: 14, fontWeight: 600 }, children: "Users" }) }), (0, jsx_runtime_1.jsxs)("table", { style: { width: '100%', borderCollapse: 'collapse' }, children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { style: {
                                                fontSize: 11,
                                                fontWeight: 600,
                                                color: 'var(--text-muted)',
                                                textTransform: 'uppercase',
                                                letterSpacing: 0.8,
                                                borderBottom: '1px solid var(--card-border)',
                                            }, children: [(0, jsx_runtime_1.jsx)("th", { style: { padding: '10px 18px', textAlign: 'left', fontWeight: 600 }, children: "Email" }), (0, jsx_runtime_1.jsx)("th", { style: { padding: '10px 18px', textAlign: 'left', fontWeight: 600 }, children: "Role" }), (0, jsx_runtime_1.jsx)("th", { style: { padding: '10px 18px', textAlign: 'right', fontWeight: 600 }, children: "Actions" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: users.map((u, i) => ((0, jsx_runtime_1.jsxs)("tr", { "data-testid": "user-row", style: { borderBottom: i < users.length - 1 ? '1px solid var(--card-border)' : 'none' }, children: [(0, jsx_runtime_1.jsx)("td", { "data-testid": "user-email", style: { padding: '12px 18px', fontSize: 13.5 }, children: u.email }), (0, jsx_runtime_1.jsx)("td", { "data-testid": "user-role", style: { padding: '12px 18px', fontSize: 13, color: 'var(--text-muted)' }, children: u.role }), (0, jsx_runtime_1.jsx)("td", { style: { padding: '12px 18px', textAlign: 'right' }, children: (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', gap: 6, justifyContent: 'flex-end' }, children: [(0, jsx_runtime_1.jsx)("button", { "data-testid": "edit-user", "aria-label": `Edit ${u.email}`, style: btnStyle('ghost'), children: "Edit" }), (0, jsx_runtime_1.jsx)("button", { "data-testid": "delete-user", "aria-label": `Delete ${u.email}`, style: btnStyle('danger'), children: "Delete" })] }) })] }, u.id))) })] })] }), (0, jsx_runtime_1.jsxs)("section", { "data-testid": "retention-settings", style: {
                            background: 'var(--surface)',
                            border: '1px solid var(--card-border)',
                            borderRadius: 'var(--radius-md)',
                            padding: '18px',
                        }, children: [(0, jsx_runtime_1.jsx)("h3", { style: { fontSize: 14, fontWeight: 600, marginBottom: 14 }, children: "Data Retention" }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 12 }, children: [(0, jsx_runtime_1.jsx)("label", { htmlFor: "retention-select", style: { fontSize: 13, color: 'var(--text-muted)' }, children: "Retention period" }), (0, jsx_runtime_1.jsxs)("select", { id: "retention-select", "data-testid": "retention-selector", value: retention?.retentionDays ?? 30, onChange: () => { }, "aria-label": "Retention period", style: selectStyle, children: [(0, jsx_runtime_1.jsx)("option", { value: 30, children: "30 days" }), (0, jsx_runtime_1.jsx)("option", { value: 60, children: "60 days" }), (0, jsx_runtime_1.jsx)("option", { value: 90, children: "90 days" })] })] })] }), (0, jsx_runtime_1.jsx)(JiraSettings_1.JiraSettings, {})] }))] }));
}
//# sourceMappingURL=Settings.js.map