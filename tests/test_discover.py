from __future__ import annotations

from gmail_cleanup import discover


def test_compose_year_query_no_extra():
    assert discover.compose_year_query("", 2024) == "after:2024/01/01 before:2025/01/01"


def test_compose_year_query_with_extra():
    assert (
        discover.compose_year_query("-label:Bills", 2024)
        == "(-label:Bills) after:2024/01/01 before:2025/01/01"
    )


def test_compose_year_query_strips_whitespace_in_extra():
    assert (
        discover.compose_year_query("  -label:foo  ", 2024)
        == "(-label:foo) after:2024/01/01 before:2025/01/01"
    )
