import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { BreaksList } from '../BreaksList';
import { apiFetch } from '../../lib/api';

jest.mock('../../lib/api', () => ({
  apiFetch: jest.fn(),
}));

describe('BreaksList resolved status', () => {
  it('shows resolved for a resolved break row', async () => {
    (apiFetch as jest.Mock).mockImplementation((path: string) => {
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

    render(
      <MemoryRouter>
        <BreaksList />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('✓ Resolved')).toBeInTheDocument());
  });
});
