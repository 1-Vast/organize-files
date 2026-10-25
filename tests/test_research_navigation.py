"""Navigation candidates are not scientific conclusions."""
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("nav", Path(__file__).parents[1] / "scripts/research_navigation.py")
nav = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nav)


def test_wrong_chapter_is_review_candidate(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "log").mkdir()
    report = tmp_path / "log/RESEARCH_REPORT.md"
    report.write_text("# Report\n## Knowledge\n`study_a` is scoped.\n## Feedback\n`study_b` is negative.\n", encoding="utf-8")
    index = tmp_path / "log/STUDY_INDEX.tsv"
    index.write_text("study\tthematic_report\nstudy_a\tRESEARCH_REPORT.md#feedback\nstudy_b\tRESEARCH_REPORT.md#feedback\n", encoding="utf-8")
    registry = tmp_path / "research/STUDIES.json"
    registry.write_text(json.dumps({"studies": [{"path": "study_a"}, {"path": "study_b"}]}), encoding="utf-8")
    found = nav.audit(index, report, registry)
    assert len(found["needs_review"]) == 1
    assert found["needs_review"][0]["study"] == "study_a"
    assert found["needs_review"][0]["candidate_sections"] == ["knowledge"]


def test_unmentioned_id_not_automatically_wrong(tmp_path):
    report = tmp_path / "RESEARCH_REPORT.md"
    report.write_text("## Findings\nText summary omits exact identifier.\n", encoding="utf-8")
    index = tmp_path / "STUDY_INDEX.tsv"
    index.write_text("study\tthematic_report\nstudy_a\tRESEARCH_REPORT.md#findings\n", encoding="utf-8")
    result = nav.audit(index, report)
    assert not result["needs_review"]
    assert result["unassessable"][0]["reason"] == "study_id_not_explicit_in_report"
