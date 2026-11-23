"""Validate a machine-readable organization/release completion report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

STATUSES = {"PARTIAL", "COMPLETE", "BLOCKED"}
EXCLUSION_STATUSES = {"opaque-inventoried", "protected", "out-of-scope"}
OPERATION_OUTCOMES = {"verified", "retained", "deferred", "blocked", "failed"}

DISPOSITIONS = {
    "resolved",
    "retained_with_reason",
    "deferred",
    "blocked",
    "excluded",
    "unknown",
}


def _error(errors: list[str], message: str) -> None:
    errors.append(message)


def _is_under(path: str, parent: str) -> bool:
    try:
        child = Path(path).resolve()
        root = Path(parent).resolve()
        child.relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _scope_path(scope_root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else scope_root / candidate


def _validate_inventory(errors: list[str], inventory: object) -> None:
    if not isinstance(inventory, dict):
        _error(errors, "inventory.before and inventory.after are required")
        return
    required = {"files", "dirs", "bytes", "root_entries"}
    for label in ("before", "after"):
        item = inventory.get(label)
        if not isinstance(item, dict) or not required.issubset(item):
            _error(errors, f"inventory.{label} needs files, dirs, bytes and root_entries")
            continue
        for key in required:
            if type(item[key]) is not int or item[key] < 0:
                _error(errors, f"inventory.{label}.{key} must be a non-negative integer")


def _validate_git(errors: list[str], git: object, *, check_git: bool, scope: object) -> None:
    if not isinstance(git, dict):
        _error(errors, "git must be an object")
        return
    for key in ("branch", "commit", "remote_commit", "clean"):
        if key not in git:
            _error(errors, f"git.{key} is required")
    if "clean" in git and not isinstance(git["clean"], bool):
        _error(errors, "git.clean must be boolean")
    if git.get("commit") != git.get("remote_commit"):
        _error(errors, "accepted commit does not match remote commit")
    if check_git:
        repository = git.get("repository")
        if not repository and isinstance(scope, dict):
            repository = scope.get("repository") or scope.get("root")
        if not isinstance(repository, str) or not Path(repository).is_dir():
            _error(errors, "git.repository or scope.repository must identify a real repository")
            return
        def run(*args: str) -> str | None:
            result = subprocess.run(
                ["git", "-C", repository, *args],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                _error(errors, f"git command failed: {' '.join(args)}")
                return None
            return result.stdout.strip()
        actual_status = run("status", "--porcelain")
        actual_branch = run("branch", "--show-current")
        actual_commit = run("rev-parse", "HEAD")
        actual_remote = run("rev-parse", f"origin/{git.get('branch', '')}")
        if actual_status is not None and actual_status:
            _error(errors, "working tree is not clean")
        if actual_branch is not None and actual_branch != git.get("branch"):
            _error(errors, "reported branch does not match the working tree")
        if actual_commit is not None and actual_commit != git.get("commit"):
            _error(errors, "reported commit does not match HEAD")
        if actual_remote is not None and actual_remote != git.get("remote_commit"):
            _error(errors, "reported remote commit does not match origin")


def validate(report: dict, *, check_git: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be a JSON object"]
    if report.get("schema") != 1:
        _error(errors, "schema must be 1")
    scope = report.get("scope")
    if not isinstance(scope, dict) or not Path(scope.get("root", "")).is_absolute():
        _error(errors, "scope.root must be an absolute path")
    exclusions = scope.get("exclusions") if isinstance(scope, dict) else None
    if not isinstance(exclusions, list):
        _error(errors, "scope.exclusions must be a list")
    else:
        for index, item in enumerate(exclusions):
            if not isinstance(item, dict) or not item.get("path") or item.get("status") not in EXCLUSION_STATUSES or not item.get("reason"):
                _error(errors, f"exclusions[{index}] needs path, status and reason")
    scope_root = Path(scope.get("root", "")).resolve() if isinstance(scope, dict) else Path()
    if not scope_root.is_dir():
        _error(errors, "scope.root must identify an existing directory")

    _validate_inventory(errors, report.get("inventory"))

    findings = report.get("findings")
    if not isinstance(findings, list):
        _error(errors, "findings must be a list")
    else:
        seen: set[str] = set()
        exclusion_paths = [
            item["path"] for item in exclusions
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ] if isinstance(exclusions, list) else []
        for index, item in enumerate(findings):
            if not isinstance(item, dict) or not item.get("id") or item.get("id") in seen:
                _error(errors, f"findings[{index}] needs a unique id")
                continue
            seen.add(item["id"])
            if not isinstance(item.get("path"), str) or not item["path"]:
                _error(errors, f"findings[{index}] needs a path")
            if item.get("disposition") not in DISPOSITIONS:
                _error(errors, f"findings[{index}] has an invalid disposition")
            if item.get("disposition") in {"resolved", "retained_with_reason", "deferred", "blocked", "unknown"} and not item.get("evidence"):
                _error(errors, f"findings[{index}] needs evidence")
            if item.get("disposition") == "excluded" and not any(
                _is_under(str(_scope_path(scope_root, item.get("path", ""))), str(_scope_path(scope_root, excluded_path)))
                for excluded_path in exclusion_paths
            ):
                _error(errors, f"findings[{index}] excluded path is not covered by scope.exclusions")

    for key in ("operations", "links", "tests", "git", "review", "recovery", "coverage", "tidy_audit"):
        if key not in report:
            _error(errors, f"{key} is required")
    operations = report.get("operations")
    if not isinstance(operations, list) or not operations:
        _error(errors, "operations must be a non-empty list")
    elif any(
        not isinstance(item, dict)
        or not item.get("op")
        or item.get("outcome") not in OPERATION_OUTCOMES
        or not item.get("source")
        for item in operations
    ):
        _error(errors, "each operation needs op and outcome")
    links = report.get("links")
    if not isinstance(links, dict) or type(links.get("checked")) is not int or links.get("checked", 0) <= 0 or links.get("broken"):
        _error(errors, "links must contain a positive checked count and no broken links")
    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        _error(errors, "tests must be a non-empty list")
    else:
        for index, item in enumerate(tests):
            if not isinstance(item, dict) or not item.get("command") or type(item.get("returncode")) is not int or item.get("returncode") != 0:
                _error(errors, f"tests[{index}] did not pass")
    recovery = report.get("recovery")
    if not isinstance(recovery, dict) or not recovery.get("manifest") or recovery.get("verified") is not True:
        _error(errors, "recovery needs a manifest and verified=true")
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        _error(errors, "coverage is required")
    else:
        for key in ("findings", "archive", "delete"):
            item = coverage.get(key)
            if not isinstance(item, dict) or not item.get("manifest") or item.get("verified") is not True:
                _error(errors, f"coverage.{key} needs a manifest and verified=true")
            elif not _scope_path(scope_root, item["manifest"]).is_file():
                _error(errors, f"coverage.{key}.manifest does not exist")
        findings_coverage = coverage.get("findings")
        if isinstance(findings_coverage, dict) and (
            type(findings_coverage.get("dispositioned")) is not int
            or findings_coverage.get("dispositioned", 0) < 0
        ):
            _error(errors, "coverage.findings.dispositioned must be a non-negative integer")
        archive_coverage = coverage.get("archive")
        if isinstance(archive_coverage, dict) and (
            type(archive_coverage.get("paths_verified")) is not int
            or archive_coverage.get("paths_verified", 0) < 0
        ):
            _error(errors, "coverage.archive.paths_verified must be a non-negative integer")
        delete_coverage = coverage.get("delete")
        if isinstance(delete_coverage, dict) and any(
            type(delete_coverage.get(key)) is not int or delete_coverage.get(key, 0) < 0
            for key in ("paths_verified", "bytes_removed_verified")
        ):
            _error(errors, "coverage.delete needs non-negative paths_verified and bytes_removed_verified")
    tidy_audit = report.get("tidy_audit")
    tidy_ids: set[str] = set()
    if not isinstance(tidy_audit, dict) or tidy_audit.get("root") != str(scope_root) or not isinstance(tidy_audit.get("findings"), list):
        _error(errors, "tidy_audit.findings is required")
    else:
        for index, item in enumerate(tidy_audit["findings"]):
            if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
                _error(errors, f"tidy_audit.findings[{index}] needs id and path")
            else:
                tidy_ids.add(item["id"])
    if isinstance(findings, list) and tidy_ids:
        finding_ids = {item.get("id") for item in findings if isinstance(item, dict)}
        missing = sorted(tidy_ids - finding_ids)
        if missing:
            _error(errors, f"tidy_audit findings missing dispositions: {', '.join(missing)}")
        if finding_ids - tidy_ids:
            _error(errors, "findings contain ids absent from tidy_audit")
        tidy_by_id = {
            item["id"]: item["path"] for item in tidy_audit["findings"]
            if isinstance(item, dict) and item.get("id") and item.get("path")
        }
        for item in findings:
            if isinstance(item, dict) and item.get("id") in tidy_by_id and item.get("path") != tidy_by_id[item["id"]]:
                _error(errors, f"finding path does not match tidy_audit for {item['id']}")
    for key in ("recovery",):
        item = report.get(key)
        if isinstance(item, dict) and isinstance(item.get("manifest"), str):
            if not _scope_path(scope_root, item["manifest"]).is_file():
                _error(errors, f"{key}.manifest does not exist")
    _validate_git(errors, report.get("git"), check_git=check_git, scope=scope)
    review = report.get("review")
    if not isinstance(review, dict) or not review.get("independent_reviewer") or review.get("verdict") != "PASS":
        _error(errors, "independent review must have a reviewer and PASS verdict")
    if report.get("status") not in STATUSES:
        _error(errors, "status must be PARTIAL, COMPLETE or BLOCKED")
    if report.get("status") == "COMPLETE":
        if report.get("unresolved"):
            _error(errors, "COMPLETE report cannot contain unresolved items")
        if isinstance(findings, list) and any(
            item.get("disposition") not in {"resolved", "retained_with_reason"}
            for item in findings if isinstance(item, dict)
        ):
            _error(errors, "COMPLETE report cannot contain deferred, blocked, excluded or unknown findings")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--check-git", action="store_true")
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    errors = validate(report, check_git=args.check_git)
    result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
