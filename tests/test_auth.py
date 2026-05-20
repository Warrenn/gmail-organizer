from __future__ import annotations

import json
from pathlib import Path

import pytest

from gmail_cleanup import auth


def test_scopes_are_modify_and_labels_only():
    assert auth.SCOPES == [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.labels",
    ]


def test_scopes_exclude_full_mail_scope():
    assert "https://mail.google.com/" not in auth.SCOPES


def test_load_cached_credentials_returns_none_when_missing(tmp_path: Path):
    token = tmp_path / "token.json"
    assert auth.load_cached_credentials(token) is None


def test_load_cached_credentials_parses_existing_file(tmp_path: Path):
    token = tmp_path / "token.json"
    payload = {
        "token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake-client-id",
        "client_secret": "fake-client-secret",
        "scopes": list(auth.SCOPES),
    }
    token.write_text(json.dumps(payload))
    creds = auth.load_cached_credentials(token)
    assert creds is not None
    assert creds.refresh_token == "fake-refresh-token"
    assert set(creds.scopes) == set(auth.SCOPES)


def test_save_credentials_roundtrip(tmp_path: Path):
    from google.oauth2.credentials import Credentials

    token = tmp_path / "token.json"
    creds = Credentials(
        token="acc",
        refresh_token="ref",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="csec",
        scopes=list(auth.SCOPES),
    )
    auth.save_credentials(creds, token)
    assert token.exists()
    reloaded = auth.load_cached_credentials(token)
    assert reloaded is not None
    assert reloaded.refresh_token == "ref"


def test_credentials_path_must_exist_for_initial_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If no token cached AND no credentials.json, get_service must raise a clear error."""
    missing_creds = tmp_path / "credentials.json"
    missing_token = tmp_path / "token.json"
    with pytest.raises(FileNotFoundError, match="credentials.json"):
        auth.get_service(missing_creds, missing_token)
