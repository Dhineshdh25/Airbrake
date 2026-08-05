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
    if (!errorHash) {
        return ((0, jsx_runtime_1.jsxs)("div", { style: { padding: '60px 0', textAlign: 'center', color: 'var(--text-muted)' }, children: [(0, jsx_runtime_1.jsx)("p", { style: { marginBottom: 16 }, children: "Invalid error detail route." }), (0, jsx_runtime_1.jsx)("button", { onClick: () => navigate('/breaks'), style: linkBtnStyle, children: "\u2190 Back to Breaks" })] }));
    }
    // After a resolve or reopen the BreaksList state is stale — navigate back
    // with a replace so the list re-mounts and re-fetches from the server.
    function handleClose() { navigate('/breaks', { replace: true }); }
    function handleRefresh() { }
    return ((0, jsx_runtime_1.jsx)(ErrorDetailModal_1.ErrorDetailModal, { row: location.state, errorHash: errorHash, projectName: projectName, onClose: handleClose, onRefresh: handleRefresh }));
}
//# sourceMappingURL=ErrorDetail.js.map