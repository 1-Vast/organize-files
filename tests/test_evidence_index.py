"""Selected evidence bindings and incremental scope, not scientific-truth tests."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("evidence_index", Path(__file__).parents[1] / "scripts/evidence_index.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def index():
    return {"schema_version": 1, "objects": [
        {"id": "experiment", "kind": "experiment", "status": "negative", "stage": "exploration", "sources": [{"path": "result.json"}]},
        {"id": "claim", "kind": "conclusion", "status": "stopped"},
        {"id": "report", "kind": "report", "status": "maintained", "sources": [{"path": "report.md"}]},
        {"id": "unrelated", "kind": "claim", "status": "supported"}],
        "relations": [{"from": "experiment", "to": "claim", "type": "contradicts"},
                      {"from": "report", "to": "claim", "type": "depends_on"}]}


def files(root):
    (root / "result.json").write_text('{"value": -0.02}', encoding="utf-8")
    (root / "report.md").write_text("Scoped negative result", encoding="utf-8")


def test_change_only_invalidates_its_dependency_closure(tmp_path):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    (tmp_path / "result.json").write_text('{"value": -0.03}', encoding="utf-8")
    result = tool.impact(before, tool.snapshot_index(index(), tmp_path))
    assert result["direct_changes"] == ["experiment"]
    assert result["affected_objects"] == ["claim", "report"]
    assert result["reusable_objects"] == ["unrelated"]


def test_source_deletion_is_visible_without_inventing_a_negative_result(tmp_path):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    (tmp_path / "result.json").unlink()
    after = tool.snapshot_index(index(), tmp_path)
    assert after["errors"] == [{"path": "result.json", "error": "missing"}]
    assert tool.impact(before, after)["source_changes"] == [{"path": "result.json", "change": "removed"}]
    assert after["objects"][1]["status"] == "negative"


def test_duplicate_ids_and_dangling_relations_fail(tmp_path):
    data = index()
    data["objects"].append(copy.deepcopy(data["objects"][0]))
    assert "Duplicate" in tool.validate_index(data, tmp_path)["errors"][0]
    data = index()
    data["relations"][0]["to"] = "missing"
    assert "Dangling" in tool.validate_index(data, tmp_path)["errors"][0]


def test_declared_hash_mismatch_and_current_hash(tmp_path):
    files(tmp_path)
    data = index()
    data["objects"][0]["sources"][0]["sha256"] = "0" * 64
    assert tool.validate_index(data, tmp_path)["errors"][0]["error"] == "sha256_mismatch"
    data["objects"][0]["sources"][0]["sha256"] = hashlib.sha256((tmp_path / "result.json").read_bytes()).hexdigest()
    assert tool.validate_index(data, tmp_path)["valid"]


@pytest.mark.parametrize("error", ["missing", "sha256_mismatch"])
def test_unchanged_invalid_source_still_requires_dependency_review(tmp_path, error):
    files(tmp_path)
    data = index()
    if error == "missing":
        (tmp_path / "result.json").unlink()
    else:
        data["objects"][0]["sources"][0]["sha256"] = "0" * 64
    before = tool.snapshot_index(data, tmp_path)
    after = tool.snapshot_index(data, tmp_path)
    result = tool.impact(before, after)
    assert result["source_changes"] == []
    assert result["direct_changes"] == []
    assert result["invalid_objects"] == ["experiment"]
    assert result["affected_objects"] == ["claim", "report"]
    assert result["review_required"] == ["claim", "experiment", "report"]
    assert result["reusable_objects"] == ["unrelated"]


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "dir\\file", "dir/../file", "data.txt:stream", "innocent.csv.", ".git./config", "directory /result", "NUL.txt", "dir/COM1"])
def test_path_escape_rejected(tmp_path, name):
    data = index()
    data["objects"][0]["sources"][0]["path"] = name
    assert not tool.validate_index(data, tmp_path)["valid"]


def test_protected_payloads_are_never_opened(tmp_path, monkeypatch):
    names = ["sealed_source/outcomes.csv", ".env", "credentials.txt", "private.key", "api_key.json", ".git/config", "declared.csv", "excluded/data.csv",
             ".npmrc", ".pypirc", "nested/.NPMRC", "nested/.PYPIRC", "nested/.hg/store", "nested/.svn/entries"]
    data = {"schema_version": 1, "objects": [{"id": "x", "kind": "source", "status": "qualified_metadata_only", "sources": [
        {"path": name, **({"protected": True} if name == "declared.csv" else {})} for name in names]}], "excluded_sources": ["excluded"]}
    def forbidden(*args, **kwargs):
        raise AssertionError("Protected source payload opened")
    monkeypatch.setattr(Path, "open", forbidden)
    snapshot = tool.snapshot_index(data, tmp_path)
    assert len(snapshot["unverified_sources"]) == len(names)
    assert all(item["state"] == "unverified" for item in snapshot["sources"].values())


def test_protection_is_global_when_file_is_shared(tmp_path, monkeypatch):
    data = {"schema_version": 1, "objects": [
        {"id": "a", "kind": "x", "status": "x", "sources": [{"path": "payload.csv"}]},
        {"id": "b", "kind": "x", "status": "x", "sources": [{"path": "payload.csv", "protected": True}]}]}
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Opened shared protected payload"))
    assert tool.snapshot_index(data, tmp_path)["sources"]["payload.csv"]["state"] == "unverified"


def test_linked_directory_is_not_followed(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "result.json").write_text("data", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Link creation unavailable")
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    try:
        data = index()
        data["objects"][0]["sources"][0]["path"] = "linked/result.json"
        assert "Linked" in tool.validate_index(data, tmp_path)["errors"][0]
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_root_link_and_linked_ancestor_are_rejected_before_reading(tmp_path, monkeypatch):
    target = tmp_path / "external"
    target.mkdir()
    (target / "child").mkdir()
    link = tmp_path / "root_link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Link creation unavailable")
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    try:
        monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Linked root payload opened"))
        for root in (link, link / "child"):
            result = tool.validate_index(index(), root)
            assert not result["valid"]
            assert "root and its ancestors" in result["errors"][0]
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_hard_link_cannot_bypass_protected_name(tmp_path, monkeypatch):
    secret = tmp_path / ".env"
    secret.write_text("secret payload", encoding="utf-8")
    (tmp_path / "result.json").hardlink_to(secret)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Hard-linked protected payload opened"))
    result = tool.validate_index(index(), tmp_path)
    assert not result["valid"]
    assert "Hard-linked" in result["errors"][0]


def test_added_correction_and_relation_update_require_review(tmp_path):
    files(tmp_path)
    data = index()
    before = tool.snapshot_index(data, tmp_path)
    data["objects"].append({"id": "correction", "kind": "audit", "status": "confirmed"})
    data["relations"].append({"from": "correction", "to": "claim", "type": "supersedes"})
    result = tool.impact(before, tool.snapshot_index(data, tmp_path))
    assert result["direct_changes"] == ["claim", "correction"]
    assert result["affected_objects"] == ["report"]
    assert result["reusable_objects"] == ["experiment", "unrelated"]


def test_snapshot_does_not_change_when_input_is_edited(tmp_path):
    files(tmp_path)
    data = index()
    before = tool.snapshot_index(data, tmp_path)
    data["objects"][0]["status"] = "amended"
    result = tool.impact(before, tool.snapshot_index(data, tmp_path))
    assert result["direct_changes"] == ["experiment"]
    assert before["objects"][1]["status"] == "negative"


def test_cycles_terminate_and_all_relation_directions_work(tmp_path):
    files(tmp_path)
    data = index()
    data["relations"] += [{"from": "claim", "to": "experiment", "type": "supports"}]
    before = tool.snapshot_index(data, tmp_path)
    (tmp_path / "result.json").write_text("changed", encoding="utf-8")
    assert tool.impact(before, tool.snapshot_index(data, tmp_path))["review_required"] == ["claim", "experiment", "report"]


def test_cli_round_trip_and_invalid_exit(tmp_path, capsys):
    files(tmp_path)
    source, before, after = (tmp_path / name for name in ("index.json", "before.json", "after.json"))
    source.write_text(json.dumps(index()), encoding="utf-8")
    assert tool.main(["validate", "--index", str(source), "--root", str(tmp_path)]) == 0
    assert tool.main(["snapshot", "--index", str(source), "--root", str(tmp_path), "--out", str(before)]) == 0
    (tmp_path / "result.json").unlink()
    assert tool.main(["snapshot", "--index", str(source), "--root", str(tmp_path), "--out", str(after)]) == 1
    assert tool.main(["impact", "--before", str(before), "--after", str(after)]) == 0
    assert '"review_required"' in capsys.readouterr().out


def test_scan_avoids_large_payload_reads_but_does_not_verify_candidates(tmp_path, monkeypatch):
    files(tmp_path)
    (tmp_path / "result.json").write_bytes(b"research evidence\n" * (1024 * 1024))
    before = tool.snapshot_index(index(), tmp_path)
    strict_again = tool.snapshot_index(index(), tmp_path)
    expected_bytes = sum((tmp_path / name).stat().st_size for name in ("result.json", "report.md"))
    for snapshot in (before, strict_again):
        assert snapshot["metrics"]["payload_bytes_read"] == expected_bytes
        assert snapshot["metrics"]["payload_files_opened"] == 2
        assert snapshot["metrics"]["sha256_computations"] == 2
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Metadata scan opened payload"))
    result = tool.scan_index(index(), tmp_path, before)
    assert result["candidate_sources"] == ["report.md", "result.json"]
    assert result["changed_sources"] == []
    assert result["needs_strict_verification"] == result["candidate_sources"]
    assert result["verified_sources"] == 0
    assert result["unverified_objects"] == ["claim", "experiment", "report", "unrelated"]
    assert "reusable_objects" not in result
    assert all(source["state"] == "unverified" and "sha256" not in source for source in result["sources"].values())
    assert result["metrics"] == {"payload_bytes_read": 0, "payload_files_opened": 0,
                                 "sha256_computations": 0, "source_stat_calls": 2}


def test_scan_classifies_changes_and_requires_a_matching_root_baseline(tmp_path):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    (tmp_path / "result.json").write_text("larger changed result", encoding="utf-8")
    (tmp_path / "new.csv").write_text("new evidence", encoding="utf-8")
    data = index()
    data["objects"][2]["sources"] = [{"path": "new.csv"}]
    result = tool.scan_index(data, tmp_path, before)
    assert {row["path"]: row["change"] for row in result["changed_sources"]} == {
        "result.json": "metadata_changed", "new.csv": "new", "report.md": "removed_from_index"}
    assert result["needs_strict_verification"] == ["new.csv", "result.json"]
    before["root"] = str(tmp_path / "different_root")
    no_baseline = tool.scan_index(index(), tmp_path, before)
    assert not no_baseline["candidate_sources"]
    assert all(row["change"] == "baseline_unavailable" for row in no_baseline["changed_sources"])


def test_same_size_same_mtime_mutation_is_not_trusted_by_scan(tmp_path):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    target = tmp_path / "result.json"
    original = target.stat()
    target.write_text('{"value": -0.03}', encoding="utf-8")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert target.stat().st_size == before["sources"]["result.json"]["bytes"]
    assert target.stat().st_mtime_ns == original.st_mtime_ns
    scan = tool.scan_index(index(), tmp_path, before)
    # Some filesystems expose the write through ctime; others preserve creation
    # time. Either result remains unverified and requires a fresh strict read.
    assert scan["sources"]["result.json"]["state"] == "unverified"
    assert "result.json" in scan["needs_strict_verification"]
    strict = tool.snapshot_index(index(), tmp_path)
    assert strict["sources"]["result.json"]["sha256"] != before["sources"]["result.json"]["sha256"]
    assert tool.impact(before, strict)["review_required"] == ["claim", "experiment", "report"]


def test_identical_metadata_observations_can_hide_different_content(tmp_path, monkeypatch):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    (tmp_path / "result.json").write_text('{"value": -0.03}', encoding="utf-8")
    observe = tool.file_metadata

    def repeated_metadata(path, metrics):
        actual = observe(path, metrics)
        # Model a filesystem/copy operation that repeats every observed identity
        # field. The scan must still avoid claiming content equality.
        return before["sources"]["result.json"]["metadata"] if path.name == "result.json" else actual

    monkeypatch.setattr(tool, "file_metadata", repeated_metadata)
    scan = tool.scan_index(index(), tmp_path, before)
    assert "result.json" in scan["candidate_sources"]
    assert scan["verified_sources"] == 0
    with pytest.raises(ValueError, match="strict_hash"):
        tool.impact(before, scan)
    strict = tool.snapshot_index(index(), tmp_path)
    assert tool.impact(before, strict)["direct_changes"] == ["experiment"]


def test_scan_missing_sources_and_protected_payloads(tmp_path, monkeypatch):
    data = index()
    names = ["sealed_source/outcomes.csv", ".env", "credentials.txt", "private.key", ".git/config", "declared.csv", "excluded/data.csv"]
    data["objects"][2]["sources"] = [{"path": name, **({"protected": True} if name == "declared.csv" else {})} for name in names]
    data["excluded_sources"] = ["excluded"]
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Protected or missing payload opened"))
    scan = tool.scan_index(data, tmp_path)
    assert scan["errors"] == [{"path": "result.json", "error": "missing"}]
    assert scan["changed_sources"] == [{"path": "result.json", "change": "missing"}]
    assert scan["needs_strict_verification"] == ["result.json"]
    assert all(scan["sources"][name]["state"] == "unverified" for name in names)
    assert scan["metrics"]["payload_bytes_read"] == 0
    assert scan["metrics"]["source_stat_calls"] == 1


def test_metadata_changes_without_content_changes_do_not_invalidate_strict_impact(tmp_path):
    files(tmp_path)
    before = tool.snapshot_index(index(), tmp_path)
    target = tmp_path / "result.json"
    info = target.stat()
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000))
    assert {row["path"] for row in tool.scan_index(index(), tmp_path, before)["changed_sources"]} == {"result.json"}
    result = tool.impact(before, tool.snapshot_index(index(), tmp_path))
    assert result["source_changes"] == []
    assert result["review_required"] == []


def test_protected_dependencies_never_appear_reusable_in_strict_impact(tmp_path):
    files(tmp_path)
    data = index()
    data["objects"][0]["sources"][0]["protected"] = True
    before = tool.snapshot_index(data, tmp_path)
    result = tool.impact(before, tool.snapshot_index(data, tmp_path))
    assert result["unverified_objects"] == ["claim", "experiment", "report"]
    assert result["review_required"] == ["claim", "experiment", "report"]
    assert result["reusable_objects"] == ["unrelated"]


def test_shared_sources_are_hashed_once_and_mismatch_is_not_verified(tmp_path):
    files(tmp_path)
    data = index()
    data["objects"][2]["sources"].append({"path": "result.json", "sha256": "0" * 64})
    result = tool.validate_index(data, tmp_path)
    assert not result["valid"]
    assert result["verified_sources"] == 1
    assert result["metrics"]["payload_files_opened"] == 2
    assert result["metrics"]["sha256_computations"] == 2


def test_scan_cli_and_rejected_scan_impact(tmp_path, capsys):
    files(tmp_path)
    source, before, scanned = (tmp_path / name for name in ("index.json", "strict.json", "scan.json"))
    source.write_text(json.dumps(index()), encoding="utf-8")
    assert tool.main(["snapshot", "--index", str(source), "--root", str(tmp_path), "--out", str(before)]) == 0
    assert tool.main(["scan", "--index", str(source), "--root", str(tmp_path), "--previous", str(before), "--out", str(scanned)]) == 0
    result = json.loads(scanned.read_text(encoding="utf-8"))
    assert result["verification_mode"] == "metadata_only"
    assert result["metrics"]["payload_bytes_read"] == 0
    with pytest.raises(SystemExit) as error:
        tool.main(["impact", "--before", str(before), "--after", str(scanned)])
    assert error.value.code == 2
    assert "metadata scans cannot establish reusable" in capsys.readouterr().err


@pytest.mark.parametrize("directory", ["sealed_source", "blind_holdout", ".ENV", ".git", "credentials"])
@pytest.mark.parametrize("child", [False, True])
def test_sensitive_root_and_ancestors_are_rejected_before_payload_access(tmp_path, monkeypatch, directory, child):
    root = tmp_path / directory
    if child:
        root /= "study"
    root.mkdir(parents=True)
    (root / "payload.csv").write_bytes(b"fixture only")
    data = {"schema_version": 1, "objects": [
        {"id": "x", "kind": "source", "status": "fixture", "sources": [{"path": "payload.csv"}]}]}
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Sensitive root payload opened"))
    for operation in (tool.snapshot_index, tool.scan_index):
        with pytest.raises(ValueError, match="protected or managed"):
            operation(data, root)
    result = tool.validate_index(data, root)
    assert not result["valid"]
    assert result["metrics"]["payload_bytes_read"] == 0
    assert result["metrics"]["payload_files_opened"] == 0


def test_failed_validation_preserves_io_metrics_for_prior_payload_reads(tmp_path):
    (tmp_path / "ok.txt").write_bytes(b"five!")
    (tmp_path / "directory").mkdir()
    data = {"schema_version": 1, "objects": [
        {"id": "x", "kind": "source", "status": "fixture", "sources": [
            {"path": "ok.txt"}, {"path": "directory"}]}]}
    result = tool.validate_index(data, tmp_path)
    assert not result["valid"]
    assert result["verified_sources"] == 0
    assert "not a regular file" in result["errors"][0]
    assert result["metrics"] == {"payload_bytes_read": 5, "payload_files_opened": 1,
                                 "sha256_computations": 1, "source_stat_calls": 3}
    assert "path-safety checks" in result["metrics_scope"]


@pytest.mark.parametrize("location", ["root", "ancestor", "intermediate"])
def test_reparse_points_are_rejected_without_isjunction_api(tmp_path, monkeypatch, location):
    from types import SimpleNamespace

    root = tmp_path / "project"
    (root / "inside").mkdir(parents=True)
    (root / "inside/result.json").write_bytes(b"fixture only")
    flagged = root if location == "root" else tmp_path if location == "ancestor" else root / "inside"
    original = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == flagged:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.delattr(os.path, "isjunction", raising=False)
    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Reparse-point payload opened"))
    data = {"schema_version": 1, "objects": [
        {"id": "x", "kind": "source", "status": "fixture", "sources": [{"path": "inside/result.json"}]}]}
    for operation in (tool.snapshot_index, tool.scan_index):
        with pytest.raises(ValueError, match="[Ll]inked"):
            operation(data, root)
    result = tool.validate_index(data, root)
    assert not result["valid"]
    assert result["metrics"]["payload_files_opened"] == 0


def test_missing_source_is_still_reported_without_isjunction_api(tmp_path, monkeypatch):
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    data = {"schema_version": 1, "objects": [
        {"id": "x", "kind": "source", "status": "fixture", "sources": [{"path": "absent/result.json"}]}]}
    result = tool.snapshot_index(data, tmp_path)
    assert result["errors"] == [{"path": "absent/result.json", "error": "missing"}]
    assert result["metrics"]["payload_files_opened"] == 0



def test_retained_source_id_requires_review_without_reading_payload(tmp_path):
    files(tmp_path)
    data = index()
    data["objects"][1]["source_ids"] = ["log/research_records/example/DECISION.md"]
    before = tool.snapshot_index(data, tmp_path)
    after = tool.snapshot_index(data, tmp_path)
    assert before["unverified_source_ids"] == ["log/research_records/example/DECISION.md"]
    result = tool.impact(before, after)
    assert {"claim", "report"} <= set(result["unverified_objects"])
    assert "claim" not in result["reusable_objects"]


def test_source_id_validation_is_bounded(tmp_path):
    files(tmp_path)
    data = index()
    data["objects"][1]["source_ids"] = ["", 3]
    assert "source_ids" in tool.validate_index(data, tmp_path)["errors"][0]


def historical_index():
    data = index()
    data["objects"][0]["sources"] = []
    data["objects"][0]["source_ids"] = ["records/experiment/RESULT.md"]
    return data


def test_trusted_historical_bytes_are_hashed_and_changes_reach_dependent_claims(tmp_path):
    files(tmp_path)
    data = historical_index()
    payloads = {"records/experiment/RESULT.md": b"gain=-0.02"}
    before = tool.snapshot_index(data, tmp_path, source_resolver=payloads.__getitem__)
    payloads["records/experiment/RESULT.md"] = b"gain=-0.03"
    after = tool.snapshot_index(data, tmp_path, source_resolver=payloads.__getitem__)
    binding = after["source_id_bindings"]["records/experiment/RESULT.md"]
    assert binding["state"] == "present"
    assert binding["bytes"] == len(b"gain=-0.03")
    assert binding["sha256"] == hashlib.sha256(b"gain=-0.03").hexdigest()
    assert binding["representation"] == "trusted_resolver_bytes"
    assert after["unverified_source_ids"] == []
    assert after["verification_complete"]
    result = tool.impact(before, after)
    assert result["source_id_changes"] == [{"source_id": "records/experiment/RESULT.md", "change": "changed"}]
    assert result["direct_changes"] == ["experiment"]
    assert result["affected_objects"] == ["claim", "report"]
    assert result["reusable_objects"] == ["unrelated"]
    assert next(obj for obj in after["objects"] if obj["id"] == "experiment")["status"] == "negative"
    assert after["source_id_metrics"] == {"resolver_calls": 1, "resolver_failures": 0,
                                          "bytes_returned": 10, "sha256_computations": 1}


def test_unchanged_verified_historical_bytes_allow_only_structural_reuse(tmp_path):
    files(tmp_path)
    data = historical_index()
    resolver = lambda source_id: b"scoped negative evidence"
    before = tool.snapshot_index(data, tmp_path, source_resolver=resolver)
    after = tool.snapshot_index(data, tmp_path, source_resolver=resolver)
    result = tool.impact(before, after)
    assert result["source_id_changes"] == []
    assert result["unverified_objects"] == []
    assert result["review_required"] == []
    assert result["reusable_objects"] == ["claim", "experiment", "report", "unrelated"]
    assert "does not establish scientific validity" in result["scope"]
    validated = tool.validate_index(data, tmp_path, source_resolver=resolver)
    assert validated["valid"] and validated["verification_complete"]
    assert validated["verified_sources"] == 1
    assert validated["verified_source_ids"] == 1


def test_absent_resolver_does_not_import_repository_code_or_verify_source_ids(tmp_path):
    files(tmp_path)
    repo_tools = tmp_path / "tools"
    repo_tools.mkdir()
    (repo_tools / "retained_records.py").write_text("raise RuntimeError('must not import repository code')")
    data = historical_index()
    validated = tool.validate_index(data, tmp_path)
    assert validated["valid"]  # Schema/file checks pass; completeness is separate.
    assert not validated["verification_complete"]
    assert validated["verified_source_ids"] == 0
    assert validated["unverified_source_ids"] == ["records/experiment/RESULT.md"]
    assert validated["source_id_bindings"]["records/experiment/RESULT.md"]["reason"] == "no_trusted_resolver"
    assert validated["source_id_metrics"]["resolver_calls"] == 0
    result = tool.impact(tool.snapshot_index(data, tmp_path), tool.snapshot_index(data, tmp_path))
    assert result["unverified_objects"] == ["claim", "experiment", "report"]
    assert result["reusable_objects"] == ["unrelated"]


def test_historical_read_failure_preserves_prior_file_and_resolver_io(tmp_path):
    files(tmp_path)
    data = historical_index()
    data["objects"][0]["source_ids"] = ["records/a.md", "records/b.md"]

    def resolver(source_id):
        if source_id == "records/b.md":
            raise RuntimeError("storage reader failed after internal I/O")
        return b"five!"

    result = tool.validate_index(data, tmp_path, source_resolver=resolver)
    assert not result["valid"] and not result["verification_complete"]
    assert result["verified_source_ids"] == 1
    assert result["source_id_bindings"]["records/b.md"]["state"] == "unreadable"
    assert result["errors"] == [{"source_id": "records/b.md", "error": "source_id_unreadable", "error_type": "RuntimeError"}]
    assert result["metrics"]["payload_bytes_read"] == len((tmp_path / "report.md").read_bytes())
    assert result["metrics"]["sha256_computations"] == 1
    assert result["source_id_metrics"] == {"resolver_calls": 2, "resolver_failures": 1,
                                           "bytes_returned": 5, "sha256_computations": 1}
    assert "reads before an exception are not measured" in result["source_id_metrics_scope"]


@pytest.mark.parametrize("returned", ["text is not original bytes", {}, None])
def test_historical_resolver_must_return_exact_bytes(tmp_path, returned):
    files(tmp_path)
    result = tool.validate_index(historical_index(), tmp_path, source_resolver=lambda source_id: returned)
    assert not result["valid"]
    assert result["errors"][0]["error_type"] == "TypeError"
    assert result["verified_source_ids"] == 0
    assert result["source_id_metrics"] == {"resolver_calls": 1, "resolver_failures": 1,
                                           "bytes_returned": 0, "sha256_computations": 0}


def test_historical_source_ids_are_deduplicated_across_objects(tmp_path):
    files(tmp_path)
    data = historical_index()
    data["objects"][1]["source_ids"] = data["objects"][0]["source_ids"][:]
    calls = []

    def resolver(source_id):
        calls.append(source_id)
        return b"shared evidence"

    snapshot = tool.snapshot_index(data, tmp_path, source_resolver=resolver)
    assert calls == ["records/experiment/RESULT.md"]
    assert snapshot["source_id_metrics"]["resolver_calls"] == 1
    assert len(snapshot["source_id_bindings"]) == 1


def test_reserved_historical_ids_never_reach_a_resolver(tmp_path):
    files(tmp_path)
    data = historical_index()
    names = ["archive/sealed_source/results.csv", "archive/BLIND/results.csv", "credentials.json",
             "logs/.ENV", "records/.git./config", "records\\private.key", "RESERVED/outcome.md",
             ".npmrc", ".pypirc", "records/.NPMRC", "records\\.PYPIRC. "]
    data["objects"][0]["source_ids"] = names
    data["excluded_sources"] = ["reserved"]

    def forbidden(source_id):
        pytest.fail("Protected historical payload resolver was called")

    snapshot = tool.snapshot_index(data, tmp_path, source_resolver=forbidden)
    assert snapshot["errors"] == []
    assert set(snapshot["unverified_source_ids"]) == set(names)
    assert all(item["state"] == "unverified" for item in snapshot["source_id_bindings"].values())
    assert snapshot["source_id_metrics"]["resolver_calls"] == 0


def test_declared_file_protection_also_protects_matching_historical_id(tmp_path):
    files(tmp_path)
    data = historical_index()
    data["objects"][0]["source_ids"] = ["RESERVED.md", "reserved.md.", "reserved.md "]
    data["objects"][1]["sources"] = [{"path": "reserved.md", "protected": True}]
    snapshot = tool.snapshot_index(data, tmp_path, source_resolver=lambda sid: pytest.fail("Declared protection bypassed"))
    assert all(item["reason"] == "declared_protected" for item in snapshot["source_id_bindings"].values())
    assert snapshot["source_id_metrics"]["resolver_calls"] == 0


def test_scan_cannot_reuse_historical_bytes_or_resolve_previous_ids(tmp_path, monkeypatch):
    files(tmp_path)
    data = historical_index()
    before = tool.snapshot_index(data, tmp_path, source_resolver=lambda sid: b"trusted once")
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Scan opened a payload"))
    scan = tool.scan_index(data, tmp_path, before)
    assert scan["candidate_sources"] == ["report.md"]
    assert scan["needs_strict_source_id_verification"] == ["records/experiment/RESULT.md"]
    assert scan["source_id_bindings"]["records/experiment/RESULT.md"]["state"] == "unverified"
    assert "sha256" not in scan["source_id_bindings"]["records/experiment/RESULT.md"]
    assert scan["source_id_metrics"] == {"resolver_calls": 0, "resolver_failures": 0,
                                         "bytes_returned": 0, "sha256_computations": 0}
    assert scan["metrics"]["payload_bytes_read"] == 0
    assert not scan["verification_complete"]
    with pytest.raises(ValueError, match="strict_hash"):
        tool.impact(before, scan)


def test_lost_historical_access_still_requires_review_when_repeated(tmp_path):
    files(tmp_path)
    data = historical_index()
    before = tool.snapshot_index(data, tmp_path, source_resolver=lambda sid: b"old evidence")

    def missing(source_id):
        raise FileNotFoundError(source_id)

    after = tool.snapshot_index(data, tmp_path, source_resolver=missing)
    result = tool.impact(before, after)
    assert result["source_id_changes"] == [{"source_id": "records/experiment/RESULT.md", "change": "unreadable"}]
    assert result["invalid_objects"] == ["experiment"]
    assert result["review_required"] == ["claim", "experiment", "report"]
    repeated = tool.impact(after, tool.snapshot_index(data, tmp_path, source_resolver=missing))
    assert repeated["source_id_changes"] == []
    assert repeated["review_required"] == ["claim", "experiment", "report"]
    assert repeated["reusable_objects"] == ["unrelated"]


def test_rebinding_a_historical_id_requires_review_even_with_identical_bytes(tmp_path):
    files(tmp_path)
    data = historical_index()
    resolver = lambda sid: b"same bytes from a different evidence identity"
    before = tool.snapshot_index(data, tmp_path, source_resolver=resolver)
    data["objects"][0]["source_ids"] = ["records/replacement/RESULT.md"]
    result = tool.impact(before, tool.snapshot_index(data, tmp_path, source_resolver=resolver))
    assert result["direct_changes"] == ["experiment"]
    assert result["review_required"] == ["claim", "experiment", "report"]
    assert {row["change"] for row in result["source_id_changes"]} == {"removed", "added"}


def test_resolver_module_strings_are_rejected_without_loading_code(tmp_path):
    files(tmp_path)
    result = tool.validate_index(historical_index(), tmp_path, source_resolver="tools.retained_records.read_bytes")
    assert not result["valid"]
    assert "trusted callable" in result["errors"][0]
    assert result["metrics"]["payload_bytes_read"] == 0
    assert result["source_id_metrics"]["resolver_calls"] == 0
