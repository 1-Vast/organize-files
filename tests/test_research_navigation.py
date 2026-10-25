"""Navigation candidates are not scientific conclusions."""
import importlib.util
import json
from pathlib import Path

import pytest

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


def audit_text(tmp_path, markdown, anchor):
    report = tmp_path / "REPORT.md"
    report.write_text(markdown, encoding="utf-8")
    index = tmp_path / "INDEX.tsv"
    index.write_text(f"study\tthematic_report\nstudy_a\tREPORT.md#{anchor}\n", encoding="utf-8")
    before = (report.read_bytes(), index.read_bytes())
    result = nav.audit(index, report)
    assert (report.read_bytes(), index.read_bytes()) == before
    return result


@pytest.mark.parametrize("fence", ["```", "~~~", "   ````python"])
def test_fenced_headings_are_not_navigation_targets(tmp_path, fence):
    closing = "~~~~" if "~" in fence else "`````"
    found = audit_text(tmp_path, f"{fence}\n## Fake\nstudy_a\n{closing}\n## Real\nstudy_a\n", "fake")
    assert found["missing_anchors"][0]["anchor"] == "fake"
    assert [section["slug"] for section in nav.headings(f"{fence}\n## Fake\n{closing}\n## Real\n")] == ["real"]


def test_fenced_mention_does_not_validate_an_unrelated_chapter(tmp_path):
    found = audit_text(tmp_path, "## Wrong\n```text\n`study_a`\n```\n## Right\nstudy_a is scoped.\n", "wrong")
    assert found["needs_review"][0]["candidate_sections"] == ["right"]


def test_only_fenced_mentions_remain_unassessable(tmp_path):
    found = audit_text(tmp_path, "## Findings\n~~~\nstudy_a\n~~~\n", "findings")
    assert not found["needs_review"]
    assert found["unassessable"][0]["reason"] == "study_id_not_explicit_in_report"


def test_short_or_wrong_fences_do_not_close_a_code_block(tmp_path):
    markdown = "## Wrong\n````\n```\nstudy_a\n~~~~\n## Fake\n````\n## Right\nstudy_a\n"
    found = audit_text(tmp_path, markdown, "wrong")
    assert found["needs_review"][0]["candidate_sections"] == ["right"]
    assert [section["slug"] for section in nav.headings(markdown)] == ["wrong", "right"]


def test_repeated_heading_anchor_selects_the_actual_occurrence(tmp_path):
    markdown = "## Findings\nOther work.\n## Findings\nstudy_a is negative.\n"
    assert not audit_text(tmp_path, markdown, "findings-1")["needs_review"]
    found = audit_text(tmp_path, markdown, "findings")
    assert found["needs_review"][0]["candidate_sections"] == ["findings-1"]


def test_generated_heading_slugs_do_not_collide_with_literal_suffixes():
    sections = nav.headings("## A\n## A\n## A-1\n   ## A\n")
    assert [section["slug"] for section in sections] == ["a", "a-1", "a-1-1", "a-2"]


@pytest.mark.parametrize("mention", ["study_a.", "**study_a**", "`study_a`", "(study_a)"])
def test_exact_ids_do_not_require_backticks(tmp_path, mention):
    found = audit_text(tmp_path, f"## Findings\n{mention}\n", "findings")
    assert found["checked_exact_id_rows"] == 1
    assert not found["needs_review"] and not found["unassessable"]


@pytest.mark.parametrize("other", ["study_a_suffix", "prefix_study_a", "other-study_a", "log/study_a/REPORT.md"])
def test_longer_ids_and_source_paths_are_not_study_mentions(tmp_path, other):
    found = audit_text(tmp_path, f"## Wrong\n{other}\n## Right\nstudy_a\n", "wrong")
    assert found["needs_review"][0]["candidate_sections"] == ["right"]


def test_a_cross_chapter_reference_is_not_automatically_rewritten(tmp_path):
    found = audit_text(tmp_path, "## Methods\nstudy_a supplies this contract.\n## Results\n`study_a` failed.\n", "methods")
    assert not found["needs_review"]
    assert not found["unassessable"]
    assert "no claim correctness" in found["scope"]
