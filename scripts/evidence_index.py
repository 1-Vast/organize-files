"""Validate selected research objects and propagate changes requiring human/agent review.

Index schema (version 1): objects have stable id, kind, status, optional stage
(exploration/validated_method/formal_result), and sources [{path, sha256?, protected?}].
Relations {from, to, type} use supports/contradicts/supersedes or depends_on.
The first three propagate from -> to; depends_on propagates to -> from.
Project-relative excluded_sources prefixes and protected sources are declarations:
their payloads are never read. Strict snapshots hash every accessible indexed source.
Metadata scans only screen candidates and never verify content or authorize deletion.
This tool checks bindings, not scientific truth.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

RELATIONS = {"supports", "contradicts", "supersedes", "depends_on"}
STAGES = {"exploration", "validated_method", "formal_result"}
HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$)(?:\..*)?\Z", re.I)
PROTECTED = re.compile(r"sealed|blind|credential|secret|password|passwd|api[_-]?key|(?:^|[_-])token(?:[_.-]|$)", re.I)
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
SKIP_PARTS = {".git", ".ssh", ".venv", "venv", "gpu_venv", "node_modules", "__pycache__"}
METRICS_SCOPE = "Source payload reads/hashes and explicit source stat calls only; index JSON, path-safety checks and filesystem/OS caches are not measured."


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("Source paths must be nonempty project-relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError(f"Unsafe source path: {value}")
    if any(p != p.rstrip(" .") or DEVICE.fullmatch(p) or any(c in p for c in '<>"|?*') for p in value.split("/")):
        raise ValueError(f"Ambiguous or reserved source path: {value}")
    return value


def linked_path(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def checked_path(root, value):
    target = root
    for part in PurePosixPath(relative_path(value)).parts:
        target = target / part
        if linked_path(target):
            raise ValueError(f"Linked source paths are not followed: {value}")
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Source leaves the project root: {value}")
    return target


def checked_root(value):
    root = Path(value)
    if not root.is_absolute():
        root = Path.cwd() / root
    for part in reversed((root, *root.parents)):
        if linked_path(part):
            raise ValueError("Project root and its ancestors must not be linked paths")
        if part.name and exclusion_reason(part.name, []):
            raise ValueError("Project root and its ancestors must not be protected or managed paths")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be a directory")
    return root


def schema(index):
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise ValueError("Expected evidence index schema_version 1")
    objects, relations = index.get("objects"), index.get("relations", [])
    if not isinstance(objects, list) or not isinstance(relations, list):
        raise ValueError("objects and relations must be lists")
    excluded = index.get("excluded_sources", [])
    if not isinstance(excluded, list):
        raise ValueError("excluded_sources must be a list")
    for name in excluded:
        relative_path(name)
    ids = set()
    for obj in objects:
        if not isinstance(obj, dict) or any(not isinstance(obj.get(k), str) or not obj[k].strip() for k in ("id", "kind", "status")):
            raise ValueError("Every object needs nonempty id, kind and status strings")
        if obj["id"] in ids:
            raise ValueError(f"Duplicate object id: {obj['id']}")
        ids.add(obj["id"])
        if "stage" in obj and (not isinstance(obj["stage"], str) or obj["stage"] not in STAGES):
            raise ValueError(f"Unknown research stage on {obj['id']}")
        if not isinstance(obj.get("sources", []), list):
            raise ValueError(f"sources must be a list on {obj['id']}")
        seen = set()
        for source in obj.get("sources", []):
            if not isinstance(source, dict):
                raise ValueError("Sources must be objects with a path")
            name = relative_path(source.get("path"))
            if name in seen:
                raise ValueError(f"Duplicate source on {obj['id']}: {name}")
            seen.add(name)
            if "sha256" in source and (not isinstance(source["sha256"], str) or not HASH.fullmatch(source["sha256"])):
                raise ValueError(f"Invalid declared SHA256: {name}")
            if "protected" in source and not isinstance(source["protected"], bool):
                raise ValueError(f"protected must be boolean: {name}")
    for relation in relations:
        if not isinstance(relation, dict) or not isinstance(relation.get("type"), str) or relation["type"] not in RELATIONS:
            raise ValueError("Unknown evidence relation type")
        if not isinstance(relation.get("from"), str) or not isinstance(relation.get("to"), str) or relation["from"] not in ids or relation["to"] not in ids:
            raise ValueError(f"Dangling relation: {relation}")
    return objects, relations, excluded


def exclusion_reason(name, excluded):
    parts = PurePosixPath(name).parts
    if any(name.casefold() == p.casefold() or name.casefold().startswith(p.casefold() + "/") for p in excluded):
        return "explicitly_excluded"
    if any(p.lower() in SKIP_PARTS for p in parts):
        return "managed_state"
    if any(p.lower().startswith(".env") or PROTECTED.search(p) for p in parts):
        return "protected_name"
    if PurePosixPath(name).suffix.lower() in PRIVATE_SUFFIXES or PurePosixPath(name).name.lower() in {"id_rsa", "id_ed25519", "authorized_keys"}:
        return "credential_name"
    return None


def io_metrics():
    return {"payload_bytes_read": 0, "payload_files_opened": 0,
            "sha256_computations": 0, "source_stat_calls": 0}


def file_metadata(path, metrics):
    metrics["source_stat_calls"] += 1
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Indexed source is not a regular file: {path.name}")
    if info.st_nlink != 1:
        raise ValueError(f"Hard-linked sources are not read: {path.name}")
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns, "device": info.st_dev,
            "inode": info.st_ino, "mode": info.st_mode, "nlink": info.st_nlink}


def fingerprint(path, metrics):
    before = file_metadata(path, metrics)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        metrics["payload_files_opened"] += 1
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            metrics["payload_bytes_read"] += len(block)
            digest.update(block)
    metrics["sha256_computations"] += 1
    after = file_metadata(path, metrics)
    if before != after:
        raise ValueError(f"Source changed while hashing: {path.name}")
    return {"state": "present", "sha256": digest.hexdigest(),
            "bytes": after["size"], "metadata": after}


def snapshot_index(index, root):
    return inspect_index(index, root)


def scan_index(index, root, previous=None):
    """Screen metadata only; even candidates need strict hashing before reuse/deletion."""
    if previous is not None:
        schema(previous)
        if not isinstance(previous.get("sources"), dict):
            raise ValueError("Previous scan/snapshot must include sources")
    return inspect_index(index, root, metadata_only=True, previous=previous)


def inspect_index(index, root, metadata_only=False, previous=None, metrics=None):
    metrics = io_metrics() if metrics is None else metrics
    objects, relations, excluded = schema(index)
    root = checked_root(root)
    sources, errors, unverified = {}, [], []
    candidates, changes, needs_strict = [], [], []
    same_root = previous is not None and previous.get("root") == str(root)
    # One protected declaration protects the file globally, even when reused.
    protected = {s["path"].casefold() for obj in objects for s in obj.get("sources", []) if s.get("protected")}
    for obj in objects:
        for source in obj.get("sources", []):
            name = source["path"]
            reason = "declared_protected" if name.casefold() in protected else exclusion_reason(name, excluded)
            if name not in sources:
                if reason:
                    sources[name] = {"state": "unverified", "reason": reason}
                    unverified.append({"path": name, "reason": reason})
                else:
                    target = checked_path(root, name)
                    if metadata_only:
                        needs_strict.append(name)
                    try:
                        if metadata_only:
                            metadata = file_metadata(target, metrics)
                            old = previous.get("sources", {}).get(name) if same_root else None
                            if isinstance(old, dict) and old.get("metadata") == metadata:
                                classification = "candidate"
                                candidates.append(name)
                            else:
                                if same_root and old is None:
                                    classification = "new"
                                elif isinstance(old, dict) and "metadata" in old:
                                    classification = "metadata_changed"
                                else:
                                    classification = "baseline_unavailable"
                                changes.append({"path": name, "change": classification})
                            sources[name] = {"state": "unverified", "reason": "metadata_only",
                                             "classification": classification, "metadata": metadata}
                            unverified.append({"path": name, "reason": "metadata_only"})
                        else:
                            sources[name] = fingerprint(target, metrics)
                    except FileNotFoundError:
                        sources[name] = {"state": "missing"}
                        errors.append({"path": name, "error": "missing"})
                        if metadata_only:
                            changes.append({"path": name, "change": "missing"})
            expected = source.get("sha256")
            if expected and sources[name]["state"] == "present" and sources[name]["sha256"] != expected.lower():
                errors.append({"path": name, "object": obj["id"], "error": "sha256_mismatch"})
    result = {"schema_version": 1, "objects": copy.deepcopy(sorted(objects, key=lambda x: x["id"])),
            "relations": copy.deepcopy(sorted(relations, key=lambda x: (x["from"], x["type"], x["to"]))),
            "excluded_sources": list(excluded), "sources": sources, "errors": errors,
            "unverified_sources": unverified, "root": str(root), "metrics": metrics,
            "verification_mode": "metadata_only" if metadata_only else "strict_hash",
            "metrics_scope": METRICS_SCOPE,
            "scope": "Only explicitly indexed files were checked; no scientific claim was validated."}
    if metadata_only:
        if same_root:
            changes.extend({"path": name, "change": "removed_from_index"}
                           for name in sorted(set(previous["sources"]) - set(sources)))
        result.update(candidate_sources=sorted(candidates), changed_sources=changes,
                      needs_strict_verification=sorted(needs_strict), verified_sources=0,
                      unverified_objects=sorted(obj["id"] for obj in objects),
                      scope="Metadata agreement is only a screening candidate, not content equality. All objects remain unverified. Run a fresh strict snapshot/validation before content reuse, consolidation or deletion; no scientific claim was validated.")
    return result


def validate_index(index, root):
    metrics = io_metrics()
    try:
        snapshot = inspect_index(index, root, metrics=metrics)
    except (ValueError, OSError) as error:
        return {"valid": False, "errors": [str(error)], "verified_sources": 0, "unverified_sources": [],
                "verification_mode": "strict_hash", "metrics": metrics, "metrics_scope": METRICS_SCOPE}
    invalid_paths = {error["path"] for error in snapshot["errors"]}
    return {"valid": not snapshot["errors"], "errors": snapshot["errors"],
            "verified_sources": sum(x["state"] == "present" and name not in invalid_paths
                                    for name, x in snapshot["sources"].items()),
            "unverified_sources": snapshot["unverified_sources"], "scope": snapshot["scope"],
            "verification_mode": snapshot["verification_mode"], "metrics": snapshot["metrics"],
            "metrics_scope": snapshot["metrics_scope"]}


def impact(before, after):
    if any(item.get("verification_mode") != "strict_hash" for item in (before, after)):
        raise ValueError("Impact requires strict_hash snapshots; metadata scans cannot establish reusable objects")
    old_objects, old_relations, _ = schema(before)
    new_objects, new_relations, _ = schema(after)
    old, new = ({obj["id"]: obj for obj in items} for items in (old_objects, new_objects))
    source_changes = []
    changed_sources = set()
    for name in sorted(set(before["sources"]) | set(after["sources"])):
        a, b = before["sources"].get(name), after["sources"].get(name)
        # Metadata changes alone are not content changes after full strict hashing.
        a = {k: v for k, v in a.items() if k != "metadata"} if a else a
        b = {k: v for k, v in b.items() if k != "metadata"} if b else b
        if a != b:
            change = "removed" if b is None or b.get("state") == "missing" else "added" if a is None or a.get("state") == "missing" else "changed"
            source_changes.append({"path": name, "change": change})
            changed_sources.add(name)
    direct = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    for obj in old_objects + new_objects:
        if any(s["path"] in changed_sources for s in obj.get("sources", [])):
            direct.add(obj["id"])
    relation_sets = [{(r["from"], r["type"], r["to"]) for r in rows} for rows in (old_relations, new_relations)]
    for start, _, end in relation_sets[0] ^ relation_sets[1]:
        direct.update((start, end))
    invalid = set()
    for error in after.get("errors", []):
        for obj in new_objects:
            if error.get("object") == obj["id"] or (
                    "object" not in error and any(s["path"] == error.get("path") for s in obj.get("sources", []))):
                invalid.add(obj["id"])
    adjacency = {}
    for relation in old_relations + new_relations:
        start, end = relation["from"], relation["to"]
        if relation["type"] == "depends_on":
            start, end = end, start
        adjacency.setdefault(start, set()).add(end)
    unverified_paths = {name for name, item in after["sources"].items() if item["state"] == "unverified"}
    unverified = {obj["id"] for obj in new_objects if any(s["path"] in unverified_paths for s in obj.get("sources", []))}
    pending = list(unverified)
    while pending:
        for dependent in adjacency.get(pending.pop(), set()) - unverified:
            unverified.add(dependent)
            pending.append(dependent)
    affected, pending = direct | invalid | unverified, list(direct | invalid | unverified)
    while pending:
        for dependent in adjacency.get(pending.pop(), set()) - affected:
            affected.add(dependent)
            pending.append(dependent)
    return {"direct_changes": sorted(direct), "invalid_objects": sorted(invalid),
            "affected_objects": sorted(affected - direct - invalid),
            "review_required": sorted(affected), "reusable_objects": sorted(set(new) - affected),
            "unverified_objects": sorted(unverified & set(new)),
            "source_changes": source_changes, "unverified_sources": after.get("unverified_sources", []),
            "scope": "Affected means review required, not scientifically disproved; reusable means structurally unchanged after strict hashing, without current binding errors or unverified source dependencies within this selected index. It does not establish scientific validity."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "snapshot", "scan"):
        child = commands.add_parser(command)
        child.add_argument("--index", type=Path, required=True)
        child.add_argument("--root", type=Path, required=True)
        if command in {"snapshot", "scan"}:
            child.add_argument("--out", type=Path)
        if command == "scan":
            child.add_argument("--previous", type=Path)
    child = commands.add_parser("impact")
    child.add_argument("--before", type=Path, required=True)
    child.add_argument("--after", type=Path, required=True)
    child.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "impact":
            result = impact(json.loads(args.before.read_text(encoding="utf-8")), json.loads(args.after.read_text(encoding="utf-8")))
        else:
            index = json.loads(args.index.read_text(encoding="utf-8"))
            if args.command == "scan":
                previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
                result = scan_index(index, args.root, previous)
            else:
                result = validate_index(index, args.root) if args.command == "validate" else snapshot_index(index, args.root)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if getattr(args, "out", None):
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 1 if result.get("valid") is False or result.get("errors") else 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"evidence_index: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
