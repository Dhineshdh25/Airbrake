"""
Jira OAuth 2.0 (3LO) helpers.

Handles:
  - Building the Atlassian authorization URL
  - Exchanging an authorization code for tokens
  - Refreshing an access token
  - Fetching the Atlassian cloud resource list and the user's own profile

No tokens are stored here.  Token persistence lives in token_store.py.
"""

import os
import secrets
import logging
import requests

logger = logging.getLogger(__name__)

# ── Atlassian OAuth endpoints ─────────────────────────────────────────────────
_AUTH_URL       = "https://auth.atlassian.com/authorize"
_TOKEN_URL      = "https://auth.atlassian.com/oauth/token"
_RESOURCES_URL  = "https://api.atlassian.com/oauth/token/accessible-resources"
_TIMEOUT        = 15  # seconds for every outbound HTTP call


def get_credentials() -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri) from environment."""
    client_id     = os.environ.get("ATLASSIAN_CLIENT_ID", "")
    client_secret = os.environ.get("ATLASSIAN_CLIENT_SECRET", "")
    redirect_uri  = os.environ.get(
        "ATLASSIAN_CALLBACK_URL",
        "http://localhost:5000/api/jira/callback",
    )
    return client_id, client_secret, redirect_uri


def get_oauth_scopes() -> str:
    """
    Return the OAuth scopes to request from Atlassian.
    
    Defaults to all required scopes for Jira issue search and creation:
    - read:jira-user (basic user profile)
    - read:jira-work (read issues, projects, JQL search)
    - write:jira-work (create issues, add comments)
    - read:me (Atlassian account profile)
    - read:account (account info)
    
    Can be overridden via ATLASSIAN_OAUTH_SCOPES environment variable.
    Space-separated scope list.
    """
    default_scopes = (
        "read:me "
        "read:account "
        "read:jira-user "
        "read:jira-work "
        "write:jira-work"
    )
    return os.environ.get("ATLASSIAN_OAUTH_SCOPES", default_scopes).strip()


def build_authorization_url(state: str) -> str:
    """
    Return the full Atlassian authorization URL for this OAuth flow.
    
    The scope parameter determines which Jira permissions the access token will have.
    By default, requests:
    - read:me, read:account (user profile)
    - read:jira-user (Jira user info)
    - read:jira-work (read issues, projects, JQL search)
    - write:jira-work (create/update issues, add comments)
    
    Additional granular scopes are available:
    - read:issue:jira, read:project:jira, read:jql:jira (granular read)
    - read:user:jira, read:field:jira, read:comment:jira, read:attachment:jira (additional read)
    - write:issue:jira (granular write)
    
    Configure via ATLASSIAN_OAUTH_SCOPES environment variable if needed.
    """
    client_id, _, redirect_uri = get_credentials()
    if not client_id:
        raise EnvironmentError("ATLASSIAN_CLIENT_ID is not set in environment")

    scopes = get_oauth_scopes()
    
    params = {
        "audience":      "api.atlassian.com",
        "client_id":     client_id,
        "scope":         scopes,
        "redirect_uri":  redirect_uri,
        "state":         state,
        "response_type": "code",
        "prompt":        "consent",
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    url = f"{_AUTH_URL}?{qs}"
    logger.info("[Jira OAuth] Built authorization URL (state=%s, scopes=%s)", state, scopes)
    return url


def generate_state() -> str:
    """Return a cryptographically random CSRF-protection state token."""
    return secrets.token_urlsafe(24)


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange an authorization code for access + refresh tokens.

    Returns the raw token response dict from Atlassian.
    Raises requests.HTTPError on failure.
    """
    client_id, client_secret, redirect_uri = get_credentials()
    logger.info("[Jira OAuth] Exchanging authorization code for tokens")

    resp = requests.post(
        _TOKEN_URL,
        json={
            "grant_type":    "authorization_code",
            "client_id":     client_id,
            "client_secret": client_secret,
            "code":          code,
            "redirect_uri":  redirect_uri,
        },
        headers={"Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    logger.info("[Jira OAuth] Token exchange succeeded")
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    """
    Use a refresh token to obtain a new access token.

    Returns the raw token response dict.
    Raises requests.HTTPError on failure.
    DO NOT log the token values.
    """
    client_id, client_secret, _ = get_credentials()
    logger.info("[Jira OAuth] Refreshing access token")

    resp = requests.post(
        _TOKEN_URL,
        json={
            "grant_type":    "refresh_token",
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    logger.info("[Jira OAuth] Token refresh succeeded")
    return resp.json()


def fetch_cloud_id(access_token: str) -> str:
    """
    Return the Atlassian cloud_id of the first accessible resource.

    The cloud_id identifies which Jira Cloud site to call.
    DO NOT log the access_token.
    """
    resp = requests.get(
        _RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    resources = resp.json()
    if not resources:
        raise ValueError("No Atlassian resources accessible with this token")
    cloud_id = resources[0]["id"]
    logger.info("[Jira OAuth] Resolved cloud_id=%s", cloud_id)
    return cloud_id


def fetch_site_url(access_token: str) -> str:
    """Return the base URL of the first accessible Jira site (e.g. https://myco.atlassian.net)."""
    resp = requests.get(
        _RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    resources = resp.json()
    if not resources:
        return ""
    return resources[0].get("url", "")


def fetch_user_profile(access_token: str, cloud_id: str) -> dict:
    """
    Return the Jira user's profile dict: { accountId, emailAddress, displayName }.
    DO NOT log the access_token.
    """
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    profile = resp.json()
    logger.info(
        "[Jira OAuth] Fetched user profile accountId=%s email=%s",
        profile.get("accountId"), profile.get("emailAddress"),
    )
    return profile
