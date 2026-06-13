"""deploy-apps-script: fileless push of apps-script/ via the Apps Script API."""

from __future__ import annotations

import argparse

from gmail_cleanup import __main__ as cli


def _make_apps_dir(tmp_path):
    d = tmp_path / "apps-script"
    d.mkdir()
    (d / "Code.gs").write_text("function run(){}")
    (d / "Classifier.gs").write_text("// classifier")
    (d / "appsscript.json").write_text('{"timeZone":"Africa/Johannesburg"}')
    return d


def test_build_apps_script_files_maps_names_and_types(tmp_path):
    d = _make_apps_dir(tmp_path)
    files = {f["name"]: f for f in cli._build_apps_script_files(str(d))}
    assert files["Code"]["type"] == "SERVER_JS"
    assert files["Code"]["source"] == "function run(){}"
    assert files["Classifier"]["type"] == "SERVER_JS"
    assert files["appsscript"]["type"] == "JSON"
    # manifest must be present and named exactly "appsscript"
    assert set(files) == {"Code", "Classifier", "appsscript"}


def test_cmd_deploy_calls_update_content(monkeypatch, tmp_path):
    d = _make_apps_dir(tmp_path)
    captured = {}

    class FakeReq:
        def execute(self):
            captured["executed"] = True
            return {"scriptId": "SID"}

    class FakeProjects:
        def updateContent(self, scriptId, body):
            captured["scriptId"] = scriptId
            captured["body"] = body
            return FakeReq()

    class FakeSvc:
        def projects(self):
            return FakeProjects()

    monkeypatch.setattr(cli.auth, "get_apps_script_service", lambda: FakeSvc())
    rc = cli.cmd_deploy_apps_script(argparse.Namespace(script_id="SID", apps_dir=str(d)))
    assert rc == 0
    assert captured["scriptId"] == "SID"
    assert captured["executed"] is True
    assert {f["name"] for f in captured["body"]["files"]} == {"Code", "Classifier", "appsscript"}


def test_cmd_deploy_uses_env_script_id(monkeypatch, tmp_path):
    d = _make_apps_dir(tmp_path)
    monkeypatch.setenv("APPS_SCRIPT_ID", "FROM_ENV")
    captured = {}

    class FakeSvc:
        def projects(self):
            class P:
                def updateContent(self, scriptId, body):
                    captured["scriptId"] = scriptId
                    class R:
                        def execute(self_):
                            return {}
                    return R()
            return P()

    monkeypatch.setattr(cli.auth, "get_apps_script_service", lambda: FakeSvc())
    rc = cli.cmd_deploy_apps_script(argparse.Namespace(script_id=None, apps_dir=str(d)))
    assert rc == 0
    assert captured["scriptId"] == "FROM_ENV"


def test_cmd_deploy_errors_without_script_id(monkeypatch):
    monkeypatch.delenv("APPS_SCRIPT_ID", raising=False)
    rc = cli.cmd_deploy_apps_script(argparse.Namespace(script_id=None, apps_dir="apps-script"))
    assert rc == 2


def test_deploy_apps_script_is_registered():
    parser = cli.build_parser()
    args = parser.parse_args(["deploy-apps-script"])
    assert args.func is cli.cmd_deploy_apps_script
