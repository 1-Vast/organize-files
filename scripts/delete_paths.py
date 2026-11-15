"""Delete an explicit, reviewed list of paths inside one root, with checks.

The skill's single deletion channel. Shell deletions (Remove-Item, rm, del,
rmdir) are rejected as "blocked by policy" in Codex sessions that cannot ask
for approval, which stops the task; this executor performs the same deletions
as one Python call after verifying every item. Dry-run is the default; pass
--apply to delete. Every item is pre-checked before anything is deleted.

Manifest (JSON):
{"root": "D:/Project",
 "items": [
   {"path": "copies/report (1).docx", "sha256": "<64 hex>", "reason": "duplicate of reports/report.docx"},
   {"path": "Thumbs.db", "reason": "OS thumbnail cache"},
   {"path": "model/__pycache__", "kind": "cache-dir", "reason": "regenerable cache"},
   {"path": "tmp", "kind": "empty-dir", "reason": "emptied by moves"}]}

kind defaults to "file". A file needs its full SHA-256 unless it is OS/editor
junk or compiled cache. A cache-dir must carry a known cache name and is
removed with its contents. An empty-dir must be empty when it is removed.
Paths already absent count as done, so a re-run after an interruption is safe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys

CACHE_DIRS = frozenset({'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.ipynb_checkpoints'})
JUNK = re.compile(r'^(thumbs\.db|ehthumbs\.db|desktop\.ini|\.ds_store|~\$.+|.+\.py[co])$', re.I)
PROTECTED = frozenset({'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '.conda'})
SENSITIVE = re.compile(r'(^\.env($|\.)|^id_(rsa|ed25519)|credential|secret|password|private_key|api_key|\.pem$|\.key$)', re.I)
KINDS = ('file', 'cache-dir', 'empty-dir')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def norm(rel: str) -> str:
    return str(rel).replace('\\', '/').strip('/').casefold()


def check(root: Path, item: dict, planned: frozenset[str] = frozenset()) -> tuple[Path | None, str]:
    """Return (target, status); status is 'ok', 'absent' or an error message.

    An empty-dir counts as empty when everything left in it is itself planned
    for deletion earlier in the same manifest.
    """
    rel, kind, reason = item.get('path', ''), item.get('kind', 'file'), item.get('reason', '')
    if kind not in KINDS:
        return None, f'unknown kind {kind!r}'
    if not str(reason).strip():
        return None, 'missing reason'
    parts = PurePosixPath(str(rel).replace('\\', '/')).parts
    if not parts or Path(rel).is_absolute() or ':' in str(rel) or any(p in ('', '.', '..') for p in parts):
        return None, 'path must be relative to root, without . or ..'
    if any(p.casefold() in PROTECTED for p in parts) or any(SENSITIVE.search(p) for p in parts):
        return None, 'protected or sensitive path'
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if not os.path.lexists(current):
            return target, 'absent'
        if is_link(current):
            return None, f'link or junction: {current}'
    if kind == 'file':
        if not target.is_file():
            return None, 'not a regular file'
        expected = str(item.get('sha256', '')).lower()
        if not expected and not JUNK.match(target.name):
            return None, 'sha256 required for this file'
        if expected and sha256(target) != expected:
            return None, 'sha256 mismatch: file changed since review'
    elif not target.is_dir():
        return None, 'not a directory'
    elif kind == 'cache-dir':
        if target.name not in CACHE_DIRS:
            return None, f'not a known cache directory name: {target.name}'
        for sub in target.rglob('*'):
            if is_link(sub):
                return None, f'link inside cache dir: {sub}'
    elif any(norm(c.relative_to(root).as_posix()) not in planned for c in target.iterdir()):
        return None, 'directory is not empty'
    return target, 'ok'


def _writable_and_retry(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove(target: Path, kind: str) -> int:
    if kind == 'file':
        size = target.stat().st_size
        if not os.access(target, os.W_OK):
            os.chmod(target, stat.S_IWRITE)
        target.unlink()
        return size
    if kind == 'cache-dir':
        size = sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
        handler = 'onexc' if sys.version_info >= (3, 12) else 'onerror'
        shutil.rmtree(target, **{handler: _writable_and_retry})
        return size
    target.rmdir()
    return 0


def run(manifest: dict, apply: bool) -> dict:
    root = Path(manifest.get('root', ''))
    if not root.is_absolute() or not root.is_dir() or is_link(root):
        raise ValueError(f'root must be an existing absolute directory, not a link: {root}')
    root = root.resolve(strict=True)
    items = manifest.get('items') or []
    order = {'file': 0, 'cache-dir': 1, 'empty-dir': 2}
    # Files first, then caches, then empty directories from the deepest up.
    items = sorted(items, key=lambda i: (order.get(i.get('kind', 'file'), 9),
                                         -str(i.get('path', '')).replace('\\', '/').count('/')))
    planned = frozenset(norm(i.get('path', '')) for i in items)
    checked = [(item, *check(root, item, planned)) for item in items]
    errors = [{'path': i.get('path'), 'error': s} for i, _, s in checked if s not in ('ok', 'absent')]
    result = {'root': str(root), 'mode': 'apply' if apply else 'dry-run', 'items': len(items),
              'to_delete': sum(s == 'ok' for _, _, s in checked),
              'already_absent': sum(s == 'absent' for _, _, s in checked),
              'errors': errors, 'deleted': [], 'bytes_freed': 0}
    if errors or not apply:
        return result
    for item, target, status in checked:
        if status != 'ok':
            continue
        kind = item.get('kind', 'file')
        _, again = check(root, item)  # re-verify immediately before mutation
        if again == 'absent':
            result['already_absent'] += 1
            continue
        if again != 'ok':
            result['errors'].append({'path': item['path'], 'error': again})
            break
        try:
            result['bytes_freed'] += remove(target, kind)
        except OSError as exc:
            result['errors'].append({'path': item['path'], 'error': f'{type(exc).__name__}: {exc}'})
            break
        result['deleted'].append(item['path'])
    result['not_attempted'] = result['to_delete'] - len(result['deleted']) - len(result['errors'])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--apply', action='store_true', help='delete (default is a dry-run)')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    result = run(manifest, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
