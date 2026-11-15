from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import delete_paths  # noqa: E402


def write(path: Path, data: bytes = b'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))


def build(root: Path) -> dict:
    dup = write(root / 'copies' / 'report (1).docx', b'same')
    write(root / 'reports' / 'report.docx', b'same')
    junk = write(root / 'Thumbs.db', b'thumb')
    junk.chmod(stat.S_IREAD)
    write(root / 'model' / '__pycache__' / 'm.cpython-312.pyc', b'pyc')
    (root / 'tmp' / 'inner').mkdir(parents=True)
    return {'root': str(root), 'items': [
        {'path': 'tmp', 'kind': 'empty-dir', 'reason': 'emptied'},
        {'path': 'tmp/inner', 'kind': 'empty-dir', 'reason': 'emptied'},
        {'path': 'copies', 'kind': 'empty-dir', 'reason': 'emptied after duplicate removal'},
        {'path': 'copies/report (1).docx', 'sha256': digest(dup), 'reason': 'duplicate of reports/report.docx'},
        {'path': 'Thumbs.db', 'reason': 'OS junk'},
        {'path': 'model/__pycache__', 'kind': 'cache-dir', 'reason': 'regenerable'},
    ]}


def test_dry_run_changes_nothing_then_apply_deletes_in_safe_order(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    before = tree(tmp_path)

    dry = delete_paths.run(manifest, apply=False)
    assert dry['errors'] == [] and dry['to_delete'] == 6
    assert tree(tmp_path) == before

    done = delete_paths.run(manifest, apply=True)
    assert done['errors'] == [] and len(done['deleted']) == 6 and done['not_attempted'] == 0
    assert tree(tmp_path) == ['model', 'reports', 'reports/report.docx']

    again = delete_paths.run(manifest, apply=True)
    assert again['errors'] == [] and again['already_absent'] == 6 and again['deleted'] == []


def test_any_failed_check_blocks_every_deletion(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    write(tmp_path / 'keep.txt', b'unique')
    write(tmp_path / '.git' / 'HEAD', b'ref')
    write(tmp_path / 'notes' / 'draft.md', b'd')
    manifest['items'] += [
        {'path': 'keep.txt', 'sha256': '0' * 64, 'reason': 'stale hash'},
        {'path': 'notes/draft.md', 'reason': 'no hash'},
        {'path': 'reports', 'kind': 'empty-dir', 'reason': 'not empty'},
        {'path': 'reports', 'kind': 'cache-dir', 'reason': 'wrong name'},
        {'path': '.git/HEAD', 'sha256': digest(tmp_path / '.git' / 'HEAD'), 'reason': 'protected'},
        {'path': '../outside.txt', 'sha256': '0' * 64, 'reason': 'escape'},
        {'path': 'Thumbs.db', 'reason': ''},
    ]
    before = tree(tmp_path)

    result = delete_paths.run(manifest, apply=True)

    assert len(result['errors']) == 7
    assert result['deleted'] == []
    assert tree(tmp_path) == before


def test_cli_returns_nonzero_on_errors(tmp_path: Path, capsys) -> None:
    write(tmp_path / 'a.txt', b'a')
    path = tmp_path / 'm.json'
    path.write_text(json.dumps({'root': str(tmp_path), 'items': [{'path': 'a.txt', 'reason': 'r'}]}),
                    encoding='utf-8')
    assert delete_paths.main([str(path)]) == 1
    assert 'sha256 required' in capsys.readouterr().out
    assert (tmp_path / 'a.txt').exists()
