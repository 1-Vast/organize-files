"""Reviewable file operations with verified recovery; semantic judgments stay with the reviewer.

Plans use schema 1, an absolute root, and file operations: move, remove, replace.
Each operation declares source, sha256 and reason. Moves add target; replacements
add replacement and replacement_sha256. Remove/replace also record evidence with
coverage and review. Evidence is a declared review record, not proof of equivalence.
Only explicit files are read. Quiesce other writers: this is a recoverable journal,
not an atomic transaction across files or a complete NTFS metadata backup.
protected_sources declares project-relative prefixes. Default sensitive names are
also excluded; omitted declarations cannot reveal all project-specific semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import tempfile
import zipfile

PROTECTED_NAME = re.compile(r'sealed|blind|credential|secret|password|passwd|api[_-]?key|(?:^|[_-])token(?:[_.-]|$)', re.I)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Link or reparse point is outside the operation boundary: {part}')


def _root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('root must be an absolute directory')
    if any(_windows_alias(part) for part in path.parts):
        raise ValueError('Windows ambiguous/reserved root path')
    if any(part.casefold() == '.git' for part in path.parts):
        raise ValueError('Git internal directories are not organization roots')
    if _default_protected(path.parts):
        raise ValueError('Protected directories are not organization roots')
    _no_links(path)
    if not path.is_dir():
        raise ValueError('root must exist')
    return path.resolve()


def _windows_alias(part: str) -> bool:
    devices = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
    devices.update(prefix + digit for prefix in ('COM', 'LPT') for digit in '123456789¹²³')
    return part.endswith((' ', '.')) or part.split('.')[0].upper() in devices


def _parts(value: str) -> list[str]:
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('A nonempty relative file path is required')
    parts = value.replace('\\', '/').split('/')
    if Path(value).is_absolute() or PureWindowsPath(value).drive or any(p in {'', '.', '..'} or ':' in p or _windows_alias(p) for p in parts):
        raise ValueError(f'Unsafe relative path: {value}')
    return parts


def _default_protected(parts) -> bool:
    return (any(p.casefold().startswith('.env') or p.casefold() in {'.git', '.ssh'} or PROTECTED_NAME.search(p) for p in parts)
            or Path(parts[-1]).suffix.casefold() in {'.pem', '.key', '.p12', '.pfx', '.kdbx'}
            or parts[-1].casefold() in {'id_rsa', 'id_ed25519', 'authorized_keys'})


def _protected_sources(plan: dict) -> list[str]:
    prefixes = plan.get('protected_sources', [])
    if not isinstance(prefixes, list):
        raise ValueError('protected_sources must be a list of relative path prefixes')
    return ['/'.join(_parts(value)) for value in prefixes]


def _path(root: Path, value: str, protected: list[str] = ()) -> Path:
    parts = _parts(value)
    name = '/'.join(parts).casefold()
    if (_default_protected(parts)
            or any(name == prefix.casefold() or name.startswith(prefix.casefold() + '/') for prefix in protected)):
        raise ValueError(f'Protected path is outside the operation boundary: {value}')
    path = root.joinpath(*parts)
    _no_links(path)
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'Path outside root: {value}')
    return path


def _hash(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('sha256 must be a lowercase 64-character hexadecimal digest')
    return value


def _assert_file(path: Path, expected: str) -> None:
    _no_links(path)
    if not path.is_file():
        raise ValueError(f'Source changed, missing, or not a regular file: {path}')
    if path.stat().st_nlink != 1:
        raise ValueError(f'Hard-linked files require a separate preservation decision: {path}')
    if digest(path) != expected:
        raise ValueError(f'Source changed, missing, or not a regular file: {path}')
    if path.stat().st_nlink != 1:
        raise ValueError(f'Hard-linked files require a separate preservation decision: {path}')


def _check_overlap(writes: list[Path], reads: list[Path]) -> None:
    """Index path segments; read/read ancestry is harmless, writes must not overlap."""
    write_keys = {tuple(part.casefold() for part in path.parts) for path in writes}
    read_keys = {tuple(part.casefold() for part in path.parts) for path in reads}
    if len(write_keys) != len(writes):
        raise ValueError('Overlapping source/destination operations')
    if write_keys & read_keys:
        raise ValueError('A replacement source is also being changed')
    all_keys = write_keys | read_keys
    for key in all_keys:
        ancestors = write_keys if key not in write_keys else all_keys
        if any(key[:depth] in ancestors for depth in range(1, len(key))):
            raise ValueError('Ancestor/descendant operation paths overlap')


def _operation_paths(root: Path, item: dict, protected: list[str]) -> dict[str, Path]:
    fields = ['source']
    if item['op'] == 'move':
        fields.append('target')
    elif item['op'] == 'replace':
        fields.append('replacement')
    return {field: _path(root, item[field], protected) for field in fields}


def dry_run(plan: dict) -> list[dict]:
    """Validate exact sources, declared review, path impact and conflicts without writing."""
    if plan.get('schema') != 1 or not isinstance(plan.get('operations'), list) or not plan['operations']:
        raise ValueError('Expected schema 1 and nonempty operations')
    root = _root(plan['root'])
    protected = _protected_sources(plan)
    changes, writes, reads = [], [], []
    for operation in plan['operations']:
        item = dict(operation)
        kind = item.get('op')
        if kind not in {'move', 'remove', 'replace'} or not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('Each operation requires op and a nonempty reason')
        paths = _operation_paths(root, item, protected)
        source = paths['source']
        _assert_file(source, _hash(item['sha256']))
        writes.append(source)
        if kind == 'move':
            target = paths['target']
            if target.exists():
                raise ValueError(f'Destination already exists: {target}')
            writes.append(target)
        else:
            evidence = item.get('evidence', {})
            coverage = evidence.get('coverage') if isinstance(evidence, dict) else None
            if isinstance(coverage, str):
                coverage = [coverage]
            if not isinstance(coverage, list) or not coverage or not all(isinstance(x, str) and x.strip() for x in coverage) or not isinstance(evidence.get('review'), str) or not evidence['review'].strip():
                raise ValueError('Remove/replace requires declared evidence.coverage and evidence.review')
            if kind == 'replace':
                prepared = paths['replacement']
                _assert_file(prepared, _hash(item['replacement_sha256']))
                reads.append(prepared)
        changes.append(item)
    _check_overlap(writes, reads)
    return changes


def _save(state_dir: Path, state: dict) -> None:
    _no_links(state_dir / 'state.json')
    handle, name = tempfile.mkstemp(prefix='.state-', suffix='.json.partial', dir=state_dir)
    temporary = Path(name)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state_dir / 'state.json')
    finally:
        temporary.unlink(missing_ok=True)


def _state_dir(path: Path, root: Path, *, new: bool) -> Path:
    path = path.absolute()
    _no_links(path)
    if path.resolve().is_relative_to(root) or root.is_relative_to(path.resolve()):
        raise ValueError('state-dir must be outside and not an ancestor of root')
    if new and path.exists():
        raise ValueError('state-dir must not already exist')
    return path


def _verify_recovery(state_dir: Path, state: dict) -> None:
    recovery = state_dir / 'recovery.zip'
    _no_links(recovery)
    if digest(recovery) != state['recovery_sha256']:
        raise ValueError('Recovery archive checksum mismatch')
    with zipfile.ZipFile(recovery) as archive:
        if 'plan.json' not in archive.namelist():
            raise ValueError('Legacy recovery has no bound protection policy; separate reviewed recovery is required')
        bound = json.loads(archive.read('plan.json'))
        current = _bound_plan(state)
        if bound != current:
            raise ValueError('Recovery plan/protection policy differs from journal state')
        protected = _protected_sources(state)
        for item in state['operations']:
            _operation_paths(Path(state['root']), item, protected)
        if archive.namelist() != ['plan.json'] + [str(i) for i in range(len(state['operations']))]:
            raise ValueError('Unexpected recovery archive members')
        for i, item in enumerate(state['operations']):
            with archive.open(str(i)) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('Recovery member checksum mismatch')


def _bound_plan(state: dict) -> dict:
    mutable = {'status', 'mode', 'mtime_ns', 'atime_ns'}
    return {'root': state['root'], 'protected_sources': state.get('protected_sources', []),
            'operations': [{k: v for k, v in item.items() if k not in mutable} for item in state['operations']]}


def _copy_exclusive(source: Path, target: Path) -> None:
    """Copy without clobbering a target created after preflight."""
    _no_links(source)
    _no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.organization-move-', dir=target.parent)
    os.close(handle)
    staging = Path(name)
    try:
        with source.open('rb') as incoming, staging.open('wb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        if digest(staging) != digest(source):
            raise ValueError(f'Source changed during copy: {source}')
        os.link(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def _apply_one(root: Path, item: dict) -> None:
    source = _path(root, item['source'])
    _assert_file(source, item['sha256'])
    if item['op'] == 'move':
        target = _path(root, item['target'])
        _copy_exclusive(source, target)
        shutil.copystat(source, target, follow_symlinks=False)
        _assert_file(target, item['sha256'])
        _assert_file(source, item['sha256'])
        source.unlink()
    elif item['op'] == 'remove':
        source.unlink()
    else:
        prepared = _path(root, item['replacement'])
        _assert_file(prepared, item['replacement_sha256'])
        handle, name = tempfile.mkstemp(prefix='.organization-', dir=source.parent)
        os.close(handle)
        staging = Path(name)
        try:
            shutil.copyfile(prepared, staging)
            _assert_file(staging, item['replacement_sha256'])
            _assert_file(source, item['sha256'])
            os.replace(staging, source)
        finally:
            staging.unlink(missing_ok=True)


def apply_plan(plan: dict, state_dir: Path) -> dict:
    operations = dry_run(plan)
    root = _root(plan['root'])
    state_dir = _state_dir(Path(state_dir), root, new=True)
    state_dir.mkdir(parents=True)
    state = {'schema': 1, 'root': str(root), 'status': 'preparing',
             'protected_sources': _protected_sources(plan), 'operations': []}
    with zipfile.ZipFile(state_dir / 'recovery.zip', 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.writestr('plan.json', json.dumps({'root': str(root), 'protected_sources': state['protected_sources'],
                                               'operations': operations}, ensure_ascii=False))
        for i, operation in enumerate(operations):
            source = _path(root, operation['source'])
            info = source.stat()
            _assert_file(source, operation['sha256'])
            archive.write(source, str(i))
            _assert_file(source, operation['sha256'])
            state['operations'].append({**operation, 'status': 'pending', 'mode': stat.S_IMODE(info.st_mode),
                                        'mtime_ns': info.st_mtime_ns, 'atime_ns': info.st_atime_ns})
    state['recovery_sha256'] = digest(state_dir / 'recovery.zip')
    with (state_dir / 'recovery.zip').open('r+b') as stream:
        os.fsync(stream.fileno())
    _verify_recovery(state_dir, state)
    state['status'] = 'prepared'
    _save(state_dir, state)
    try:
        for item in state['operations']:
            _operation_paths(root, item, state['protected_sources'])
            item['status'] = 'started'
            _save(state_dir, state)
            _apply_one(root, item)
            item['status'] = 'done'
            _save(state_dir, state)
        state['status'] = 'applied'
        _save(state_dir, state)
    except Exception:
        state['status'] = 'failed'
        _save(state_dir, state)
        raise
    return state


def _rollback_check(root: Path, item: dict) -> None:
    source = _path(root, item['source'])
    if source.exists() and source.stat().st_nlink != 1:
        raise ValueError(f'Refusing to alter later hard-linked source: {source}')
    old_present = source.exists() and source.is_file() and digest(source) == item['sha256']
    if item['op'] == 'move':
        target = _path(root, item['target'])
        if target.exists():
            _assert_file(target, item['sha256'])
        if source.exists() and not old_present:
            raise ValueError(f'Refusing to overwrite later source changes: {source}')
        if not source.exists() and not target.exists():
            raise ValueError(f'Moved file is missing at both locations: {source}')
    elif source.exists():
        allowed = {item['sha256']}
        if item['op'] == 'replace':
            allowed.add(item['replacement_sha256'])
        if not source.is_file() or digest(source) not in allowed:
            raise ValueError(f'Refusing to overwrite later changes: {source}')


def rollback(state_dir: Path) -> dict:
    state_dir = Path(state_dir).absolute()
    _no_links(state_dir / 'state.json')
    state = json.loads((state_dir / 'state.json').read_text(encoding='utf-8'))
    if state.get('schema') != 1:
        raise ValueError('Unsupported recovery state schema')
    root = _root(state['root'])
    _state_dir(state_dir, root, new=False)
    _verify_recovery(state_dir, state)
    active = [(i, item) for i, item in enumerate(state['operations']) if item['status'] in {'started', 'done', 'rollback_started'}]
    for _, item in active:
        _rollback_check(root, item)
    with zipfile.ZipFile(state_dir / 'recovery.zip') as archive:
        for i, item in reversed(active):
            item['status'] = 'rollback_started'
            _save(state_dir, state)
            _rollback_check(root, item)
            source = _path(root, item['source'])
            if not source.exists() or digest(source) != item['sha256']:
                source.parent.mkdir(parents=True, exist_ok=True)
                handle, name = tempfile.mkstemp(prefix='.organization-restore-', dir=source.parent)
                os.close(handle)
                staging = Path(name)
                try:
                    with archive.open(str(i)) as incoming, staging.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                    _assert_file(staging, item['sha256'])
                    _rollback_check(root, item)
                    os.replace(staging, source)
                finally:
                    staging.unlink(missing_ok=True)
            if item['op'] == 'move':
                target = _path(root, item['target'])
                if target.exists():
                    _assert_file(target, item['sha256'])
                    target.unlink()
            os.chmod(source, item['mode'])
            os.utime(source, ns=(item['atime_ns'], item['mtime_ns']))
            item['status'] = 'rolled_back'
            _save(state_dir, state)
    state['status'] = 'rolled_back'
    _save(state_dir, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('dry-run', 'apply'):
        command = commands.add_parser(name)
        command.add_argument('plan', type=Path)
        if name == 'apply':
            command.add_argument('--state-dir', type=Path, required=True)
    commands.add_parser('rollback').add_argument('state_dir', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'rollback':
            result = rollback(args.state_dir)
        else:
            plan = json.loads(args.plan.read_text(encoding='utf-8'))
            result = dry_run(plan) if args.command == 'dry-run' else apply_plan(plan, args.state_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
