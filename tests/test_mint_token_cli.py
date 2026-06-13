"""mint-token: one-time OAuth grant that emits the token to stdout, never a file."""

from __future__ import annotations

import argparse
import json

import pytest

from gmail_cleanup import __main__ as cli


def test_mint_token_from_env_prints_token_and_writes_no_file(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GMAIL_CREDENTIALS_JSON", json.dumps({"installed": {"client_id": "x"}}))
    monkeypatch.setattr(cli.auth, "mint_token_json", lambda cfg: '{"refresh_token":"r"}')

    rc = cli.cmd_mint_token(argparse.Namespace(client_secret=None))
    assert rc == 0
    assert '"refresh_token"' in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []  # nothing persisted


def test_mint_token_from_client_secret_file(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    secret = tmp_path / "client_secret.json"
    secret.write_text(json.dumps({"installed": {"client_id": "x"}}))
    captured = {}

    def fake_mint(cfg):
        captured["cfg"] = cfg
        return '{"refresh_token":"r"}'

    monkeypatch.setattr(cli.auth, "mint_token_json", fake_mint)

    rc = cli.cmd_mint_token(argparse.Namespace(client_secret=str(secret)))
    assert rc == 0
    assert captured["cfg"] == {"installed": {"client_id": "x"}}
    assert '"refresh_token"' in capsys.readouterr().out


def test_mint_token_errors_when_no_client_config(monkeypatch):
    monkeypatch.delenv("GMAIL_CREDENTIALS_JSON", raising=False)
    rc = cli.cmd_mint_token(argparse.Namespace(client_secret=None))
    assert rc == 2


def test_mint_token_errors_on_missing_client_secret_file(tmp_path, capsys):
    rc = cli.cmd_mint_token(argparse.Namespace(client_secret=str(tmp_path / "nope.json")))
    assert rc == 2
    assert "Could not read client secret file" in capsys.readouterr().err


def test_mint_token_errors_on_invalid_json(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rc = cli.cmd_mint_token(argparse.Namespace(client_secret=str(bad)))
    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_mint_token_is_a_registered_subcommand():
    parser = cli.build_parser()
    args = parser.parse_args(["mint-token"])
    assert args.func is cli.cmd_mint_token
