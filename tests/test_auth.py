from __future__ import annotations

import json

import pytest

from gmail_cleanup import auth

TOKEN_PAYLOAD = {
    "token": "fake-access-token",
    "refresh_token": "fake-refresh-token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "scopes": list(auth.SCOPES),
}


def test_scopes_are_modify_and_labels_only():
    assert auth.SCOPES == [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.labels",
    ]


def test_scopes_exclude_full_mail_scope():
    assert "https://mail.google.com/" not in auth.SCOPES


def test_credentials_from_token_json_parses_in_memory():
    creds = auth.credentials_from_token_json(json.dumps(TOKEN_PAYLOAD))
    assert creds.refresh_token == "fake-refresh-token"
    assert set(creds.scopes) == set(auth.SCOPES)


def test_get_service_raises_clear_error_when_env_unset(monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=auth.TOKEN_ENV):
        auth.get_service()


def test_get_service_builds_from_env_without_touching_disk(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.TOKEN_ENV, json.dumps(TOKEN_PAYLOAD))
    # valid token → straight to build(), no refresh/network
    monkeypatch.setattr(auth.Credentials, "valid", property(lambda self: True))
    built = {}
    monkeypatch.setattr(auth, "build", lambda *a, **k: built.setdefault("svc", object()))
    monkeypatch.chdir(tmp_path)

    svc = auth.get_service()
    assert svc is built["svc"]
    # nothing was written to disk
    assert list(tmp_path.iterdir()) == []


def test_get_service_does_not_persist_token_on_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.TOKEN_ENV, json.dumps(TOKEN_PAYLOAD))
    monkeypatch.chdir(tmp_path)

    # Force the "needs refresh" branch and stub the network refresh.
    monkeypatch.setattr(auth.Credentials, "valid", property(lambda self: False))
    monkeypatch.setattr(auth.Credentials, "expired", property(lambda self: True))
    refreshed = {}
    monkeypatch.setattr(auth.Credentials, "refresh",
                        lambda self, request: refreshed.setdefault("did", True))
    monkeypatch.setattr(auth, "build", lambda *a, **k: object())

    auth.get_service()
    assert refreshed.get("did") is True
    # refresh must NOT write a token file anywhere
    assert list(tmp_path.iterdir()) == []


def test_mint_token_json_returns_string_and_writes_no_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class FakeCreds:
        def to_json(self):
            return json.dumps(TOKEN_PAYLOAD)

    class FakeFlow:
        def run_local_server(self, *a, **k):
            return FakeCreds()

    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config",
                        classmethod(lambda cls, config, scopes: FakeFlow()))

    out = auth.mint_token_json({"installed": {"client_id": "x"}})
    assert json.loads(out)["refresh_token"] == "fake-refresh-token"
    assert list(tmp_path.iterdir()) == []


def test_mint_token_json_keeps_oauth_prompt_off_stdout(monkeypatch, capsys):
    # The OAuth library prints "Please visit this URL..." to stdout. mint_token_json
    # must keep stdout clean so the token can be piped straight into SSM.
    class FakeCreds:
        def to_json(self):
            return '{"refresh_token":"r"}'

    class FakeFlow:
        def run_local_server(self, *a, **k):
            print("Please visit this URL to authorize: http://example/auth")
            return FakeCreds()

    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config",
                        classmethod(lambda cls, config, scopes: FakeFlow()))

    token = auth.mint_token_json({"installed": {"client_id": "x"}})
    out, err = capsys.readouterr()
    assert token == '{"refresh_token":"r"}'
    assert "Please visit" not in out   # nothing but the token may reach stdout
    assert "Please visit" in err       # the prompt is routed to stderr


def test_auth_module_has_no_file_persistence_functions():
    # The fileless contract: these file-based helpers must be gone.
    assert not hasattr(auth, "save_credentials")
    assert not hasattr(auth, "load_cached_credentials")


# ---- Apps Script API (deploy) scope + service ----------------------------
def test_gmail_scopes_alias():
    assert auth.SCOPES == auth.GMAIL_SCOPES


def test_apps_script_scope_is_projects_only():
    assert auth.APPS_SCRIPT_SCOPES == ["https://www.googleapis.com/auth/script.projects"]


def test_get_apps_script_service_raises_without_env(monkeypatch):
    monkeypatch.delenv(auth.APPS_SCRIPT_TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=auth.APPS_SCRIPT_TOKEN_ENV):
        auth.get_apps_script_service()


def test_get_apps_script_service_builds_script_v1(monkeypatch):
    monkeypatch.setenv(auth.APPS_SCRIPT_TOKEN_ENV, json.dumps(TOKEN_PAYLOAD))
    monkeypatch.setattr(auth.Credentials, "valid", property(lambda self: True))
    captured = {}

    def fake_build(name, version, **kwargs):
        captured["name"], captured["version"] = name, version
        return object()

    monkeypatch.setattr(auth, "build", fake_build)
    svc = auth.get_apps_script_service()
    assert svc is not None
    assert captured == {"name": "script", "version": "v1"}


def test_mint_token_json_uses_given_scopes(monkeypatch):
    captured = {}

    class FakeCreds:
        def to_json(self):
            return '{"refresh_token":"r"}'

    class FakeFlow:
        def run_local_server(self, *a, **k):
            return FakeCreds()

    def fake_from_client_config(cls, config, scopes):
        captured["scopes"] = scopes
        return FakeFlow()

    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config",
                        classmethod(fake_from_client_config))
    auth.mint_token_json({"installed": {}}, scopes=auth.APPS_SCRIPT_SCOPES)
    assert captured["scopes"] == auth.APPS_SCRIPT_SCOPES
