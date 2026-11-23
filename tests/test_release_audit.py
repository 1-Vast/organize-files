from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_audit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def valid_report() -> dict:
    return {
        "schema": 1,
        "scope": {
            "root": str(ROOT),
            "exclusions": [{"path": "data", "status": "opaque-inventoried", "reason": "raw inputs"}],
        },
        "inventory": {
            "before": {"files": 2, "dirs": 1, "bytes": 20, "root_entries": 2},
            "after": {"files": 1, "dirs": 1, "bytes": 10, "root_entries": 1},
        },
        "findings": [{
            "id": "finding:1",
            "path": "src/example.md",
            "disposition": "resolved",
            "evidence": ["move-plan.json"],
        }],
        "operations": [{"op": "move", "source": "a", "target": "b", "outcome": "verified"}],
        "links": {"checked": 1, "broken": []},
        "tests": [{"command": "pytest", "returncode": 0}],
        "git": {"branch": "main", "commit": "abc", "remote_commit": "abc", "clean": True},
        "review": {"independent_reviewer": "reviewer", "verdict": "PASS"},
        "recovery": {"manifest": "CHANGELOG.md", "verified": True},
        "coverage": {
            "findings": {"manifest": "CHANGELOG.md", "verified": True, "dispositioned": 1},
            "archive": {"manifest": "CHANGELOG.md", "verified": True, "paths_verified": 0},
            "delete": {
                "manifest": "CHANGELOG.md",
                "verified": True,
                "paths_verified": 0,
                "bytes_removed_verified": 0,
            },
        },
        "tidy_audit": {"root": str(ROOT), "findings": [{"id": "finding:1", "path": "src/example.md"}]},
        "status": "COMPLETE",
    }


def test_valid_report_passes() -> None:
    assert release_audit.validate(valid_report()) == []


def test_complete_report_rejects_missing_finding_and_remote_match() -> None:
    report = valid_report()
    report["findings"][0].pop("evidence")
    report["git"]["remote_commit"] = "different"
    assert release_audit.validate(report)


def test_complete_report_rejects_incomplete_dispositions() -> None:
    for disposition in ("deferred", "blocked", "excluded", "unknown"):
        report = valid_report()
        report["findings"][0]["disposition"] = disposition
        assert release_audit.validate(report)


def test_empty_tests_inventory_and_operations_fail() -> None:
    report = valid_report()
    report["tests"] = []
    report["operations"] = []
    report["inventory"]["before"].pop("bytes")
    assert len(release_audit.validate(report)) >= 3


def test_excluded_finding_requires_scope_coverage() -> None:
    report = valid_report()
    report["status"] = "PARTIAL"
    report["findings"][0]["disposition"] = "excluded"
    report["findings"][0]["path"] = "src/example.md"
    assert release_audit.validate(report)
    report["findings"][0]["path"] = "data/example.md"
    report["tidy_audit"]["findings"][0]["path"] = "data/example.md"
    assert release_audit.validate(report) == []


def test_check_git_uses_actual_repository_state(tmp_path: Path) -> None:
    report = valid_report()
    report["git"]["repository"] = str(tmp_path)

    class Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(command: list[str], **_: object) -> Result:
        operation = command[3:]
        outputs = {
            ("status", "--porcelain"): " M file.txt",
            ("branch", "--show-current"): "main",
            ("rev-parse", "HEAD"): "abc",
            ("rev-parse", "origin/main"): "abc",
        }
        return Result(outputs.get(tuple(operation), ""))

    with patch.object(release_audit.subprocess, "run", side_effect=fake_run):
        errors = release_audit.validate(report, check_git=True)
    assert "working tree is not clean" in errors


def test_malformed_git_and_mismatched_tidy_path_fail() -> None:
    report = valid_report()
    report["git"] = None
    assert release_audit.validate(report)
    report = valid_report()
    report["tidy_audit"]["findings"][0]["path"] = "other.md"
    assert release_audit.validate(report)


def test_boolean_counts_are_rejected() -> None:
    report = valid_report()
    report["inventory"]["before"]["files"] = True
    report["coverage"]["delete"]["paths_verified"] = True
    assert len(release_audit.validate(report)) >= 2
