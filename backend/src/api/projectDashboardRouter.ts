/**
 * Project Dashboard Router
 * Serves the 4 endpoints the frontend Dashboard.tsx calls:
 *   GET /api/dashboard/top-projects       — top 10 by total row count
 *   GET /api/dashboard/top-error-projects — top 10 by error row count
 *   GET /api/dashboard/today-errors       — all errors with a timestamp of today (UTC)
 *   GET /api/dashboard/errors             — errors filtered by optional ?from=&to= ISO params
 *
 * No auth required — these are internal monitoring endpoints.
 * Data is spread across 85 individual project tables; we discover them
 * dynamically via information_schema so no hardcoded table list is needed.
 */

import { Pool } from 'pg';
import { sendTeamsAlert } from '../alerts/teamsNotifier';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Returns table names for LIVE projects only.
 * A project is live when projects.is_live = true.
 * Only includes tables that have both `error_status` and `error_hash` columns.
 * Falls back to all project tables if the is_live column hasn't been migrated yet.
 */
async function getProjectTables(pool: Pool): Promise<string[]> {
  // Graceful fallback if migration 033 hasn't run yet
  const { rows: colCheck } = await pool.query<{ exists: boolean }>(`
    SELECT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'projects' AND column_name = 'is_live'
    ) AS exists
  `);
  const hasIsLive = colCheck[0]?.exists === true;

  const liveFilter = hasIsLive
    ? `AND REPLACE(c.table_name, '_', ' ') IN (SELECT name FROM projects WHERE is_live = true)`
    : `AND c.table_name IN (
        'tand_f_rubriq_processing',
        'language_quality_score'
      )`;

  const { rows } = await pool.query<{ table_name: string }>(`
    SELECT c.table_name
    FROM information_schema.columns c
    -- must have project_name column
    WHERE c.table_schema = 'public'
      AND c.column_name = 'project_name'
      -- exclude system / non-project tables
      AND c.table_name NOT IN (
        'alert_rules', 'alert_history', 'users', 'projects',
        'saved_filters', 'retention_policies', 'parse_errors',
        'audit_log', 'break_groups', 'breaks', 'error_solutions',
        'Image_Forensics'
      )
      -- must have error_status column
      AND c.table_name IN (
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'error_status'
      )
      -- must have error_hash column
      AND c.table_name IN (
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'error_hash'
      )
      -- *** LIVE PROJECTS ONLY ***
      ${liveFilter}
    ORDER BY c.table_name
  `);
  return rows.map((r) => r.table_name);
}

/**
 * Builds a UNION ALL query across all project tables selecting
 * project_name, file_name, error, timestamp — only active (non-resolved) errors.
 * Normalizes project_name: underscores → spaces so duplicate tables merge cleanly.
 */
function buildErrorUnion(tables: string[], extraWhere = ''): string {
  const parts = tables.map(
    (t) => `SELECT REPLACE(project_name, '_', ' ') AS project_name, file_name, error, error_detail, error_hash, timestamp, reopened_at, COALESCE(error_group_name, '') AS error_group_name, COALESCE(error_group_id, '') AS error_group_id FROM "${t}" WHERE error IS NOT NULL AND error <> '' AND error_status IN ('open', 'reopened')${extraWhere}`,
  );
  return parts.join('\n UNION ALL\n');
}

function buildErrorCountUnion(tables: string[], extraWhere = ''): string {
  const parts = tables.map(
    (t) => `SELECT REPLACE(project_name, '_', ' ') AS project_name, COUNT(*) AS cnt FROM "${t}" WHERE error IS NOT NULL AND error <> '' AND error_status IN ('open', 'reopened')${extraWhere} GROUP BY project_name`,
  );
  return parts.join('\n UNION ALL\n');
}

export function buildDateRangeWhere(from?: string, to?: string): string {
  let where = '';
  if (from) {
    where += ` AND timestamp >= '${from.replace(/'/g, "''")}'`;
  }
  if (to) {
    where += ` AND timestamp <= '${to.replace(/'/g, "''")}'`;
  }
  return where;
}

/**
 * Builds a UNION ALL query across all project tables selecting
 * project_name and COUNT(*) — for total usage (filtered by optional date range).
 * Normalizes project_name: underscores → spaces.
 */
function buildTotalUnion(tables: string[], extraWhere = ''): string {
  const parts = tables.map(
    (t) => `SELECT REPLACE(project_name, '_', ' ') AS project_name, COUNT(*) AS cnt FROM "${t}" WHERE 1=1${extraWhere} GROUP BY project_name`,
  );
  return parts.join('\n UNION ALL\n');
}

// ─── Router factory ───────────────────────────────────────────────────────────

export function createGetErrorDetailHandler(pool: Pool) {
  return async (req: any, res: any) => {
    try {
      const errorHash = String(req.params?.errorHash ?? '').trim();
      const projectName = req.query?.project_name ? String(req.query.project_name) : undefined;

      if (!errorHash) {
        return res.status(400).json({ error: 'errorHash is required' });
      }

      const tables = await getProjectTables(pool);
      const filteredTables = projectName
        ? tables.filter((table) => {
          const normalizedProject = projectName.toLowerCase();
          const normalizedTable = table.toLowerCase();
          return normalizedTable === normalizedProject.replace(/ /g, '_') || normalizedTable.replace(/_/g, ' ') === normalizedProject;
        })
        : tables;

      if (filteredTables.length === 0) {
        return res.status(404).json({ error: 'Not Found', message: 'Error detail not found.' });
      }

      for (const table of filteredTables) {
        const { rows } = await pool.query(`
          SELECT
            REPLACE(project_name, '_', ' ') AS project_name,
            file_name,
            error AS error_message,
            error_detail,
            COALESCE(error_hash, MD5(COALESCE(error_detail, error))) AS error_hash,
            COALESCE(failure_count, 1)::int AS occurrence_count,
            timestamp AS first_seen,
            timestamp AS last_seen,
            CASE
              WHEN error_status = 'reopened' THEN 'regression'
              WHEN COALESCE(failure_count, 1) <= 1 THEN 'new'
              ELSE 'existing'
            END AS status,
            error_status
          FROM "${table}"
          WHERE error_hash = $1
             OR COALESCE(error_hash, MD5(COALESCE(error_detail, error))) = $1
          ORDER BY timestamp DESC
          LIMIT 1
        `, [errorHash]);

        if (rows[0]) {
          const row = rows[0];
          const occurrenceCount = row.occurrence_count ?? row.failure_count ?? 1;
          const derivedStatus = row.status ?? (row.error_status === 'reopened' ? 'regression' : (occurrenceCount > 1 ? 'existing' : 'new'));
          return res.json({
            project_name: row.project_name,
            file_name: row.file_name,
            error_message: row.error_message,
            error_detail: row.error_detail,
            error_hash: row.error_hash,
            occurrence_count: occurrenceCount,
            first_seen: row.first_seen,
            last_seen: row.last_seen,
            status: derivedStatus,
            error_status: row.error_status,
            occurrences: [{ file_name: row.file_name, timestamp: row.first_seen, failure_count: occurrenceCount }],
            solution: null,
            ai_recommendation: null,
          });
        }
      }

      return res.status(404).json({ error: 'Not Found', message: 'Error detail not found.' });
    } catch (err) {
      console.error('[Breaks] error detail lookup failed:', err);
      return res.status(500).json({ error: 'Internal server error' });
    }
  };
}

export function createProjectDashboardRouter(pool: Pool) {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const express = require('express');
  const router = express.Router();

export function createTopProjectsHandler(pool: Pool) {
  return async (req: any, res: any) => {
    try {
      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ projects: [] });

      const { from, to } = req.query as Record<string, string | undefined>;
      const extraWhere = buildDateRangeWhere(from, to);
      const union = buildTotalUnion(tables, extraWhere);
      const { rows } = await pool.query(`
        SELECT project_name, SUM(cnt)::int AS total
        FROM (${union}) AS combined
        GROUP BY project_name
        ORDER BY total DESC
        LIMIT 10
      `);
      res.json({ projects: rows });
    } catch (err) {
      console.error('[Dashboard] top-projects error:', (err as any).message ?? err);
      res.status(500).json({ error: 'Internal server error', detail: (err as any).message });
    }
  };
}

export function createTopErrorProjectsHandler(pool: Pool) {
  return async (req: any, res: any) => {
    try {
      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ projects: [] });

      const { from, to } = req.query as Record<string, string | undefined>;
      const extraWhere = buildDateRangeWhere(from, to);
      const union = buildErrorCountUnion(tables, extraWhere);

      const { rows } = await pool.query(`
        SELECT project_name, SUM(cnt)::int AS total
        FROM (${union}) AS combined
        GROUP BY project_name
        HAVING SUM(cnt) > 0
        ORDER BY total DESC
        LIMIT 10
      `);
      res.json({ projects: rows });
    } catch (err) {
      console.error('[Dashboard] top-error-projects error:', (err as any).message ?? err);
      res.status(500).json({ error: 'Internal server error', detail: (err as any).message });
    }
  };
}

  // GET /today-errors — all errors where timestamp is today (UTC)
  router.get('/today-errors', async (_req: any, res: any) => {
    try {
      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ date: new Date().toISOString().slice(0, 10), errors: [] });

      const todayWhere = ` AND (
        (timestamp AT TIME ZONE 'UTC' >= CURRENT_DATE AND timestamp AT TIME ZONE 'UTC' < CURRENT_DATE + INTERVAL '1 day')
        OR
        (reopened_at IS NOT NULL AND reopened_at AT TIME ZONE 'UTC' >= CURRENT_DATE AND reopened_at AT TIME ZONE 'UTC' < CURRENT_DATE + INTERVAL '1 day')
      )`;
      const union = buildErrorUnion(tables, todayWhere);

      const { rows } = await pool.query(`
        SELECT project_name AS project, file_name, error, error_detail, error_hash, timestamp AS timestamp,
               NULLIF(error_group_name, '') AS error_group_name,
               NULLIF(error_group_id, '') AS error_group_id
        FROM (${union}) AS combined
        ORDER BY timestamp DESC
      `);

      const date = new Date().toISOString().slice(0, 10);
      res.json({ date, errors: rows });
    } catch (err) {
      console.error('[Dashboard] today-errors error:', (err as any).message ?? err);
      res.status(500).json({ error: 'Internal server error', detail: (err as any).message });
    }
  });

  router.get('/detail/:errorHash', createGetErrorDetailHandler(pool));

  // GET /errors?from=ISO&to=ISO — errors in date range (or all if no params)
  router.get('/errors', async (req: any, res: any) => {

    try {
      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ errors: [] });

      const { from, to } = req.query as Record<string, string | undefined>;

      let extraWhere = '';
      const values: string[] = [];

      if (from) {
        values.push(from);
        extraWhere += ` AND timestamp >= '${from.replace(/'/g, "''")}'`;
      }
      if (to) {
        extraWhere += ` AND timestamp <= '${to.replace(/'/g, "''")}'`;
      }

      const union = buildErrorUnion(tables, extraWhere);

      const { rows } = await pool.query(`
        SELECT project_name AS project, file_name, error, error_detail, error_hash, timestamp,
               NULLIF(error_group_name, '') AS error_group_name,
               NULLIF(error_group_id, '') AS error_group_id
        FROM (${union}) AS combined
        ORDER BY timestamp DESC
        LIMIT 2000
      `);

      res.json({ errors: rows });
    } catch (err) {
      console.error('[Dashboard] errors error:', (err as any).message ?? err);
      res.status(500).json({ error: 'Internal server error', detail: (err as any).message });
    }
  });

  // GET /project-errors?project=NAME&from=ISO&to=ISO — errors for a specific project in date range
  router.get('/project-errors', async (req: any, res: any) => {
    try {
      const { project, from, to } = req.query as Record<string, string | undefined>;

      if (!project) {
        return res.status(400).json({ error: 'project query parameter is required' });
      }

      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ errors: [] });

      // Filter to only the tables matching this project
      const projectTableName = project.toLowerCase().replace(/ /g, '_');
      const matchingTables = tables.filter(t =>
        t.toLowerCase() === projectTableName ||
        t.toLowerCase().replace(/_/g, ' ') === project.toLowerCase()
      );

      if (matchingTables.length === 0) {
        return res.json({ errors: [] });
      }

      let extraWhere = '';
      if (from) {
        extraWhere += ` AND timestamp >= '${from.replace(/'/g, "''")}'`;
      }
      if (to) {
        extraWhere += ` AND timestamp <= '${to.replace(/'/g, "''")}'`;
      }

      const union = buildErrorUnion(matchingTables, extraWhere);

      const { rows } = await pool.query(`
        SELECT project_name AS project, file_name, error, error_detail, error_hash, timestamp,
               NULLIF(error_group_name, '') AS error_group_name,
               NULLIF(error_group_id, '') AS error_group_id
        FROM (${union}) AS combined
        ORDER BY timestamp DESC
        LIMIT 2000
      `);

      res.json({ errors: rows });
    } catch (err) {
      console.error('[Dashboard] project-errors error:', (err as any).message ?? err);
      res.status(500).json({ error: 'Internal server error', detail: (err as any).message });
    }
  });

  // GET /grouped?page=1&limit=20&status=&from=ISO&to=ISO
  // Groups errors by (project_name, error_hash) across all project tables.
  // Supports optional date range and status filter (new / existing / regression).
  router.get('/grouped', async (req: any, res: any) => {
    try {
      const tables = await getProjectTables(pool);
      if (tables.length === 0) return res.json({ data: [], total: 0, page: 1, limit: 20 });

      const page = Math.max(1, parseInt(req.query.page ?? '1', 10) || 1);
      const limit = Math.min(100, Math.max(1, parseInt(req.query.limit ?? '20', 10) || 20));
      const statusFilter: string = req.query.status ?? '';
      const projectFilter: string = req.query.project ?? '';
      const from: string = req.query.from ?? '';
      const to: string = req.query.to ?? '';

      // Build date-range clause (safe — values are ISO strings, not user SQL)
      let dateWhere = '';
      if (from) dateWhere += ` AND timestamp >= '${from.replace(/'/g, "''")}'`;
      if (to) dateWhere += ` AND timestamp <= '${to.replace(/'/g, "''")}'`;

      // Include resolved cases in the grouped list as well so the UI can show
      // a proper resolved badge after a user marks an error as fixed.
      const filteredTables = projectFilter
        ? tables.filter(t => t.toLowerCase() === projectFilter.toLowerCase().replace(/ /g, '_') ||
          t.toLowerCase().replace(/_/g, ' ') === projectFilter.toLowerCase())
        : tables;

      if (filteredTables.length === 0) return res.json({ data: [], total: 0, page, limit });

      const unionParts = filteredTables.map(
        (t) => `SELECT REPLACE(project_name, '_', ' ') AS project_name, error, error_detail, error_hash, failure_count, timestamp, error_status, reopened_at, resolved_at FROM "${t}" WHERE error IS NOT NULL AND error <> '' AND error_status IN ('open', 'reopened', 'resolved')${dateWhere}`,
      );
      const union = unionParts.join('\nUNION ALL\n');

      // Group by project + error_hash, compute occurrence counts and first/last seen.
      // Resolved items are carried through with an explicit resolved status flag so
      // the frontend can render a resolved badge instead of an old open/reopened state.
      const grouped = `
        SELECT
          project_name,
          error                                        AS error_message,
          COALESCE(error_hash, MD5(LOWER(TRIM(error)))) AS error_hash,
          SUM(failure_count)::int                      AS occurrence_count,
          MIN(timestamp)                               AS first_seen,
          COALESCE(MAX(reopened_at), MAX(timestamp))   AS last_seen,
          CASE
            WHEN BOOL_OR(error_status = 'resolved') THEN 'resolved'
            WHEN BOOL_OR(error_status = 'reopened') THEN 'regression'
            WHEN SUM(failure_count) = 1 THEN 'new'
            ELSE 'existing'
          END AS status
        FROM (${union}) AS all_errors
        GROUP BY project_name, error, COALESCE(error_hash, MD5(LOWER(TRIM(error))))
      `;

      // Apply optional status and project filters
      const conditions: string[] = [];
      if (statusFilter) conditions.push(`status = '${statusFilter.replace(/'/g, "''")}'`);
      if (projectFilter) conditions.push(`project_name = '${projectFilter.replace(/'/g, "''")}'`);
      const statusWhere = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
      const countRes = await pool.query(`SELECT COUNT(*) FROM (${grouped}) AS g ${statusWhere}`);
      const total = parseInt(countRes.rows[0].count, 10);

      const offset = (page - 1) * limit;
      const dataRes = await pool.query(`
        SELECT * FROM (${grouped}) AS g
        ${statusWhere}
        ORDER BY last_seen DESC NULLS LAST
        LIMIT ${limit} OFFSET ${offset}
      `);

      res.json({ data: dataRes.rows, total, page, limit });
    } catch (err) {
      console.error('[Breaks] grouped error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  return router;
}


/**
 * Upsert logic for per-project error tracking.
 *
 * POST /api/projects/:name/errors
 * Body: { file_name, error, error_hash?, ...other columns }
 *
 * Rules:
 *  - No existing row with this error_hash → INSERT with failure_count=1, error_status='open'
 *  - Existing row with error_status='resolved' → UPDATE to 'reopened', increment failure_count, set reopened_at=NOW(), clear resolved_at
 *  - Existing row with error_status='open' or 'reopened' → do NOT increment failure_count, just update timestamp
 */
export function createProjectErrorUpsertRouter(pool: Pool) {
  const express = require('express');
  const router = express.Router();

  // ── Teams webhook helper ──────────────────────────────────────────────────
  // Uses shared teamsNotifier — direct Teams Incoming Webhook

  function fireTeamsAlert(projectName: string, shortError: string, errorDetail: string | undefined): void {
    sendTeamsAlert({
      ruleName: 'Error Upsert',
      alertType: 'New Error',
      projectName,
      errorMsg: shortError,
      errorDetail,
    }).catch(() => { });
  }

  router.post('/:name/errors', async (req: any, res: any) => {
    try {
      const projectName: string = decodeURIComponent(req.params.name);
      const tableNameRaw = projectName.replace(/ /g, '_');

      // Case-insensitive lookup for Aurora DSQL (stores names in lowercase)
      const { rows: tableCheck } = await pool.query(
        'SELECT table_name FROM information_schema.tables WHERE table_schema = $1 AND LOWER(table_name) = LOWER($2)',
        ['public', tableNameRaw],
      );
      if (tableCheck.length === 0) {
        return res.status(404).json({ error: 'No table found for project: ' + projectName });
      }
      const tableName: string = tableCheck[0].table_name;

      // Only send Teams alerts for live projects
      // (graceful fallback if projects registry doesn't exist in Aurora DSQL)
      let isLive = false;
      try {
        const { rows: liveCheck } = await pool.query(
          'SELECT is_live FROM projects WHERE name = $1',
          [projectName],
        );
        isLive = liveCheck[0]?.is_live === true;
      } catch {
        // projects table doesn't exist — treat all as non-live (no Teams alert)
        isLive = false;
      }

      const body = req.body as Record<string, unknown>;
      const fileName: string = String(body.file_name ?? '');
      const errorDetail: string | undefined = (body.error_detail as string | undefined)?.trim() || undefined;

      // Derive short error from error_detail (last line before first colon)
      // If no error_detail, fall back to the 'error' field
      let shortError = String(body.error ?? '').trim();
      if (errorDetail) {
        const lines = errorDetail.split('\n').map((l: string) => l.trim()).filter(Boolean);
        const lastLine = lines[lines.length - 1] ?? '';
        const derived = lastLine.split(':')[0].trim();
        if (derived) shortError = derived;
      }

      if (!shortError) return res.status(400).json({ error: 'error or error_detail is required' });

      const hashSource = shortError.toLowerCase().trim();
      const errorHash: string = require('crypto').createHash('md5').update(hashSource).digest('hex');

      const updateResult = await pool.query(
        'UPDATE "' + tableName + '" SET failure_count = failure_count + 1, file_name = $2, timestamp = NOW(), ' +
        'error_detail = COALESCE($5, error_detail), ' +
        'error_status = CASE WHEN error_status = $3 THEN $4 ELSE error_status END, ' +
        'reopened_at = CASE WHEN error_status = $3 THEN NOW() ELSE reopened_at END, ' +
        'resolved_at = CASE WHEN error_status = $3 THEN NULL ELSE resolved_at END ' +
        'WHERE error_hash = $1 RETURNING id, error_status, failure_count',
        [errorHash, fileName, 'resolved', 'reopened', errorDetail ?? null],
      );

      if (updateResult.rowCount && updateResult.rowCount > 0) {
        const r = updateResult.rows[0];
        if (isLive) fireTeamsAlert(projectName, shortError, errorDetail);
        return res.json({
          action: r.error_status === 'reopened' ? 'reopened' : 'updated',
          error_status: r.error_status,
          failure_count: r.failure_count,
        });
      }

      const insertResult = await pool.query(
        'INSERT INTO "' + tableName + '" (id, project_name, file_name, timestamp, success_count, failure_count, ' +
        'error, error_detail, error_hash, error_status) ' +
        'VALUES ($7, $1, $2, NOW(), 0, 1, $3, $4, $5, $6) ' +
        'RETURNING id, error_status, failure_count',
        [projectName, fileName, shortError, errorDetail ?? null, errorHash, 'open', require('crypto').randomUUID()],
      );

      const inserted = insertResult.rows[0];
      if (isLive) fireTeamsAlert(projectName, shortError, errorDetail);
      return res.json({ action: 'inserted', error_status: inserted.error_status, failure_count: inserted.failure_count });

    } catch (err) {
      console.error('[Projects] error upsert failed:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  router.patch('/:name/errors/:hash/resolve', async (req: any, res: any) => {
    try {
      const projectName: string = decodeURIComponent(req.params.name);
      const tableNameRaw = projectName.replace(/ /g, '_');
      const errorHash: string = req.params.hash;

      // Case-insensitive lookup for Aurora DSQL
      const { rows: tableCheck } = await pool.query(
        'SELECT table_name FROM information_schema.tables WHERE table_schema = $1 AND LOWER(table_name) = LOWER($2)',
        ['public', tableNameRaw],
      );
      if (tableCheck.length === 0) {
        return res.status(404).json({ error: 'No table found for project: ' + projectName });
      }
      const tableName: string = tableCheck[0].table_name;

      await pool.query(
        'UPDATE "' + tableName + '" SET error_status = $1, resolved_at = NOW(), reopened_at = NULL WHERE error_hash = $2',
        ['resolved', errorHash],
      );
      res.json({ action: 'resolved' });
    } catch (err) {
      console.error('[Projects] resolve error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  return router;
}


/**
 * Live-project management + test sample-error injection router.
 *
 * PATCH /api/projects/:name/live          — toggle is_live on/off
 * GET   /api/projects/live                — list all live projects
 * POST  /api/projects/:name/test-error    — inject a sample error for testing
 *        Body: { error?, error_detail?, file_name? }
 *        Only works when NODE_ENV !== 'production' OR query ?force=1
 *        Sends a real Teams alert so you can verify the channel end-to-end.
 */
export function createProjectLiveRouter(pool: Pool) {
  const express = require('express');
  const router = express.Router();

  // ── Teams webhook (shared helper) ─────────────────────────────────────────
  // Uses shared teamsNotifier — direct Teams Incoming Webhook

  function fireTeamsAlert(
    projectName: string,
    shortError: string,
    errorDetail: string | undefined,
    label = '',
  ): void {
    sendTeamsAlert({
      ruleName: label || 'Direct Alert',
      alertType: 'New Error',
      projectName,
      errorMsg: shortError,
      errorDetail,
      label,
    }).catch(() => { });
  }

  // ── GET /api/projects/live — list live projects ───────────────────────────

  router.get('/live', async (_req: any, res: any) => {
    try {
      // Check if the projects registry exists first (may not exist in Aurora DSQL)
      const { rows: tableExists } = await pool.query(
        `SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'projects' LIMIT 1`,
      );
      if (tableExists.length === 0) {
        // No projects table — return all discovered project tables as "live"
        return res.json([]);
      }
      const { rows } = await pool.query(
        'SELECT id, name, category, is_live FROM projects WHERE is_live = true ORDER BY name',
      );
      res.json(rows);
    } catch (err) {
      console.error('[Projects] live list error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // ── PATCH /api/projects/:name/live — toggle is_live ───────────────────────

  router.patch('/:name/live', async (req: any, res: any) => {
    try {
      const projectName: string = decodeURIComponent(req.params.name);
      const { is_live } = req.body as { is_live: boolean };

      if (typeof is_live !== 'boolean') {
        return res.status(400).json({ error: 'Body must contain { is_live: true | false }' });
      }

      // Check if projects table exists
      const { rows: tableExists } = await pool.query(
        `SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'projects' LIMIT 1`,
      );
      if (tableExists.length === 0) {
        return res.status(404).json({ error: 'projects registry table not found in this database' });
      }

      const { rows } = await pool.query(
        'UPDATE projects SET is_live = $1 WHERE name = $2 RETURNING id, name, category, is_live',
        [is_live, projectName],
      );

      if (rows.length === 0) {
        return res.status(404).json({ error: 'Project not found: ' + projectName });
      }

      console.log(`[Projects] ${projectName} is_live → ${is_live}`);
      res.json(rows[0]);
    } catch (err) {
      console.error('[Projects] live toggle error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // ── POST /api/projects/:name/test-error — inject sample error ────────────
  //
  // Inserts a sample error row into the project table AND fires a Teams alert
  // so you can verify the full pipeline (dashboard + Teams) end-to-end.
  //
  // Blocked in production unless ?force=1 is passed.

  const SAMPLE_ERRORS = [
    {
      error: 'RuntimeError: Model inference failed — CUDA out of memory',
      error_detail: 'Traceback (most recent call last):\n  File "run.py", line 42, in infer\n    output = model(input_tensor)\nRuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB',
      file_name: 'sample_batch_001.pdf',
    },
    {
      error: 'ValueError: Input tensor shape mismatch',
      error_detail: 'Traceback (most recent call last):\n  File "preprocess.py", line 18, in transform\n    x = reshape(data, (batch, 512))\nValueError: cannot reshape array of size 1024 into shape (2,512)',
      file_name: 'sample_doc_002.docx',
    },
    {
      error: 'TimeoutError: LLM API request timed out after 30s',
      error_detail: 'requests.exceptions.Timeout: HTTPSConnectionPool(host="api.openai.com", port=443): Read timed out. (read timeout=30)',
      file_name: 'sample_file_003.xml',
    },
  ];

  router.post('/:name/test-error', async (req: any, res: any) => {
    try {
      const isProduction = process.env.NODE_ENV === 'production';
      const force = req.query.force === '1';

      if (isProduction && !force) {
        return res.status(403).json({
          error: 'Test error injection is disabled in production. Pass ?force=1 to override.',
        });
      }

      const projectName: string = decodeURIComponent(req.params.name);
      const tableNameRaw = projectName.replace(/ /g, '_');

      // Case-insensitive lookup for Aurora DSQL
      const { rows: tableCheck } = await pool.query(
        'SELECT table_name FROM information_schema.tables WHERE table_schema = $1 AND LOWER(table_name) = LOWER($2)',
        ['public', tableNameRaw],
      );
      if (tableCheck.length === 0) {
        return res.status(404).json({ error: 'No table found for project: ' + projectName });
      }
      const tableName: string = tableCheck[0].table_name;

      // Pick sample or use body override
      const body = req.body as Record<string, string | undefined>;
      const sampleIndex = Math.floor(Math.random() * SAMPLE_ERRORS.length);
      const sample = SAMPLE_ERRORS[sampleIndex];

      const errorDetail: string = (body.error_detail ?? sample.error_detail).trim();
      const fileName: string = body.file_name ?? sample.file_name;

      // Derive short error from last line of detail
      const lines = errorDetail.split('\n').map((l) => l.trim()).filter(Boolean);
      const lastLine = lines[lines.length - 1] ?? '';
      const shortError: string = body.error ?? (lastLine.split(':')[0].trim() || sample.error);

      const crypto = require('crypto');
      const errorHash: string = crypto.createHash('md5').update(shortError.toLowerCase().trim()).digest('hex');

      // Upsert into project table
      const updateResult = await pool.query(
        `UPDATE "${tableName}"
         SET failure_count = failure_count + 1,
             file_name     = $2,
             timestamp     = NOW(),
             error_detail  = $3,
             error_status  = CASE WHEN error_status = 'resolved' THEN 'reopened' ELSE error_status END,
             reopened_at   = CASE WHEN error_status = 'resolved' THEN NOW() ELSE reopened_at END,
             resolved_at   = CASE WHEN error_status = 'resolved' THEN NULL ELSE resolved_at END
         WHERE error_hash = $1
         RETURNING id, error_status, failure_count`,
        [errorHash, fileName, errorDetail],
      );

      let action: string;
      let errorStatus: string;
      let failureCount: number;

      if (updateResult.rowCount && updateResult.rowCount > 0) {
        const r = updateResult.rows[0];
        action = r.error_status === 'reopened' ? 'reopened' : 'updated';
        errorStatus = r.error_status;
        failureCount = r.failure_count;
      } else {
        const insertResult = await pool.query(
          `INSERT INTO "${tableName}"
             (id, project_name, file_name, timestamp, success_count, failure_count,
              error, error_detail, error_hash, error_status)
           VALUES ($6, $1, $2, NOW(), 0, 1, $3, $4, $5, 'open')
           RETURNING id, error_status, failure_count`,
          [projectName, fileName, shortError, errorDetail, errorHash, require('crypto').randomUUID()],
        );
        const r = insertResult.rows[0];
        action = 'inserted';
        errorStatus = r.error_status;
        failureCount = r.failure_count;
      }

      // Always fire Teams alert for test errors (so you can verify the channel)
      await sendTeamsAlert({
        ruleName: 'Sample Error',
        alertType: 'New Error',
        projectName,
        errorMsg: shortError,
        errorDetail,
        label: 'Sample Error',
      });

      console.log(`[TestError] injected into "${projectName}": ${shortError}`);

      res.json({
        action,
        project: projectName,
        error: shortError,
        error_status: errorStatus,
        failure_count: failureCount,
        teams_alert_sent: true,
      });
    } catch (err) {
      console.error('[Projects] test-error injection failed:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  return router;
}
