/**
 * JiraOverview — Jira tickets dashboard.
 *
 * Fetches all Jira issues visible to the connected account via
 * GET /api/jira/search?jql=...
 * Reuses existing OAuth integration — no new auth logic.
 *
 * Columns: Issue Key | Summary | Project | Status | Priority | Assignee | Created | Updated | Actions
 */
export declare function JiraOverview(): import("react/jsx-runtime").JSX.Element;
