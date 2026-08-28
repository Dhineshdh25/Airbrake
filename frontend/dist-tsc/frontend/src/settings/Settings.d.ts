/**
 * Settings view — admin and non-admin layouts.
 *
 * ADMIN:
 *   - Users section: full table of all users, role editing, add/remove workflow
 *   - Projects section: all projects with responsible-user assignment
 *   - Jira Integration section
 *
 * NON-ADMIN (viewer / developer):
 *   - Own row only: email, role, own Jira ticket counts
 *   - Jira Integration section
 *
 * Security:
 *   - All mutations go through the backend; the backend derives the caller's
 *     identity from the session cookie — never from a frontend-supplied user_id.
 *   - Ticket counts for other users are fetched via GET /api/users/<id>/tickets
 *     which is admin-gated server-side.
 *   - No user's oauth_subject or raw metadata is rendered.
 */
import type { Role } from '@portal/shared';
interface Props {
    readonly role: Role;
}
export declare function Settings({ role }: Props): import("react/jsx-runtime").JSX.Element;
export {};
