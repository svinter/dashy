"""Shared Google API authentication."""

import json
import logging
import os
import stat

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import DATA_DIR, GCLOUD_CREDENTIALS_PATH, get_google_scopes

logger = logging.getLogger(__name__)

TOKEN_PATH = DATA_DIR / ".google_token.json"
_cached_creds: Credentials | None = None


def _scopes_sufficient(creds: Credentials) -> bool:
    """Check if the credential's granted scopes cover all required scopes.

    Returns True when scopes cannot be determined (no scope info in token) —
    assume OK and let the API call fail naturally if scopes are wrong.
    Returns False only when the token explicitly records scopes that don't
    cover the required set.
    """
    if not creds.scopes:
        return True  # No scope info — can't verify, assume OK
    required = set(get_google_scopes())
    granted = set(creds.scopes)
    return required.issubset(granted)


def _get_quota_project_id() -> str | None:
    """Read quota_project_id from ADC credentials."""
    if GCLOUD_CREDENTIALS_PATH.exists():
        with open(GCLOUD_CREDENTIALS_PATH) as f:
            return json.load(f).get("quota_project_id")
    return None


def _get_client_credentials() -> tuple[str, str] | None:
    """Resolve Google OAuth client credentials from config or file.

    Returns (client_id, client_secret) or None if no credentials found.
    Priority:
      1. GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in config.json secrets
      2. google_client_secret.json file in DATA_DIR

    Note: gcloud ADC credentials are intentionally excluded here. The gcloud
    CLI's own client_id/client_secret cannot be used for new OAuth flows
    (Google rejects them with 'invalid_client'). ADC token refresh is handled
    separately in get_google_credentials().
    """
    from app_config import get_secret

    # 1. Config secrets (primary path for DMG users)
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return (client_id, client_secret)

    # 2. Bundled client_secret.json file in data directory
    client_secret_file = DATA_DIR / "google_client_secret.json"
    if client_secret_file.exists():
        try:
            with open(client_secret_file) as f:
                data = json.load(f)
            app_data = data.get("installed") or data.get("web") or {}
            cid = app_data.get("client_id")
            csec = app_data.get("client_secret")
            if cid and csec:
                return (cid, csec)
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read google_client_secret.json")

    return None


def get_google_credentials() -> Credentials:
    """Return Dashy-specific Google credentials from TOKEN_PATH only.

    Never falls back to gcloud ADC — ADC tokens carry different scopes and
    cannot be replaced without breaking the gcloud CLI for the user.

    Returns None-equivalent by raising FileNotFoundError when unauthenticated,
    or RuntimeError when the token exists but has wrong/expired scopes (token
    is deleted so the next call will prompt re-authentication).
    """
    global _cached_creds
    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    scopes = get_google_scopes()
    quota_project_id = _get_quota_project_id()

    if not TOKEN_PATH.exists():
        _cached_creds = None
        raise FileNotFoundError(
            "Google not authenticated. Click Authenticate in Settings → Connectors → Google."
        )

    _cached_creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)
    if quota_project_id:
        _cached_creds = _cached_creds.with_quota_project(quota_project_id)

    if not _scopes_sufficient(_cached_creds):
        _cached_creds = None
        TOKEN_PATH.unlink(missing_ok=True)
        raise RuntimeError(
            "Google token has insufficient scopes. Please Disconnect and re-Authenticate "
            "in Settings → Connectors → Google to grant the required permissions."
        )

    if _cached_creds.expired and _cached_creds.refresh_token:
        try:
            _cached_creds.refresh(Request())
            TOKEN_PATH.write_text(_cached_creds.to_json())
            os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except RefreshError as e:
            logger.warning("Token refresh failed: %s", e)
            _cached_creds = None
            TOKEN_PATH.unlink(missing_ok=True)
            raise RuntimeError(
                "Google token refresh failed. Please Disconnect and re-Authenticate "
                "in Settings → Connectors → Google."
            ) from e

    if not (_cached_creds and _cached_creds.valid):
        _cached_creds = None
        raise RuntimeError(
            "Google token is invalid. Please Disconnect and re-Authenticate "
            "in Settings → Connectors → Google."
        )

    return _cached_creds


def _find_free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def run_oauth_flow() -> Credentials:
    """Run browser-based OAuth flow using resolved client credentials."""
    import subprocess
    import webbrowser

    from google_auth_oauthlib.flow import InstalledAppFlow

    logger.info("Starting Google OAuth flow...")

    creds_pair = _get_client_credentials()
    if not creds_pair:
        raise FileNotFoundError(
            "No Google OAuth client credentials found. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Settings."
        )

    client_id, client_secret = creds_pair
    scopes = get_google_scopes()
    port = _find_free_port()
    logger.info("OAuth scopes: %s", scopes)
    logger.info("OAuth callback port: %d", port)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{port}"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes)

    # In pywebview (DMG app), webbrowser.open() can silently fail because
    # PyInstaller bundles may not find the system browser correctly.
    # Monkey-patch webbrowser.open to use macOS `open` command which always works.
    _orig_open = webbrowser.open

    def _open_via_macos(url, *args, **kwargs):
        logger.info("Opening OAuth URL in system browser")
        try:
            subprocess.Popen(["open", url])
            return True
        except Exception:
            logger.warning("macOS `open` failed, falling back to webbrowser.open")
            return _orig_open(url, *args, **kwargs)

    webbrowser.open = _open_via_macos
    try:
        logger.info("Waiting for OAuth callback on port %d...", port)
        creds = flow.run_local_server(
            port=port,
            open_browser=True,
            # Force the full consent screen so Google returns exactly the
            # requested scopes — nothing more, nothing less.
            prompt="consent",
            access_type="offline",
        )
    finally:
        webbrowser.open = _orig_open

    global _cached_creds
    _cached_creds = creds
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
    logger.info("OAuth flow completed, token saved to %s", TOKEN_PATH)
    return creds
