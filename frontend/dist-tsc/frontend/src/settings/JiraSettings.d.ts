/**
 * JiraSettings — per-user Jira OAuth connection panel.
 *
 * Shown inside the Settings page.
 * Each developer connects their own Jira account here (one-time).
 * After connecting, every "Create Jira Ticket" click uses their identity.
 *
 * No Client ID / Client Secret is exposed here — those are administrator
 * environment variables, invisible to developers.
 */
export declare function JiraSettings(): import("react/jsx-runtime").JSX.Element;
