"""Read-only tidiness audit: naming, layout and redundancy findings for a folder tree.

Lists what a perfectionist reviewer would flag (junk and caches, empty or
pointless folders, exact duplicates, copy/version markers, vague names, mixed
sibling naming styles, unpadded numbering, non-ISO dates, crowded folders) and
can print a compact tree for before/after review. Nothing is modified. Findings
are candidates: a justified exception is acceptable, a silent one is not.
Managed or IDE subtrees (.git, virtual environments, node_modules, .idea, ...)
are listed as opaque and never descended into.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys

OPAQUE = frozenset({'.git', '.hg', '.svn', '.venv', 'venv', '.conda', 'node_modules',
                    '.idea', '.vscode', 'site-packages'})
CACHE_DIRS = frozenset({'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
                        '.ipynb_checkpoints'})
JUNK_FILES = frozenset({'thumbs.db', 'ehthumbs.db', 'desktop.ini', '.ds_store'})
CONVENTIONAL = re.compile(
    r'^(readme|license|licence|changelog|contributing|notice|authors|makefile|dockerfile|'
    r'skill|agents|claude|memory|requirements|setup|pyproject|package|package-lock|'
    r'environment|main|__init__|__main__|conftest|index)(\.[\w.-]+)?$', re.I)
COPY = re.compile(r'(\(\d+\)$|^copy of |[ _-]copy\d*$| - copy$|副本)', re.I)
VERSION = re.compile(r'(^|[ _.-])(final|new|old|latest|bak|backup|orig|draft|v\d+(\.\d+)*)(?=$|[ _.-])'
                     r'|最终|最新|终版|定稿|修改版|旧版|备份', re.I)
VAGUE = re.compile(r'^((demo|test|untitled|sample|example|新建文件夹|未命名|新建文本文档)[ _-]?\d+'
                   r'|untitled|misc|other|others|stuff|temp|tmp|file|files|new ?folder|'
                   r'新建文件夹|未命名|杂项|其他|临时)$', re.I)
LOOSE_DATE = re.compile(r'(?<!\d)((?:19|20)\d{2})([._/ -]?)(\d{1,2})\2(\d{1,2})(?!\d)')
NUMBER_PREFIX = re.compile(r'^(\d+)[ _.-]')
FORMAT_DIRS = frozenset({'doc', 'docx', 'pdf', 'pdfs', 'png', 'jpg', 'jpeg', 'img', 'imgs', 'xls', 'xlsx',
                         'csv', 'ppt', 'pptx', 'txt', 'word', 'excel', 'zip', 'rar', 'mp4', 'py'})


def style(stem: str) -> str | None:
    """Naming style of a stem; None for neutral one-word names that fit any style."""
    if ' ' in stem:
        return 'spaces'
    core = stem.lstrip('_.')
    has_dash, has_under = '-' in core, '_' in core
    upper = any(c.isupper() for c in core)
    if has_dash and has_under:
        return 'mixed separators'
    if has_dash:
        return 'kebab-case' if not upper else 'Mixed-Kebab'
    if has_under:
        return 'snake_case' if not upper else 'Mixed_Snake'
    if upper and any(c.isupper() for c in core[1:]) and any(c.islower() for c in core):
        return 'CamelCase'
    return None


def split_name(entry: Path) -> tuple[str, str]:
    if entry.is_dir():
        return entry.name, ''
    stem, dot, ext = entry.name.rpartition('.')
    return (stem, '.' + ext) if dot and stem else (entry.name, '')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path, max_items: int = 15, max_root_files: int = 5, max_depth: int = 5,
          exclude: tuple[str, ...] = ()) -> dict:
    root = root.resolve(strict=True)
    findings: list[dict] = []
    opaque: list[str] = []
    files_by_size: dict[int, list[Path]] = defaultdict(list)
    project_styles: dict[str, dict[str, str]] = defaultdict(dict)
    counts = {'files': 0, 'dirs': 0, 'bytes': 0}
    skip = {e.strip('/').casefold() for e in exclude}

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix() or '.'

    def add(kind: str, path: Path, hint: str) -> None:
        findings.append({'kind': kind, 'path': rel(path), 'hint': hint})

    def walk(folder: Path, depth: int) -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        except OSError as exc:
            add('unreadable', folder, str(exc))
            return
        if folder != root and not entries:
            add('empty dir', folder, 'remove unless a tool requires it')
        if folder != root and len(entries) == 1 and entries[0].is_dir() \
                and entries[0].name not in OPAQUE | CACHE_DIRS:
            add('single-child chain', folder, f'only contains {entries[0].name}/; flatten one level')
        series = len({re.sub(r'\d+', '#', e.name) for e in entries}) == 1
        if len(entries) > max_items and not series:
            add('crowded', folder, f'{len(entries)} entries > {max_items}; group by purpose')
        if folder == root:
            loose = [e for e in entries if e.is_file() and not CONVENTIONAL.match(e.name)
                     and not e.name.startswith('.')]
            if len(loose) > max_root_files:
                add('root clutter', folder, f'{len(loose)} loose files at root > {max_root_files}')
        styles: dict[str, dict[str, list[str]]] = {'dir': defaultdict(list), 'file': defaultdict(list)}
        widths: dict[int, list[str]] = defaultdict(list)
        for entry in entries:
            key = rel(entry).casefold()
            if key in skip or any(key.startswith(s + '/') for s in skip):
                continue
            name = entry.name
            if entry.is_symlink():
                add('link', entry, 'links are not followed')
                continue
            if entry.is_dir():
                if name in OPAQUE:
                    opaque.append(rel(entry))
                    continue
                if name in CACHE_DIRS:
                    add('cache', entry, 'regenerable cache; delete')
                    continue
            elif name.casefold() in JUNK_FILES or name.startswith('~$'):
                add('junk', entry, 'OS/editor leftover; delete')
                continue
            elif name.endswith(('.pyc', '.pyo')):
                add('cache', entry, 'compiled cache; delete')
                continue
            stem, ext = split_name(entry)
            if name != name.strip() or '  ' in name:
                add('whitespace', entry, 'leading/trailing/double spaces')
            if COPY.search(stem):
                add('copy marker', entry, 'compare with the original; keep one')
            if VERSION.search(stem):
                add('version marker', entry, 'keep one current version; fold or delete superseded ones')
            if entry.is_dir() and name.casefold() in FORMAT_DIRS:
                add('format-named dir', entry, 'group by purpose, not by file type')
            if VAGUE.match(stem):
                add('vague name', entry, 'name it after its content or purpose')
            if ext and ext != ext.lower():
                add('extension case', entry, f'use {ext.lower()}')
            for m in LOOSE_DATE.finditer(stem):
                if m.group(2) not in ('-', '') or len(m.group(3)) < 2 or len(m.group(4)) < 2:
                    add('date format', entry, f'"{m.group(0)}" -> YYYY-MM-DD')
            numbered = NUMBER_PREFIX.match(name)
            if numbered:
                widths[len(numbered.group(1))].append(name)
            if not name.startswith('.') and not CONVENTIONAL.match(name):
                found = style(stem)
                if found:
                    styles['dir' if entry.is_dir() else 'file'][found].append(name)
                    project_styles[found].setdefault(re.sub(r'\d+', '#', rel(entry)), rel(entry))
            if entry.is_dir():
                counts['dirs'] += 1
                walk(entry, depth + 1)
            else:
                counts['files'] += 1
                size = entry.stat().st_size
                counts['bytes'] += size
                if depth + 1 > max_depth:
                    add('deep', entry, f'depth {depth + 1} > {max_depth}')
                if size:
                    files_by_size[size].append(entry)
        for kind, groups in styles.items():
            if len(groups) > 1:
                detail = '; '.join(f'{s}: {", ".join(n[:3])}{" ..." if len(n) > 3 else ""}'
                                   for s, n in sorted(groups.items()))
                add('mixed naming', folder, f'{kind} names mix {detail}')
        if len(widths) > 1:
            add('unpadded numbering', folder, 'numeric prefixes differ in width; zero-pad them')

    walk(root, 0)
    if len(project_styles) > 1:
        main_style = max(project_styles, key=lambda k: len(project_styles[k]))
        for other, names in sorted(project_styles.items()):
            if other != main_style:
                sample = sorted(names.values())
                findings.append({'kind': 'off-style name', 'path': sample[0],
                                 'hint': f'project mostly {main_style} ({len(project_styles[main_style])}); '
                                         f'{len(sample)} {other} name(s): '
                                         + ', '.join(sample[:4]) + (' ...' if len(sample) > 4 else '')})
    for size, paths in files_by_size.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for path in paths:
            by_hash[sha256(path)].append(path)
        for digest, same in by_hash.items():
            if len(same) > 1:
                findings.append({'kind': 'duplicate', 'path': rel(same[0]),
                                 'hint': f'identical ({size} B, sha256 {digest[:12]}) to '
                                         + ', '.join(rel(p) for p in same[1:])})
    findings.sort(key=lambda f: (f['kind'], f['path']))
    summary: dict[str, int] = defaultdict(int)
    for item in findings:
        summary[item['kind']] += 1
    return {'root': str(root), 'counts': counts, 'summary': dict(sorted(summary.items())),
            'findings': findings, 'opaque': opaque}


def tree(root: Path, max_entries: int = 25) -> list[str]:
    lines = [root.resolve().name + '/']

    def walk(folder: Path, prefix: str) -> None:
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.casefold()))
        shown = entries[:max_entries]
        for index, entry in enumerate(shown):
            last = index == len(shown) - 1 and len(entries) <= max_entries
            branch, child = ('└── ', '    ') if last else ('├── ', '│   ')
            if entry.is_dir() and not entry.is_symlink():
                total = sum(1 for _ in entry.rglob('*') if _.is_file())
                if entry.name in OPAQUE | CACHE_DIRS:
                    lines.append(f'{prefix}{branch}{entry.name}/  [{total} files, not expanded]')
                    continue
                lines.append(f'{prefix}{branch}{entry.name}/')
                walk(entry, prefix + child)
            else:
                lines.append(f'{prefix}{branch}{entry.name}')
        if len(entries) > max_entries:
            lines.append(f'{prefix}└── ... {len(entries) - max_entries} more')

    walk(root, '')
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('root', type=Path)
    parser.add_argument('--json', action='store_true', help='print the full result as JSON')
    parser.add_argument('--tree', action='store_true', help='print a compact tree first')
    parser.add_argument('--exclude', action='append', default=[],
                        help='root-relative path to skip (repeatable), e.g. a frozen archive')
    parser.add_argument('--max-items', type=int, default=15)
    parser.add_argument('--max-root-files', type=int, default=5)
    parser.add_argument('--max-depth', type=int, default=5)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    result = audit(args.root, args.max_items, args.max_root_files, args.max_depth, tuple(args.exclude))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.tree:
        print('\n'.join(tree(args.root)), end='\n\n')
    c = result['counts']
    print(f"{result['root']}: {c['files']} files, {c['dirs']} dirs, {c['bytes']:,} bytes; "
          f"{len(result['findings'])} findings")
    for kind, n in result['summary'].items():
        print(f'  {kind}: {n}')
    for item in result['findings']:
        print(f"- [{item['kind']}] {item['path']}: {item['hint']}")
    if result['opaque']:
        print('opaque (not descended): ' + ', '.join(result['opaque']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
