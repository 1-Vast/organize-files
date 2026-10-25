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
    names = ["sealed_source/outcomes.csv", ".env", "credentials.txt", "private.key", "api_key.json", ".git/config", "declared.csv", "excluded/data.csv"]
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
