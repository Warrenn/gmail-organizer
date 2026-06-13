from __future__ import annotations

import contextlib
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

# Credentials are passed in memory only — NEVER read from or written to disk.
# The caller sources these env vars from SSM (see scripts/feedback-loop.sh).
#
#   GMAIL_TOKEN_JSON       — an authorized-user token (the output of
#                            `creds.to_json()`); self-contains client_id,
#                            client_secret and refresh_token, so it is all the
#                            runtime needs. Access-token refresh happens in
#                            memory and is not persisted (refresh tokens do not
#                            rotate; if Google ever invalidates one, re-mint via
#                            the `mint-token` command and re-put the SSM param).
#   GMAIL_CREDENTIALS_JSON — an OAuth *client* config (Desktop client). Needed
#                            only by `mint_token_json` for the one-time grant.
TOKEN_ENV = "GMAIL_TOKEN_JSON"
CREDENTIALS_ENV = "GMAIL_CREDENTIALS_JSON"


def credentials_from_token_json(raw: str) -> Credentials:
    """Build Credentials from an in-memory token-JSON string."""
    return Credentials.from_authorized_user_info(json.loads(raw), SCOPES)


def get_service():
    """Build a Gmail service from the in-memory token in ``$GMAIL_TOKEN_JSON``.

    No credentials are read from or written to disk. Raises if the env var is
    absent or holds a token that cannot be made valid.
    """
    raw = os.environ.get(TOKEN_ENV)
    if not raw:
        raise RuntimeError(
            f"{TOKEN_ENV} is not set. Gmail credentials must be supplied in "
            "memory via this environment variable (sourced from SSM). "
            "Credential files are not supported — mint a token with "
            "`python -m gmail_cleanup mint-token` and store it in SSM."
        )

    creds = credentials_from_token_json(raw)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())  # in-memory only; not persisted
        else:
            raise RuntimeError(
                f"{TOKEN_ENV} holds an invalid token that cannot be refreshed. "
                "Re-mint with `python -m gmail_cleanup mint-token`."
            )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def mint_token_json(client_config: dict) -> str:
    """Run the one-time interactive OAuth grant and return the token as a JSON
    string. Writes nothing to disk — the caller pipes the result straight into
    ``aws ssm put-parameter``.
    """
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # The OAuth flow prints its "Please visit this URL..." prompt to stdout;
    # route that to stderr so the caller can pipe the token cleanly into SSM.
    with contextlib.redirect_stdout(sys.stderr):
        creds = flow.run_local_server(port=0)
    return creds.to_json()
