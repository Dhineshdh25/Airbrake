"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.coercePageValue = coercePageValue;
exports.PaginationControls = PaginationControls;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
function coercePageValue(rawValue, totalPages) {
    const trimmed = rawValue.trim();
    if (trimmed === '' || !/^\d+$/.test(trimmed))
        return null;
    const nextPage = Number(trimmed);
    if (!Number.isInteger(nextPage))
        return null;
    if (totalPages <= 0)
        return 1;
    if (nextPage <= 0)
        return 1;
    if (nextPage > totalPages)
        return totalPages;
    return nextPage;
}
function PaginationControls({ currentPage, totalPages, onPageChange, }) {
    const [draftPage, setDraftPage] = (0, react_1.useState)(String(currentPage));
    (0, react_1.useEffect)(() => {
        setDraftPage(String(currentPage));
    }, [currentPage]);
    if (totalPages <= 1)
        return null;
    const safeCurrentPage = Math.min(Math.max(1, currentPage), totalPages);
    const isPreviousDisabled = safeCurrentPage <= 1;
    const isNextDisabled = safeCurrentPage >= totalPages;
    const commitChange = (nextValue) => {
        const coerced = coercePageValue(nextValue, totalPages);
        if (coerced == null || coerced === safeCurrentPage) {
            setDraftPage(String(safeCurrentPage));
            return;
        }
        onPageChange(coerced);
    };
    return ((0, jsx_runtime_1.jsxs)("div", { style: {
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            marginTop: 18,
            paddingTop: 14,
            borderTop: '1px solid var(--card-border)',
            flexWrap: 'wrap',
        }, children: [(0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => onPageChange(Math.max(1, safeCurrentPage - 1)), disabled: isPreviousDisabled, style: {
                    padding: '7px 16px',
                    borderRadius: 6,
                    border: '1px solid var(--card-border)',
                    background: isPreviousDisabled ? 'rgba(255,255,255,0.03)' : 'var(--surface)',
                    color: isPreviousDisabled ? 'var(--text-muted)' : 'var(--text)',
                    cursor: isPreviousDisabled ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    opacity: isPreviousDisabled ? 0.55 : 1,
                }, children: "\u2190 Previous" }), (0, jsx_runtime_1.jsxs)("div", { style: { display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 13 }, children: [(0, jsx_runtime_1.jsx)("span", { children: "Page" }), (0, jsx_runtime_1.jsx)("input", { type: "text", inputMode: "numeric", "aria-label": "Page number", value: draftPage, onChange: (event) => setDraftPage(event.target.value), onBlur: () => commitChange(draftPage), onKeyDown: (event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                commitChange(draftPage);
                            }
                        }, style: {
                            width: 58,
                            textAlign: 'center',
                            padding: '7px 8px',
                            borderRadius: 6,
                            border: '1px solid var(--input-border)',
                            background: 'var(--input-bg)',
                            color: 'var(--text)',
                            fontSize: 13,
                            outline: 'none',
                        } }), (0, jsx_runtime_1.jsxs)("span", { children: ["of ", totalPages] })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => onPageChange(Math.min(totalPages, safeCurrentPage + 1)), disabled: isNextDisabled, style: {
                    padding: '7px 16px',
                    borderRadius: 6,
                    border: '1px solid var(--card-border)',
                    background: isNextDisabled ? 'rgba(255,255,255,0.03)' : 'var(--surface)',
                    color: isNextDisabled ? 'var(--text-muted)' : 'var(--text)',
                    cursor: isNextDisabled ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    opacity: isNextDisabled ? 0.55 : 1,
                }, children: "Next \u2192" })] }));
}
//# sourceMappingURL=PaginationControls.js.map