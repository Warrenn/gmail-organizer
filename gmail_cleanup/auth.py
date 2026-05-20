from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


def load_cached_credentials(token_path: Path) -> Credentials | None:
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), SCOPES)


def save_credentials(creds: Credentials, token_path: Path) -> None:
    token_path.write_text(creds.to_json())


def get_service(credentials_path: Path, token_path: Path):
    creds = load_cached_credentials(token_path)
    if creds and creds.valid:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds, token_path)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {credentials_path}. "
            "Download a Desktop OAuth client JSON from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    save_credentials(creds, token_path)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
