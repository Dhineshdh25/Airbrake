"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const jsx_runtime_1 = require("react/jsx-runtime");
require("@testing-library/jest-dom");
const react_1 = require("@testing-library/react");
const react_router_dom_1 = require("react-router-dom");
const BreaksList_1 = require("../BreaksList");
const api_1 = require("../../lib/api");
jest.mock('../../lib/api', () => ({
    apiFetch: jest.fn(),
}));
describe('BreaksList resolved status', () => {
    it('shows resolved for a resolved break row', async () => {
        api_1.apiFetch.mockImplementation((path) => {
            if (path === '/api/projects') {
                return Promise.resolve({ json: async () => [] });
            }
            if (path.startsWith('/api/breaks/grouped')) {
                return Promise.resolve({
                    json: async () => ({
                        data: [{
                                project_name: 'Alpha',
                                error_message: 'Null pointer',
                                error_hash: 'abc123',
                                error_group_id: 'group-1',
                                error_group_name: 'Null pointer group',
                                representative_id: 'log-1',
                                occurrence_count: 1,
                                first_seen: '2026-07-29T10:00:00Z',
                                last_seen: '2026-07-29T10:00:00Z',
                                status: 'resolved',
                            }],
                        total: 1,
                        page: 1,
                        limit: 20,
                    }),
                });
            }
            return Promise.resolve({ json: async () => ({}) });
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(react_router_dom_1.MemoryRouter, { children: (0, jsx_runtime_1.jsx)(BreaksList_1.BreaksList, {}) }));
        await (0, react_1.waitFor)(() => expect(react_1.screen.getByText('✓ Resolved')).toBeInTheDocument());
    });
});
//# sourceMappingURL=BreaksList.resolved.test.js.map