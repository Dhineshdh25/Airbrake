"""
Google OAuth 2.0 / OIDC helpers.

Handles:
  - Building the Google authorization URL
  - Exchanging an authorization code for tokens
  - Validating the ID token and extracting user info

Environment variables required:
  GOOGLE_CLIENT_ID       — OAuth 2.0 client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET   — OAuth 2.0 client secret
  GOOGLE_CALLBACK_URL    — e.g. https://<lambda-url>/api/auth/google/callback

No tokens or sessions are stored here.
"""

import logging
import os
import secrets

import requests

logger = logging.getLogger(__name__)

# ── Google OAuth endpoints ────────────────────────────────────────────────────
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_TIMEOUT = 15  # seconds


def get_credentials() -> tuple:
    """Return (client_id, client_secret, redirect_uri) from environment."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.environ.get(
        "GOOGLE_CALLBACK_URL",
        "http://localhost:5000/api/auth/google/callback",
    )
    return client_id, client_secret, redirect_uri


def generate_state() -> str:
    """Return a cryptographically random CSRF state token."""
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    """
    Build the Google OAuth authorization URL.

    Requests openid + email + profile scopes for OIDC.
    Uses 'consent' prompt to always show the consent screen.
    """
    client_id, _, redirect_uri = get_credentials()
    if not client_id:
        raise EnvironmentError("GOOGLE_CLIENT_ID is not set in environment")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    url = f"{_AUTH_URL}?{qs}"
    logger.info("[Google OAuth] Built authorization URL (state=%s...)", state[:8])
    return url


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange an authorization code for tokens.

    Returns the raw token response dict containing:
      access_token, id_token, expires_in, token_type, scope
    Raises requests.HTTPError on failure.
    """
    client_id, client_secret, redirect_uri = get_credentials()
    logger.info("[Google OAuth] Exchanging authorization code for tokens")

    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    logger.info("[Google OAuth] Token exchange succeeded")
    return resp.json()


def get_user_info(access_token: str) -> dict:
    """
    Fetch the authenticated user's profile from Google.

    Returns dict with: sub, email, email_verified, name, picture, etc.
    DO NOT log the access_token.
    """
    resp = requests.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    info = resp.json()
    logger.info(
        "[Google OAuth] Fetched user info sub=%s email=%s verified=%s",
        info.get("sub"),
        info.get("email"),
        info.get("email_verified"),
    )
    return info


def validate_id_token_claims(id_token_payload: dict) -> bool:
    """
    Validate basic claims from the decoded ID token.

    Checks:
    - email_verified is True
    - sub is present and non-empty

    Note: Full JWT signature verification is done by Google's token endpoint.
    Since we receive the id_token directly from Google's token endpoint over HTTPS,
    the token is implicitly trusted (no need for local JWT verification).
    """
    if not id_token_payload.get("sub"):
        logger.warning("[Google OAuth] ID token missing 'sub' claim")
        return False

    if not id_token_payload.get("email_verified", False):
        logger.warning("[Google OAuth] Email not verified for sub=%s", id_token_payload.get("sub"))
        return False

    return True


def decode_id_token_payload(id_token: str) -> dict:
    """
    Decode the payload of a JWT ID token WITHOUT signature verification.

    This is safe because:
    1. The id_token comes directly from Google's token endpoint over HTTPS
    2. We already authenticated with client_secret in the token exchange

    Returns the decoded payload dict.
    """
    import base64

    # JWT format: header.payload.signature
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    # Decode payload (add padding if needed)
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding

    import json
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)
