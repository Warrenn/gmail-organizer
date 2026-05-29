from __future__ import annotations

import argparse
import json

from gmail_cleanup import __main__ as cli


def _args(path):
    return argparse.Namespace(input=str(path), credentials="creds.json", token="token.json")


def test_cmd_cleanup_markers_missing_file_is_noop(tmp_path):
    # Nonexistent file → nothing to do, exit 0, never touches Gmail.
    assert cli.cmd_cleanup_markers(_args(tmp_path / "nope.json")) == 0


def test_cmd_cleanup_markers_empty_array_is_noop(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text("[]")
    assert cli.cmd_cleanup_markers(_args(p)) == 0


def test_cmd_cleanup_markers_rejects_non_array(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text(json.dumps({"marker_label_id": "x"}))  # object, not array
    assert cli.cmd_cleanup_markers(_args(p)) == 2


def test_cmd_cleanup_markers_rejects_entry_missing_keys(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text(json.dumps([{"marker_label_id": "L1", "sign": "+"}]))  # missing name + target
    assert cli.cmd_cleanup_markers(_args(p)) == 2


def test_cmd_cleanup_markers_rejects_invalid_sign(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text(json.dumps([{
        "marker_label_id": "L1",
        "marker_label_name": "*weird",
        "sign": "*",
        "target_label_name": "receipts",
        "thread_ids": ["t1"],
    }]))
    assert cli.cmd_cleanup_markers(_args(p)) == 2


def test_cmd_cleanup_markers_rejects_non_list_thread_ids(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text(json.dumps([{
        "marker_label_id": "L1",
        "marker_label_name": "+receipts",
        "sign": "+",
        "target_label_name": "receipts",
        "thread_ids": "t1",  # should be a list
    }]))
    assert cli.cmd_cleanup_markers(_args(p)) == 2


def test_cmd_cleanup_markers_rejects_non_object_entry(tmp_path):
    p = tmp_path / "feedback_resolved.json"
    p.write_text(json.dumps(["just a string"]))
    assert cli.cmd_cleanup_markers(_args(p)) == 2
