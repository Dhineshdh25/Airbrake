/**
 * Jira Router
 * POST /api/jira/create-ticket
 *
 * Creates a Jira issue with:
 *   summary    = short error (e.g. "json.JSONDecodeError")
 *   description = full error_detail traceback
 *   + fixed default custom fields
 *
 * Credentials from .env:
 *   JIRA_BASE_URL, JIRA_PROJECT_KEY, JIRA_EMAIL, JIRA_API_TOKEN
 */

export function createJiraRouter() {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const express = require('express');
  const router = express.Router();

  // GET /api/jira/create-ticket-redirect?summary=...&description=...
  // Called when "Create Jira Ticket" button is clicked in Teams card
  router.get('/create-ticket-redirect', async (req: any, res: any) => {
    try {
      const jiraBaseUrl = process.env.JIRA_BASE_URL ?? '';
      const projectKey = process.env.JIRA_PROJECT_KEY ?? '';
      const jiraEmail = process.env.JIRA_EMAIL ?? '';
      const jiraApiToken = process.env.JIRA_API_TOKEN ?? '';

      if (!jiraBaseUrl || !projectKey || !jiraEmail || !jiraApiToken) {
        return res.status(500).send('Jira credentials not configured');
      }

      const summary = String(req.query.summary ?? '');
      const description = String(req.query.description ?? summary);

      const auth = Buffer.from(`${jiraEmail}:${jiraApiToken}`).toString('base64');

      const payload = {
        fields: {
          project: { key: projectKey },
          issuetype: { name: 'Story' },
          summary,
          description: {
            type: 'doc', version: 1,
            content: [{ type: 'paragraph', content: [{ type: 'text', text: description }] }],
          },
          customfield_10120: 10,
          customfield_10339: { value: 'Productivity' },
          customfield_10340: { value: 'Elsevier Journal' },
          customfield_10033: 1,
          customfield_10104: 'Improving accuracy, reducing manual effort',
        },
      };

      const response = await fetch(`${jiraBaseUrl}/rest/api/3/issue`, {
        method: 'POST',
        headers: {
          'Authorization': `Basic ${auth}`,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json() as any;

      if (!response.ok) {
        console.error('[Jira] redirect create failed:', data);
        return res.status(500).send(`Jira error: ${JSON.stringify(data)}`);
      }

      const ticketUrl = `${jiraBaseUrl}/browse/${data.key}`;
      console.log('[Jira] ticket created via redirect:', data.key);
      // Redirect browser to the created ticket
      return res.redirect(ticketUrl);

    } catch (err) {
      console.error('[Jira] redirect error:', err);
      res.status(500).send('Internal server error');
    }
  });

  router.post('/create-ticket', async (req: any, res: any) => {
    try {
      const jiraBaseUrl = process.env.JIRA_BASE_URL ?? '';
      const projectKey = process.env.JIRA_PROJECT_KEY ?? '';
      const jiraEmail = process.env.JIRA_EMAIL ?? '';
      const jiraApiToken = process.env.JIRA_API_TOKEN ?? '';

      if (!jiraBaseUrl || !projectKey || !jiraEmail || !jiraApiToken) {
        return res.status(500).json({ error: 'Jira credentials not configured in .env' });
      }

      const { summary, description } = req.body as { summary?: string; description?: string };

      if (!summary) return res.status(400).json({ error: 'summary is required' });

      const auth = Buffer.from(`${jiraEmail}:${jiraApiToken}`).toString('base64');

      const payload = {
        fields: {
          project: { key: projectKey },
          issuetype: { name: 'Story' },
          summary: summary,
          description: {
            type: 'doc',
            version: 1,
            content: [
              {
                type: 'paragraph',
                content: [{ type: 'text', text: description || summary }],
              },
            ],
          },
          // Fixed default custom fields
          customfield_10120: 10,                                          // CS-Time Savings (Per Month)
          customfield_10339: { value: 'Productivity' },                   // Efficiency Gain
          customfield_10340: { value: 'Elsevier Journal' },               // Impacted Customer - CS
          customfield_10033: 1,                                           // Story Points
          customfield_10104: 'Improving accuracy, reducing manual effort', // Efficiency Type
        },
      };

      const response = await fetch(`${jiraBaseUrl}/rest/api/3/issue`, {
        method: 'POST',
        headers: {
          'Authorization': `Basic ${auth}`,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json() as any;

      if (!response.ok) {
        console.error('[Jira] create-ticket failed:', data);
        return res.status(response.status).json({ error: 'Jira API error', detail: data });
      }

      console.log('[Jira] ticket created:', data.key);
      return res.json({
        ticket_key: data.key,
        ticket_url: `${jiraBaseUrl}/browse/${data.key}`,
      });

    } catch (err) {
      console.error('[Jira] create-ticket error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // GET /api/jira/search?jql=<query>&maxResults=100
  // Search Jira issues directly using JQL
  router.get('/search', async (req: any, res: any) => {
    try {
      const jiraBaseUrl = process.env.JIRA_BASE_URL ?? '';
      const jiraEmail = process.env.JIRA_EMAIL ?? '';
      const jiraApiToken = process.env.JIRA_API_TOKEN ?? '';

      if (!jiraBaseUrl || !jiraEmail || !jiraApiToken) {
        return res.status(500).json({
          error: 'Jira credentials not configured',
          needs_auth: true
        });
      }

      const jql = String(req.query.jql ?? '');
      if (!jql) {
        return res.status(400).json({ error: 'jql parameter is required' });
      }

      const maxResults = parseInt(String(req.query.maxResults ?? '100'), 10);
      const fields = req.query.fields ? String(req.query.fields).split(',') : undefined;

      const auth = Buffer.from(`${jiraEmail}:${jiraApiToken}`).toString('base64');

      // Build request URL for the new /rest/api/3/search/jql endpoint
      const searchUrl = new URL(`${jiraBaseUrl}/rest/api/3/search/jql`);

      const payload: any = {
        jql,
        maxResults,
      };

      if (fields && fields.length > 0) {
        payload.fields = fields;
      }

      console.log('[Jira] Searching with JQL:', jql.substring(0, 100));

      const response = await fetch(searchUrl.toString(), {
        method: 'POST',
        headers: {
          'Authorization': `Basic ${auth}`,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json() as any;

      if (!response.ok) {
        console.error('[Jira] search failed:', data);
        return res.status(response.status).json({
          error: 'Jira API error',
          detail: data,
          needs_auth: response.status === 401
        });
      }

      console.log(`[Jira] Search returned ${data.issues?.length ?? 0} issues`);

      return res.json({
        issues: data.issues ?? [],
        isLast: data.isLast ?? true,
        nextPageToken: data.nextPageToken ?? null,
        total: data.issues?.length ?? 0,
      });

    } catch (err) {
      console.error('[Jira] search error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // GET /api/jira/status
  // Check if Jira is configured (credentials exist)
  router.get('/status', async (req: any, res: any) => {
    try {
      const jiraBaseUrl = process.env.JIRA_BASE_URL ?? '';
      const jiraEmail = process.env.JIRA_EMAIL ?? '';
      const jiraApiToken = process.env.JIRA_API_TOKEN ?? '';

      const isConfigured = !!(jiraBaseUrl && jiraEmail && jiraApiToken);

      return res.json({
        connected: isConfigured,
        email: isConfigured ? jiraEmail : '',
        account_id: '', // Not applicable for Basic Auth
      });

    } catch (err) {
      console.error('[Jira] status error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  return router;
}
