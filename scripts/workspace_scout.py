"""Fast, read-only workspace inventory and metadata delta for organization triage.

Only file metadata is inspected. No source payloads are opened or hashed. Opaque,
managed, sensitive, and reparse-point subtrees are never descended into. A delta
can select review candidates, never certify byte identity or authorize deletion.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import tempfile
import time

MANAGED = frozenset({'.git', '.hg', '.svn', '.venv', 'venv', 'gpu_venv',
                     'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache'})
SENSITIVE = re.compile(r'(^|[._-])(sealed|blind|secret|credentials?|password|passwd|tokens?|private_key|api_key)([._-]|$)', re.I)
SENSITIVE_FILES = frozenset({'.env', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519'})
DEVICE = re.compile(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def checked_root(value: Path) -> Path:
    path = value.absolute()
    for candidate in (path, *path.parents):
        if candidate.name.casefold() in MANAGED or _sensitive(candidate.name):
            raise ValueError(f'Protected project root or ancestor: {candidate}')
        if candidate.exists() and _linked(candidate):
            raise ValueError(f'Linked project root or ancestor: {candidate}')
    if not path.is_dir():
        raise ValueError(f'Project root is not a directory: {path}')
    return path.resolve(strict=True)


def _relative_prefix(value: str) -> str:
    if not value or '\\' in value or ':' in value or PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise ValueError(f'Unsafe opaque prefix: {value}')
    parts = value.split('/')
    if any(p in ('', '.', '..') or p != p.rstrip(' .') or DEVICE.fullmatch(p) for p in parts):
        raise ValueError(f'Unsafe opaque prefix: {value}')
    result = '/'.join(parts)
    return result.casefold() if os.name == 'nt' else result


def _sensitive(name: str) -> bool:
    return name.casefold() in SENSITIVE_FILES or bool(SENSITIVE.search(name)) or name.casefold().startswith('.env.')


def _opaque_match(path: str, opaque: tuple[str, ...]) -> bool:
    if os.name == 'nt':
        path = path.casefold()
    return any(path == item or path.startswith(item + '/') for item in opaque)


def _classification(name: str, is_dir: bool, relative: str, opaque: tuple[str, ...]) -> str | None:
    if is_dir and name.casefold() in MANAGED:
        return 'managed'
    if _sensitive(name):
        return 'sensitive'
    if _opaque_match(relative, opaque):
        return 'explicit_opaque'
    return None


def inventory(root: Path, opaque: tuple[str, ...] = ()) -> dict:
    root = checked_root(root)
    opaque = tuple(sorted({_relative_prefix(x) for x in opaque}))
    start = time.perf_counter()
    stack = [(root, '')]
    entries: dict[str, list[int]] = {}
    dirs = 0
    excluded = Counter()
    exclusions: list[dict] = []
    top = defaultdict(lambda: {'files': 0, 'bytes': 0})
    extensions = Counter()
    total_bytes = 0
    entry_stat_calls = 0
    while stack:
        directory, prefix = stack.pop()
        with os.scandir(directory) as scan:
            children = list(scan)
        dirs += 1
        for item in children:
            relative = f'{prefix}/{item.name}' if prefix else item.name
            # Do not inspect payload or traverse linked/reparse-point subtrees.
            entry_stat_calls += 1
            info = item.stat(follow_symlinks=False)
            linked = item.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
            if linked:
                excluded['linked'] += 1
                exclusions.append({'path': relative, 'reason': 'linked'})
                continue
            if stat.S_ISDIR(info.st_mode):
                reason = _classification(item.name, True, relative, opaque)
                if reason:
                    excluded[reason] += 1
                    exclusions.append({'path': relative, 'reason': reason})
                else:
                    stack.append((Path(item.path), relative))
            elif stat.S_ISREG(info.st_mode):
                reason = _classification(item.name, False, relative, opaque)
                if reason:
                    excluded[reason] += 1
                    # Avoid exposing sensitive filenames; only record count.
                    if reason != 'sensitive':
                        exclusions.append({'path': relative, 'reason': reason})
                    continue
                size = int(info.st_size)
                meta = [size, int(info.st_mtime_ns), int(info.st_ctime_ns), int(info.st_dev), int(info.st_ino)]
                entries[relative] = meta
                top[relative.split('/')[0]]['files'] += 1
                top[relative.split('/')[0]]['bytes'] += size
                suffix = PurePosixPath(relative).suffix.casefold() or '<none>'
                extensions[suffix] += 1
                total_bytes += size
            else:
                excluded['special'] += 1
                exclusions.append({'path': relative, 'reason': 'special'})
    return {'schema': 1, 'root': str(root), 'opaque': list(opaque),
            'entries': entries, 'stats': {'files': len(entries), 'visited_directories': dirs,
                'entry_stat_calls': entry_stat_calls, 'source_payload_files_opened': 0,
                'logical_bytes': total_bytes, 'excluded_counts': dict(excluded),
                'top_areas': dict(top), 'extension_counts': dict(extensions),
                'excluded_paths': exclusions},
            'seconds': time.perf_counter() - start,
            'scope': 'METADATA ONLY: unchanged metadata is not byte identity; excluded subtrees are not counted. No conclusions or deletions are verified.'}


def delta(current: dict, previous: dict | None, max_preview: int = 20) -> dict:
    if max_preview < 0:
        raise ValueError('max_preview must be nonnegative')
    if previous is not None and (previous.get('schema') != 1 or previous.get('root') != current['root']
                                 or previous.get('opaque') != current['opaque']):
        raise ValueError('Previous snapshot has a different root, scope or schema')
    now = current['entries']
    if previous is None:
        changes = {'baseline': sorted(now), 'added': [], 'metadata_changed': [],
                   'metadata_unchanged': [], 'missing': []}
    else:
        old = previous['entries']
        changes = {'baseline': [], 'added': sorted(set(now) - set(old)),
                   'metadata_changed': sorted(k for k in set(now) & set(old) if now[k] != old[k]),
                   'metadata_unchanged': sorted(k for k in set(now) & set(old) if now[k] == old[k]),
                   'missing': sorted(set(old) - set(now))}
    return {'schema': 1, 'root': current['root'], 'opaque': current['opaque'],
            'scan_seconds': current['seconds'],
            'files_seen': current['stats']['files'], 'dirs_visited': current['stats']['visited_directories'],
            'logical_bytes': current['stats']['logical_bytes'],
            'opaque_and_skipped': current['stats']['excluded_counts'],
            'top_areas': sorted(({'area': k, **v} for k, v in current['stats']['top_areas'].items()),
                                key=lambda x: (-x['files'], x['area']))[:15],
            'extensions': sorted(({'ext': k, 'files': v} for k, v in current['stats']['extension_counts'].items()),
                                 key=lambda x: (-x['files'], x['ext']))[:12],
            'change_counts': {k: len(v) for k, v in changes.items()},
            'change_preview': {k: v[:max_preview] for k, v in changes.items() if k != 'metadata_unchanged'},
            'scope': current['scope']}


def write_snapshot(target: Path, root: Path, snapshot: dict) -> None:
    target = target.absolute()
    root = checked_root(root)
    for candidate in (target, *target.parents):
        if candidate.exists() and _linked(candidate):
            raise ValueError('Linked snapshot path or ancestor is outside the write boundary')
    target = target.parent.resolve(strict=True) / target.name
    if target == root or root in target.parents:
        raise ValueError('Snapshot must stay outside the project root')
    if not target.parent.is_dir():
        raise ValueError('Snapshot parent must exist')
    staging = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                         prefix='.workspace-scout-', suffix='.partial', delete=False) as stream:
            staging = Path(stream.name)
            json.dump(snapshot, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, target)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--snapshot-out', type=Path)
    parser.add_argument('--opaque', action='append', default=[])
    parser.add_argument('--max-preview', type=int, default=20)
    args = parser.parse_args(argv)
    try:
        previous = json.loads(args.previous.read_text(encoding='utf-8')) if args.previous else None
        result = inventory(args.root, tuple(args.opaque))
        summary = delta(result, previous, max_preview=args.max_preview)
        if args.snapshot_out:
            write_snapshot(args.snapshot_out, Path(result['root']), result)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f'workspace_scout: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
