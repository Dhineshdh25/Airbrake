import { Pool } from 'pg';
import {
  createGetErrorDetailHandler,
  createTopProjectsHandler,
  createTopErrorProjectsHandler,
} from '../projectDashboardRouter';

function makeRes() {
  const res: any = {
    statusCode: 200,
    body: undefined,
    status(code: number) {
      res.statusCode = code;
      return res;
    },
    json(body: unknown) {
      res.body = body;
    },
  };
  return res;
}

describe('GET /api/breaks/detail/:errorHash', () => {
  it('returns the stored error detail for a matching hash', async () => {
    const query = jest.fn()
      .mockResolvedValueOnce({ rows: [{ exists: true }] })
      .mockResolvedValueOnce({ rows: [{ table_name: 'toc_extractor' }] })
      .mockResolvedValueOnce({
        rows: [{
          project_name: 'toc_extractor',
          file_name: 'parser.py',
          error_message: 'TOC not found',
          error_detail: 'Traceback: missing TOC section',
          error_hash: 'abc123',
          timestamp: '2024-01-15T12:00:00Z',
          error_status: 'open',
          failure_count: 2,
          reopened_at: null,
        }],
      });

    const handler = createGetErrorDetailHandler({ query } as unknown as Pool);
    const res = makeRes();

    await handler({
      params: { errorHash: 'abc123' },
      query: { project_name: 'toc_extractor' },
    } as any, res);

    expect(res.statusCode).toBe(200);
    expect(res.body).toMatchObject({
      project_name: 'toc_extractor',
      error_message: 'TOC not found',
      error_detail: 'Traceback: missing TOC section',
      error_hash: 'abc123',
      occurrence_count: 2,
      status: 'existing',
    });
  });

  it('passes from/to range filters to top-projects SQL', async () => {
    const query = jest.fn()
      .mockResolvedValueOnce({ rows: [{ table_name: 'toc_extractor' }] })
      .mockResolvedValueOnce({ rows: [{ project_name: 'toc extractor', total: 42 }] });

    const handler = createTopProjectsHandler({ query } as unknown as Pool);
    const res = makeRes();

    await handler({ query: { from: '2026-08-01T00:00:00.000Z', to: '2026-08-07T23:59:59.000Z' } } as any, res);

    expect(query).toHaveBeenCalledTimes(2);
    expect(query.mock.calls[1][0]).toContain("timestamp >= '2026-08-01T00:00:00.000Z'");
    expect(query.mock.calls[1][0]).toContain("timestamp <= '2026-08-07T23:59:59.000Z'");
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ projects: [{ project_name: 'toc extractor', total: 42 }] });
  });

  it('passes from/to range filters to top-error-projects SQL', async () => {
    const query = jest.fn()
      .mockResolvedValueOnce({ rows: [{ table_name: 'toc_extractor' }] })
      .mockResolvedValueOnce({ rows: [{ project_name: 'toc extractor', total: 5 }] });

    const handler = createTopErrorProjectsHandler({ query } as unknown as Pool);
    const res = makeRes();

    await handler({ query: { from: '2026-08-01T00:00:00.000Z', to: '2026-08-07T23:59:59.000Z' } } as any, res);

    expect(query).toHaveBeenCalledTimes(2);
    expect(query.mock.calls[1][0]).toContain("timestamp >= '2026-08-01T00:00:00.000Z'");
    expect(query.mock.calls[1][0]).toContain("timestamp <= '2026-08-07T23:59:59.000Z'");
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ projects: [{ project_name: 'toc extractor', total: 5 }] });
  });
});
