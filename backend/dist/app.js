"use strict";
/**
 * Express application factory — shared between the local dev server (index.ts)
 * and the Lambda handler (lambda.ts).
 *
 * Exports `app` so serverless-http can wrap it, and `buildApp` for testing.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.app = void 0;
require("dotenv/config");
const logPipeline_1 = require("./pipeline/logPipeline");
const airbrakeClient_1 = require("./airbrake/airbrakeClient");
const client_1 = require("./db/client");
const ingestRouter_1 = require("./api/ingestRouter");
const errorIngestRouter_1 = require("./api/errorIngestRouter");
const projectDashboardRouter_1 = require("./api/projectDashboardRouter");
const alertManagementRouter_1 = require("./api/alertManagementRouter");
const errorSolutionRouter_1 = require("./api/errorSolutionRouter");
const jiraRouter_1 = require("./api/jiraRouter");
const teamsNotifier_1 = require("./alerts/teamsNotifier");
const logsRouter_1 = require("./api/logsRouter");
const breaksRouter_1 = require("./api/breaksRouter");
const dashboardRouter_1 = require("./api/dashboardRouter");
const alertsRouter_1 = require("./api/alertsRouter");
const filtersRouter_1 = require("./api/filtersRouter");
const adminRouter_1 = require("./api/adminRouter");
const rbac_1 = require("./auth/rbac");
const errorAggregator_1 = require("./aggregator/errorAggregator");
// ─── Stub adapters ────────────────────────────────────────────────────────────
const redisPublisher = {
    publish: async (channel, message) => {
        console.log(`[Redis] publish ${channel}: ${message.slice(0, 80)}…`);
    },
};
const logRecordRepository = {
    save: async (record) => {
        console.log('[PG] save log record', record.id);
    },
};
const logSearchIndexer = {
    indexLogRecord: async (record) => {
        console.log('[ES] index log record', record.id);
    },
};
const parseErrorRepository = {
    save: async (_rawPayload, errorMessage) => {
        console.error('[PG] parse error:', errorMessage);
    },
    write: async (_rawPayload, errorMessage) => {
        console.error('[PG] parse error:', errorMessage);
    },
};
const httpClient = {
    get: async (_url, _headers) => ({ groups: [] }),
};
// ─── Service instantiation ────────────────────────────────────────────────────
const logPipeline = (0, logPipeline_1.createLogPipeline)(logRecordRepository, logSearchIndexer, redisPublisher, parseErrorRepository);
// AirbrakeClient, AlertEngine, PurgeJob exist for completeness; they are no-ops
// in the Lambda execution context (no setInterval / background threads).
new airbrakeClient_1.AirbrakeClient({
    apiKey: process.env.AIRBRAKE_API_KEY ?? 'placeholder',
    projectId: process.env.AIRBRAKE_PROJECT_ID ?? 'placeholder',
    pollIntervalMs: parseInt(process.env.AIRBRAKE_POLL_INTERVAL ?? '30000', 10),
}, httpClient, redisPublisher);
const breakGroupRepository = {
    findByFingerprint: async (_fp) => null,
    save: async (group) => group,
    update: async (group) => group,
};
const aggBreakRepository = { save: async (_b) => { } };
const searchIndexer = {
    indexBreak: async (_b) => { },
    indexBreakGroup: async (_g) => { },
};
const errorAggregator = new errorAggregator_1.DefaultErrorAggregator(breakGroupRepository, aggBreakRepository, searchIndexer);
// ─── Session store — honours dev tokens from LoginPage.tsx ───────────────────
//
// LoginPage writes "dev-token-admin" / "dev-token-developer" / "dev-token-viewer"
// to localStorage. apiFetch sends it as  Authorization: Bearer <token>.
// The RBAC middleware calls sessionStore.get(token) and checks the role.
// This stub resolves those tokens so every RBAC-protected route works.
const sessionStore = {
    get: async (token) => {
        if (token === 'dev-token-admin')
            return { userId: 'dev-admin', role: 'admin', createdAt: new Date(), expiresAt: new Date(Date.now() + 86400000) };
        if (token === 'dev-token-developer')
            return { userId: 'dev-developer', role: 'developer', createdAt: new Date(), expiresAt: new Date(Date.now() + 86400000) };
        if (token === 'dev-token-viewer')
            return { userId: 'dev-viewer', role: 'viewer', createdAt: new Date(), expiresAt: new Date(Date.now() + 86400000) };
        return null;
    },
    set: async () => { },
    delete: async () => { },
};
const auditLogRepo = { log: async () => { } };
// ─── DB-backed repositories ───────────────────────────────────────────────────
const userRepository = {
    findAll: async () => {
        try {
            const { rows } = await client_1.pool.query('SELECT * FROM users ORDER BY created_at DESC');
            return rows;
        }
        catch (err) {
            console.warn('[Users] findAll failed (table may not exist):', err.message);
            return [];
        }
    },
    create: async (user) => {
        const { rows } = await client_1.pool.query('INSERT INTO users (email, role, oauth_provider, oauth_subject) VALUES ($1, $2, $3, $4) RETURNING *', [user.email, user.role, user.oauthProvider, user.oauthSubject]);
        return rows[0];
    },
    update: async (id, user) => {
        const fields = Object.entries(user).map(([k], i) => `${k} = $${i + 2}`).join(', ');
        const { rows } = await client_1.pool.query(`UPDATE users SET ${fields} WHERE id = $1 RETURNING *`, [id, ...Object.values(user)]);
        return rows[0] ?? null;
    },
    delete: async (id) => {
        const { rowCount } = await client_1.pool.query('DELETE FROM users WHERE id = $1', [id]);
        return (rowCount ?? 0) > 0;
    },
};
const retentionPolicyRepository = {
    findAll: async () => {
        try {
            const { rows } = await client_1.pool.query('SELECT * FROM retention_policies');
            return rows;
        }
        catch (err) {
            console.warn('[Retention] findAll failed (table may not exist):', err.message);
            return [];
        }
    },
    upsert: async (policy) => {
        const { rows } = await client_1.pool.query(`INSERT INTO retention_policies (application_id, retention_days)
       VALUES ($1, $2)
       ON CONFLICT (application_id) DO UPDATE SET retention_days = EXCLUDED.retention_days
       RETURNING *`, [policy.applicationId, policy.retentionDays]);
        return rows[0];
    },
};
const alertRuleRepository = {
    create: async (rule) => {
        const { rows } = await client_1.pool.query(`INSERT INTO alert_rules (name, threshold, window_seconds, trigger_on_new_error, channels, created_by, enabled)
       VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *`, [rule.name, rule.threshold, rule.windowSeconds, rule.triggerOnNewError,
            JSON.stringify(rule.channels), rule.createdBy, rule.enabled ?? true]);
        return rows[0];
    },
    findAll: async () => {
        const { rows } = await client_1.pool.query('SELECT * FROM alert_rules ORDER BY created_at DESC');
        return rows;
    },
    findById: async (id) => {
        const { rows } = await client_1.pool.query('SELECT * FROM alert_rules WHERE id = $1', [id]);
        return rows[0] ?? null;
    },
    update: async (id, rule) => {
        const fields = Object.entries(rule).map(([k], i) => `${k} = $${i + 2}`).join(', ');
        const { rows } = await client_1.pool.query(`UPDATE alert_rules SET ${fields} WHERE id = $1 RETURNING *`, [id, ...Object.values(rule)]);
        return rows[0] ?? null;
    },
    delete: async (id) => {
        const { rowCount } = await client_1.pool.query('DELETE FROM alert_rules WHERE id = $1', [id]);
        return (rowCount ?? 0) > 0;
    },
};
const savedFilterRepository = {
    create: async (filter) => {
        const { rows } = await client_1.pool.query('INSERT INTO saved_filters (user_id, name, criteria) VALUES ($1, $2, $3) RETURNING *', [filter.userId, filter.name, JSON.stringify(filter.criteria)]);
        return rows[0];
    },
    findById: async (id) => {
        const { rows } = await client_1.pool.query('SELECT * FROM saved_filters WHERE id = $1', [id]);
        return rows[0] ?? null;
    },
    update: async (id, filter) => {
        const fields = Object.entries(filter).map(([k], i) => `${k} = $${i + 2}`).join(', ');
        const { rows } = await client_1.pool.query(`UPDATE saved_filters SET ${fields} WHERE id = $1 RETURNING *`, [id, ...Object.values(filter)]);
        return rows[0] ?? null;
    },
    delete: async (id) => {
        const { rowCount } = await client_1.pool.query('DELETE FROM saved_filters WHERE id = $1', [id]);
        return (rowCount ?? 0) > 0;
    },
};
const logSearchRepository = {
    search: async (filters) => {
        const conds = [];
        const vals = [];
        let i = 1;
        if (filters.keyword) {
            conds.push(`message ILIKE $${i++}`);
            vals.push(`%${filters.keyword}%`);
        }
        if (filters.severity) {
            conds.push(`severity = $${i++}`);
            vals.push(filters.severity);
        }
        if (filters.applicationId) {
            conds.push(`application_id = $${i++}`);
            vals.push(filters.applicationId);
        }
        if (filters.environment) {
            conds.push(`environment = $${i++}`);
            vals.push(filters.environment);
        }
        if (filters.from) {
            conds.push(`timestamp >= $${i++}`);
            vals.push(filters.from);
        }
        if (filters.to) {
            conds.push(`timestamp <= $${i++}`);
            vals.push(filters.to);
        }
        const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
        const offset = (filters.page - 1) * filters.limit;
        const [d, c] = await Promise.all([
            client_1.pool.query(`SELECT * FROM logs ${where} ORDER BY timestamp DESC LIMIT $${i} OFFSET $${i + 1}`, [...vals, filters.limit, offset]),
            client_1.pool.query(`SELECT COUNT(*) FROM logs ${where}`, vals),
        ]);
        return { data: d.rows, total: parseInt(c.rows[0].count, 10) };
    },
    searchAll: async (filters) => {
        const conds = [];
        const vals = [];
        let i = 1;
        if (filters.keyword) {
            conds.push(`message ILIKE $${i++}`);
            vals.push(`%${filters.keyword}%`);
        }
        if (filters.severity) {
            conds.push(`severity = $${i++}`);
            vals.push(filters.severity);
        }
        if (filters.applicationId) {
            conds.push(`application_id = $${i++}`);
            vals.push(filters.applicationId);
        }
        if (filters.environment) {
            conds.push(`environment = $${i++}`);
            vals.push(filters.environment);
        }
        if (filters.from) {
            conds.push(`timestamp >= $${i++}`);
            vals.push(filters.from);
        }
        if (filters.to) {
            conds.push(`timestamp <= $${i++}`);
            vals.push(filters.to);
        }
        const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
        const { rows } = await client_1.pool.query(`SELECT * FROM logs ${where} ORDER BY timestamp DESC`, vals);
        return rows;
    },
};
const breakExportRepository = {
    exportAll: async (filters) => {
        const conds = [];
        const vals = [];
        let i = 1;
        if (filters.severity) {
            conds.push(`severity = $${i++}`);
            vals.push(filters.severity);
        }
        if (filters.applicationId) {
            conds.push(`application_id = $${i++}`);
            vals.push(filters.applicationId);
        }
        if (filters.from) {
            conds.push(`timestamp >= $${i++}`);
            vals.push(filters.from);
        }
        if (filters.to) {
            conds.push(`timestamp <= $${i++}`);
            vals.push(filters.to);
        }
        const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
        const { rows } = await client_1.pool.query(`SELECT * FROM breaks ${where} ORDER BY timestamp DESC`, vals);
        return rows;
    },
};
const breakRepository = {
    findAll: async (filters) => {
        const conds = [];
        const vals = [];
        let i = 1;
        if (filters.status) {
            conds.push(`status = $${i++}`);
            vals.push(filters.status);
        }
        if (filters.severity) {
            conds.push(`severity = $${i++}`);
            vals.push(filters.severity);
        }
        if (filters.applicationId) {
            conds.push(`application_id = $${i++}`);
            vals.push(filters.applicationId);
        }
        if (filters.from) {
            conds.push(`timestamp >= $${i++}`);
            vals.push(filters.from);
        }
        if (filters.to) {
            conds.push(`timestamp <= $${i++}`);
            vals.push(filters.to);
        }
        const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
        const offset = (filters.page - 1) * filters.limit;
        const [d, c] = await Promise.all([
            client_1.pool.query(`SELECT * FROM breaks ${where} ORDER BY timestamp DESC LIMIT $${i} OFFSET $${i + 1}`, [...vals, filters.limit, offset]),
            client_1.pool.query(`SELECT COUNT(*) FROM breaks ${where}`, vals),
        ]);
        return { data: d.rows, total: parseInt(c.rows[0].count, 10) };
    },
    findById: async (id) => {
        const { rows } = await client_1.pool.query('SELECT * FROM breaks WHERE id = $1', [id]);
        return rows[0] ?? null;
    },
};
const correlatedLogRepository = {
    findCorrelated: async (applicationId, from, to) => {
        const { rows } = await client_1.pool.query('SELECT * FROM logs WHERE application_id = $1 AND timestamp BETWEEN $2 AND $3 ORDER BY timestamp', [applicationId, from, to]);
        return rows;
    },
};
const dashboardRepository = {
    countBreaks: async (windowHours) => {
        const { rows } = await client_1.pool.query(`SELECT COUNT(*) FROM breaks WHERE timestamp >= NOW() - INTERVAL '${windowHours} hours'`);
        return parseInt(rows[0].count, 10);
    },
    getErrorRateTrend: async (windowHours) => {
        const { rows } = await client_1.pool.query(`SELECT date_trunc('hour', timestamp) AS timestamp, COUNT(*) AS count
       FROM breaks WHERE timestamp >= NOW() - INTERVAL '${windowHours} hours'
       GROUP BY 1 ORDER BY 1`);
        return rows.map((r) => ({ timestamp: r.timestamp, count: parseInt(r.count, 10) }));
    },
    getTopServices: async (limit) => {
        const { rows } = await client_1.pool.query(`SELECT application_id AS "applicationId", COUNT(*) AS count
       FROM breaks GROUP BY 1 ORDER BY 2 DESC LIMIT $1`, [limit]);
        return rows.map((r) => ({ applicationId: r.applicationId, count: parseInt(r.count, 10) }));
    },
    getTimeSeries: async (granularity, from, to) => {
        const trunc = granularity === 'daily' ? 'day' : 'hour';
        const { rows } = await client_1.pool.query(`SELECT date_trunc('${trunc}', timestamp) AS timestamp, COUNT(*) AS count
       FROM breaks WHERE timestamp BETWEEN $1 AND $2 GROUP BY 1 ORDER BY 1`, [from, to]);
        return rows.map((r) => ({ timestamp: r.timestamp, count: parseInt(r.count, 10) }));
    },
    getSeverityBreakdown: async () => {
        const { rows } = await client_1.pool.query('SELECT severity, COUNT(*) AS count FROM breaks GROUP BY severity');
        return Object.fromEntries(rows.map((r) => [r.severity, parseInt(r.count, 10)]));
    },
};
// ─── Express app ──────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-var-requires
const express = require('express');
// eslint-disable-next-line @typescript-eslint/no-var-requires
const swaggerUi = require('swagger-ui-express');
const swagger_1 = require("./api/swagger");
exports.app = express();
exports.app.use(express.json({ limit: '10mb' }));
// ── CORS — must come before all routes ────────────────────────────────────────
// Explicitly allows:
//   1. http://airbrake.s3-website-us-east-1.amazonaws.com  (production S3 frontend)
//   2. http://localhost:3000                                (local Vite dev server)
//   3. Any other origin via wildcard fallback
const ALLOWED_ORIGINS = new Set([
    'http://airbrake.s3-website-us-east-1.amazonaws.com',
    'http://localhost:3000',
    'http://localhost:3001',
]);
exports.app.use((req, res, next) => {
    const origin = req.headers['origin'] ?? '';
    // If the request origin is in our explicit list, reflect it exactly.
    // Otherwise fall back to * so the API is still usable from curl / Postman.
    const allowOrigin = ALLOWED_ORIGINS.has(origin) ? origin : '*';
    res.setHeader('Access-Control-Allow-Origin', allowOrigin);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key');
    res.setHeader('Access-Control-Max-Age', '86400');
    if (origin && ALLOWED_ORIGINS.has(origin)) {
        res.setHeader('Vary', 'Origin');
    }
    // Short-circuit OPTIONS preflight immediately — required by Lambda Function URLs
    if (req.method === 'OPTIONS') {
        res.status(204).send('');
        return;
    }
    next();
});
// ── Health / Docs ─────────────────────────────────────────────────────────────
exports.app.use('/api/docs', swaggerUi.serve, swaggerUi.setup(swagger_1.swaggerSpec, { customSiteTitle: 'Airbrake Portal API Docs' }));
exports.app.get('/api/docs.json', (_req, res) => res.json(swagger_1.swaggerSpec));
exports.app.get('/api/health', (_req, res) => res.json({ status: 'ok', ts: new Date().toISOString() }));
exports.app.get('/api/health/teams', async (_req, res) => {
    const result = await (0, teamsNotifier_1.testTeamsWebhook)();
    res.json(result);
});
// ── Mount all routers ─────────────────────────────────────────────────────────
const rbac = (0, rbac_1.createRbacMiddleware)(sessionStore, auditLogRepo);
// Ingest (unauthenticated — API-key protected internally)
exports.app.use('/api/ingest', (0, ingestRouter_1.createIngestRouter)(logPipeline, errorAggregator, parseErrorRepository, process.env.API_KEY));
exports.app.use('/api/ingest', (0, errorIngestRouter_1.createErrorIngestRouter)(client_1.pool));
// Dashboard & project endpoints (no auth — internal monitoring)
exports.app.use('/api/dashboard', (0, projectDashboardRouter_1.createProjectDashboardRouter)(client_1.pool));
// Breaks — real-time grouped errors (no auth)
exports.app.use('/api/breaks', (0, projectDashboardRouter_1.createProjectDashboardRouter)(client_1.pool));
// Per-project error upsert (no auth — called by project AI services)
exports.app.use('/api/projects', (0, projectDashboardRouter_1.createProjectErrorUpsertRouter)(client_1.pool));
exports.app.use('/api/projects', (0, projectDashboardRouter_1.createProjectLiveRouter)(client_1.pool));
// Alert management — CRUD on alert_rules + alert_history
exports.app.use('/api', (0, alertManagementRouter_1.createAlertManagementRouter)(client_1.pool));
// Error solutions
exports.app.use('/api/error-solution', (0, errorSolutionRouter_1.createErrorSolutionRouter)(client_1.pool));
// Jira
exports.app.use('/api/jira', (0, jiraRouter_1.createJiraRouter)());
// GET /api/projects — list projects from the projects table (falls back to
// information_schema when the projects registry table doesn't exist yet)
exports.app.get('/api/projects', async (req, res) => {
    try {
        const { category } = req.query;
        // Check if the projects registry table exists
        const { rows: tableExists } = await client_1.pool.query(`
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = 'projects'
      LIMIT 1
    `);
        if (tableExists.length > 0) {
            // Projects registry exists — use it (richer data: id, name, category)
            const { rows } = category
                ? await client_1.pool.query('SELECT id, name, category FROM projects WHERE category = $1 ORDER BY name', [category])
                : await client_1.pool.query('SELECT id, name, category FROM projects ORDER BY name');
            return res.json(rows);
        }
        // Fallback: discover project tables directly from information_schema.
        // Returns the same shape { id, name, category } with category = 'Unknown'
        // so the frontend tile grid still renders.
        const SYSTEM_TABLES = [
            'alert_rules', 'alert_history', 'users', 'projects', 'saved_filters',
            'retention_policies', 'parse_errors', 'audit_log', 'break_groups',
            'breaks', 'error_solutions',
        ];
        const exclude = SYSTEM_TABLES.map((_, i) => `$${i + 1}`).join(',');
        const { rows: tables } = await client_1.pool.query(`
      SELECT DISTINCT table_name
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND column_name = 'project_name'
        AND table_name NOT IN (${exclude})
      ORDER BY table_name
    `, SYSTEM_TABLES);
        const projects = tables.map((t, i) => ({
            id: String(i + 1),
            // Convert table_name back to display name: underscores → spaces, then title-case
            name: t.table_name.replace(/_/g, ' '),
            category: 'Unknown',
        }));
        // Filter by category if requested (no-op when using fallback since all = 'Unknown')
        const filtered = category ? projects.filter((p) => p.category === category) : projects;
        res.json(filtered);
    }
    catch (err) {
        console.error('[Projects] error:', err);
        res.status(500).json({ error: 'Internal server error' });
    }
});
// GET /api/projects/:name/logs — project detail stats
exports.app.get('/api/projects/:name/logs', async (req, res) => {
    try {
        const projectName = decodeURIComponent(req.params.name);
        const page = parseInt(req.query.page) || 1;
        const limit = parseInt(req.query.limit) || 50;
        const offset = (page - 1) * limit;
        // Date filter parameters
        const from = req.query.from;
        const to = req.query.to;
        // Try the exact name (spaces→underscores) first, then lowercase version
        // to handle Aurora DSQL tables which may be all-lowercase
        const tableNameExact = projectName.replace(/ /g, '_');
        const tableNameLower = tableNameExact.toLowerCase();
        const { rows: tableCheck } = await client_1.pool.query(`SELECT table_name FROM information_schema.tables
       WHERE table_schema = 'public' AND LOWER(table_name) = LOWER($1)`, [tableNameExact]);
        if (tableCheck.length === 0) {
            return res.json({ exists: false, tableName: tableNameExact, total: 0, filesProcessed: 0, success: 0, failure: 0, totalCost: null, errors: [], logs: [], pagination: { currentPage: 1, totalPages: 0, totalRecords: 0, limit: 50, hasNextPage: false, hasPreviousPage: false } });
        }
        // Use the actual table name as stored in the DB (preserves case)
        const actualTableName = tableCheck[0].table_name;
        // Build date filter WHERE clause
        let dateFilter = '';
        const queryParams = [limit, offset];
        let paramIndex = 3;
        if (from) {
            dateFilter += ` AND timestamp >= $${paramIndex}`;
            queryParams.push(from);
            paramIndex++;
        }
        if (to) {
            dateFilter += ` AND timestamp <= $${paramIndex}`;
            queryParams.push(to);
            paramIndex++;
        }
        // Get total count first with date filter
        const countQuery = from || to
            ? `SELECT COUNT(*) as total FROM "${actualTableName}" WHERE 1=1 ${dateFilter}`
            : `SELECT COUNT(*) as total FROM "${actualTableName}"`;
        const { rows: countResult } = await client_1.pool.query(countQuery, from || to ? queryParams.slice(2) : []);
        const totalRecords = parseInt(countResult[0].total, 10);
        const totalPages = Math.ceil(totalRecords / limit);
        // Fetch paginated logs with date filter
        const { rows: logs } = await client_1.pool.query(`SELECT file_name, timestamp, success_count, failure_count, error,
              llm_usage, input_tokens, output_tokens, calculated_cost, word_count, file_type,
              error_status, resolved_at, reopened_at
       FROM "${actualTableName}"
       WHERE 1=1 ${dateFilter}
       ORDER BY timestamp DESC LIMIT $1 OFFSET $2`, queryParams);
        const total = totalRecords;
        const filesProcessed = total;
        // Separate resolved errors from active errors
        const resolvedLogs = logs.filter((r) => r.error && r.error !== '' && r.error_status === 'resolved');
        const activeLogs = logs.filter((r) => r.error && r.error !== '' && r.error_status !== 'resolved');
        const successfulLogs = logs.filter((r) => !r.error || r.error === '');
        const success = successfulLogs.length;
        const failure = activeLogs.length; // Count of files with active errors in this page
        const resolved = resolvedLogs.length; // Count of files with resolved errors in this page
        // Sum the failure_count column for more accurate failure metrics
        const totalFailureCount = activeLogs.reduce((sum, r) => sum + (r.failure_count || 0), 0);
        const totalResolvedCount = resolvedLogs.reduce((sum, r) => sum + (r.failure_count || 0), 0);
        const rawCost = logs.reduce((s, r) => s + (parseFloat(r.calculated_cost) || 0), 0);
        const totalCost = rawCost > 0 ? `$${rawCost.toFixed(4)}` : null;
        const errors = activeLogs.map((r) => ({ timestamp: r.timestamp, message: r.error }));
        // Create visibleLogs with all data, but mark resolved errors distinctly
        const visibleLogs = logs.map((r) => ({
            ...r,
            isResolved: r.error && r.error !== '' && r.error_status === 'resolved',
        }));
        console.log(`[DEBUG] Project: ${projectName}, Page: ${page}/${totalPages}${from ? `, From: ${from}` : ''}${to ? `, To: ${to}` : ''}`);
        console.log(`  - Total records: ${totalRecords}`);
        console.log(`  - Files with active errors (this page): ${activeLogs.length}`);
        console.log(`  - Files with resolved errors (this page): ${resolvedLogs.length}`);
        res.json({
            exists: true,
            tableName: actualTableName,
            total,
            filesProcessed,
            success,
            failure, // Number of files with active errors in current page
            resolved, // Number of files with resolved errors in current page
            totalCost,
            errors,
            logs: visibleLogs,
            pagination: {
                currentPage: page,
                totalPages,
                totalRecords,
                limit,
                hasNextPage: page < totalPages,
                hasPreviousPage: page > 1
            }
        });
    }
    catch (err) {
        console.error('[Projects] logs error:', err);
        res.status(500).json({ error: 'Internal server error' });
    }
});
// RBAC-protected legacy routes
exports.app.use('/api/logs', (0, logsRouter_1.createLogsRouterSync)(logSearchRepository, breakExportRepository, sessionStore, auditLogRepo, rbac));
exports.app.use('/api/breaks', (0, breaksRouter_1.createBreaksRouterSync)(breakRepository, correlatedLogRepository, sessionStore, auditLogRepo, rbac, breakExportRepository));
exports.app.use('/api/dashboard', (0, dashboardRouter_1.createDashboardRouterSync)(dashboardRepository, sessionStore, auditLogRepo, rbac));
exports.app.use('/api/alerts', (0, alertsRouter_1.createAlertsRouterSync)(alertRuleRepository, sessionStore, auditLogRepo, rbac));
exports.app.use('/api/filters', (0, filtersRouter_1.createFiltersRouterSync)(savedFilterRepository, sessionStore, auditLogRepo, rbac));
// Admin routes — mounted at /api/admin (canonical path used by admin UI)
// and also directly at /api so Settings.tsx can reach /api/users and /api/retention
exports.app.use('/api/admin', (0, adminRouter_1.createAdminRouterSync)(userRepository, retentionPolicyRepository, sessionStore, auditLogRepo, rbac));
exports.app.use('/api', (0, adminRouter_1.createAdminRouterSync)(userRepository, retentionPolicyRepository, sessionStore, auditLogRepo, rbac));
//# sourceMappingURL=app.js.map