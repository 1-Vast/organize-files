"""Check whether research index anchors lead to sections mentioning the indexed study.

This is a navigation heuristic, not scientific-semantic verification. It never
changes the report or treats a missing literal ID as proof of an incorrect claim.
Only explicitly provided index, report and optional registry files are read.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from urllib.parse import unquote, urldefrag

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def slugify(title: str) -> str:
    """Approximate common GitHub Markdown heading anchors for navigation screening."""
    title = title.lower().strip()
    title = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    return re.sub(r"\s+", "-", title)


def prose_lines(markdown: str) -> list[str]:
    """Mask fenced code without changing line positions used by the audit."""
    lines = markdown.splitlines()
    fence = None
    for i, line in enumerate(lines):
        match = FENCE.match(line)
        if fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines[i] = ""
        elif match and (match[1][0] != "`" or "`" not in match[2]):
            fence = match[1]
            lines[i] = ""
    return lines


def headings(markdown: str) -> list[dict]:
    lines = prose_lines(markdown)
    result = []
    used_slugs = set()
    for line_number, line in enumerate(lines):
        match = HEADING.match(line)
        if match:
            base = slugify(match[2])
            slug, suffix = base, 0
            while slug in used_slugs:
                suffix += 1
                slug = f"{base}-{suffix}"
            used_slugs.add(slug)
            result.append({"title": match[2].strip(), "slug": slug,
                           "level": len(match[1]), "start": line_number, "end": len(lines)})
    for i, item in enumerate(result):
        for following in result[i + 1:]:
            if following["level"] <= item["level"]:
                item["end"] = following["start"]
                break
    return result


def audit(index_path: Path, report_path: Path, registry_path: Path | None = None) -> dict:
    """Return candidates for human review; no automatic link rewrites."""
    index_path = index_path.resolve(strict=True)
    report_path = report_path.resolve(strict=True)
    markdown = report_path.read_text(encoding="utf-8-sig")
    lines = prose_lines(markdown)
    sections = headings(markdown)
    by_slug: dict[str, list[dict]] = {}
    for section in sections:
        by_slug.setdefault(section["slug"], []).append(section)

    registered = None
    if registry_path is not None:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        studies = data.get("studies")
        if not isinstance(studies, list):
            raise ValueError("Registry must include a studies list")
        registered = {item["path"] for item in studies if isinstance(item, dict)
                      and isinstance(item.get("path"), str)}
    with index_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows or not {"study", "thematic_report"}.issubset(rows[0]):
        raise ValueError("Index requires study and thematic_report columns")

    covered = set()
    needs_review = []
    unassessable = []
    missing_anchors = []
    checked = 0
    for row_number, row in enumerate(rows, start=2):
        study = row.get("study", "")
        if registered is not None and study not in registered:
            continue
        covered.add(study)
        url, anchor = urldefrag((row.get("thematic_report") or "").strip())
        if not url or not anchor:
            unassessable.append({"study": study, "line": row_number, "reason": "no_report_anchor"})
            continue
        # Only inspect the report explicitly supplied. Do not open files from index entries.
        if (index_path.parent / unquote(url)).resolve() != report_path:
            unassessable.append({"study": study, "line": row_number, "reason": "different_report"})
            continue
        targets = by_slug.get(unquote(anchor), [])
        if not targets:
            missing_anchors.append({"study": study, "line": row_number, "anchor": anchor})
            continue
        # Exact identifiers can appear in prose or inline code. Longer IDs and
        # source-path components do not establish a section's subject.
        token = re.compile(r"(?<![\w/-])" + re.escape(study) + r"(?![\w/-])")
        mentions = [i for i, line in enumerate(lines) if token.search(line)]
        if not mentions:
            unassessable.append({"study": study, "line": row_number,
                                 "reason": "study_id_not_explicit_in_report"})
            continue
        checked += 1
        if any(target["start"] <= i < target["end"] for target in targets for i in mentions):
            continue
        candidates = []
        for i in mentions:
            enclosing = [s for s in sections if s["start"] <= i < s["end"]]
            closest = max(enclosing, key=lambda s: s["level"], default=None)
            major = next((s for s in reversed(enclosing) if s["level"] == 2), closest)
            if major and major["slug"] not in candidates:
                candidates.append(major["slug"])
        needs_review.append({"study": study, "line": row_number, "anchor": anchor,
                             "candidate_sections": candidates,
                             "reason": "study_id_outside_linked_section"})

    absent = sorted(registered - covered) if registered is not None else []
    return {"index_rows": len(rows),
            "registered_studies": len(registered) if registered is not None else None,
            "checked_exact_id_rows": checked,
            "needs_review": needs_review, "missing_anchors": missing_anchors,
            "missing_registered_rows": absent, "unassessable": unassessable,
            "scope": "Checks ATX Markdown anchors and bounded literal study IDs outside fenced code. Heading slugs approximate GitHub behavior; prose without the ID remains unassessable. Review candidates against scientific content; no claim correctness or source coverage is established."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--strict", action="store_true", help="Return nonzero if review candidates remain")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.index, args.report, args.registry)
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        parser.exit(2, f"research_navigation: {error}\n")
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    failures = len(result["missing_anchors"]) + len(result["missing_registered_rows"])
    failures += len(result["needs_review"]) if args.strict else 0
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
