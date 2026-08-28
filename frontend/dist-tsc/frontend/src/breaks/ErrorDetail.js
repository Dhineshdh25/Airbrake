"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ErrorDetail = ErrorDetail;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_router_dom_1 = require("react-router-dom");
const ErrorDetailModal_1 = require("../components/ErrorDetailModal");
const linkBtnStyle = {
    background: 'none',
    border: 'none',
    color: '#818cf8',
    cursor: 'pointer',
    fontSize: 13,
    padding: 0,
    fontWeight: 500,
};
function ErrorDetail() {
    const { errorHash } = (0, react_router_dom_1.useParams)();
    const navigate = (0, react_router_dom_1.useNavigate)();
    const location = (0, react_router_dom_1.useLocation)();
    const params = new URLSearchParams(location.search);
    const projectName = params.get('project_name') ?? params.get('project') ?? undefined;
    // Read log_id from the URL query string.
    // This is present when navigating from a Jira deep-link, a bookmark,
    // a browser refresh, or any direct URL that includes ?log_id=<uuid>.
    // Without this, the backend receives no log_id and falls back to
    // the group-aggregate status path, which can show the wrong occurrence.
    const logIdFromUrl = params.get('log_id') ?? undefined;
    if (!errorHash) {
        return ((0, jsx_runtime_1.jsxs)("div", { style: { padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)' }, children: [(0, jsx_runtime_1.jsx)("p", { style: { marginBottom: 16 }, children: "Invalid error detail route." }), (0, jsx_runtime_1.jsx)("button", { onClick: () => navigate('/breaks'), style: linkBtnStyle, children: "\u2190 Back to Breaks" })] }));
    }
    // After a resolve or reopen the BreaksList state is stale — navigate back
    // with a replace so the list re-mounts and re-fetches from the server.
    function handleClose() { navigate('/breaks', { replace: true }); }
    function handleRefresh() { }
    // Navigation state (set by BreaksList.navigate()) takes priority.
    // If absent (direct URL, Jira link, refresh, new tab, incognito), synthesise
    // a minimal row with representative_id = logIdFromUrl so ErrorDetailModal
    // sends ?log_id=<uuid> to the backend and gets the exact occurrence back.
    const stateRow = location.state;
    const effectiveRow = stateRow ??
        (logIdFromUrl
            ? {
                project: projectName ?? '',
                file_name: null,
                error: '',
                error_hash: errorHash,
                timestamp: null,
                representative_id: logIdFromUrl,
            }
            : undefined);
    return ((0, jsx_runtime_1.jsx)(ErrorDetailModal_1.ErrorDetailModal, { row: effectiveRow, errorHash: errorHash, projectName: projectName, onClose: handleClose, onRefresh: handleRefresh }));
}
//# sourceMappingURL=ErrorDetail.js.map