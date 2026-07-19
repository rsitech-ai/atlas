"""Injection containment suite tests."""

from __future__ import annotations

from rsi_atlas_retrieval.injection_suite import run_injection_suite


def test_injection_suite_self_consistent() -> None:
    passed, total = run_injection_suite()
    assert total == 3
    assert passed == total


def test_injection_suite_detects_leak() -> None:
    passed, total = run_injection_suite(
        actuals={
            "inj_ignore_prev": {"abstain": False, "citation_ids": ["cite_x"], "score": 1},
            "inj_exfil": {"abstain": True, "citation_ids": [], "score": 0},
            "inj_tool": {"abstain": True, "citation_ids": [], "score": 0},
        }
    )
    assert total == 3
    assert passed == 2
