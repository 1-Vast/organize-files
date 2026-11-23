from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest

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

    assert len(result['errors']) >= 7
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


def test_partition_keeps_safe_items_visible_when_one_item_is_blocked(tmp_path: Path) -> None:
    safe = write(tmp_path / 'safe.txt', b'safe')
    manifest = {
        'root': str(tmp_path),
        'items': [
            {'path': 'safe.txt', 'sha256': digest(safe), 'reason': 'candidate'},
            {'path': '.git/HEAD', 'sha256': '0' * 64, 'reason': 'protected'},
        ],
    }
    groups = delete_paths.partition(manifest)
    assert [item['path'] for item in groups['accepted']] == ['safe.txt']
    assert groups['blocked'][0]['path'] == '.git/HEAD'
    assert safe.exists()


def test_duplicate_paths_are_rejected_before_mutation(tmp_path: Path) -> None:
    file = write(tmp_path / 'a.txt', b'a')
    manifest = {
        'root': str(tmp_path),
        'items': [
            {'path': 'a.txt', 'sha256': digest(file), 'reason': 'one'},
            {'path': './a.txt', 'sha256': digest(file), 'reason': 'two'},
        ],
    }
    result = delete_paths.run(manifest, apply=True)
    assert result['deleted'] == []
    assert result['errors']
    assert file.exists()


def test_post_delete_bytes_are_verified(tmp_path: Path) -> None:
    file = write(tmp_path / 'a.txt', b'a')
    manifest = {'root': str(tmp_path), 'items': [
        {'path': 'a.txt', 'sha256': digest(file), 'reason': 'candidate'},
    ]}
    result = delete_paths.run(manifest, apply=True)
    assert result['errors'] == []
    assert result['bytes_planned'] == 1
    assert result['bytes_removed_verified'] == 1
    assert not file.exists()


def test_partition_blocks_parent_when_child_is_blocked(tmp_path: Path) -> None:
    write(tmp_path / 'folder' / 'keep.txt', b'keep')
    manifest = {
        'root': str(tmp_path),
        'items': [
            {'path': 'folder', 'kind': 'empty-dir', 'reason': 'candidate'},
            {'path': 'folder/keep.txt', 'reason': 'protected content'},
        ],
    }
    groups = delete_paths.partition(manifest)
    assert groups['accepted'] == []
    assert {item['path'] for item in groups['blocked']} == {'folder', 'folder/keep.txt'}


def test_partition_cli_returns_structured_errors(tmp_path: Path, capsys) -> None:
    file = write(tmp_path / 'a.txt', b'a')
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps({
        'root': str(tmp_path),
        'items': [
            {'path': 'a.txt', 'sha256': digest(file), 'reason': 'candidate'},
            {'path': '.git/HEAD', 'sha256': '0' * 64, 'reason': 'protected'},
        ],
    }), encoding='utf-8')
    assert delete_paths.main([str(manifest_path), '--partition']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['errors']
    assert result['accepted'][0]['path'] == 'a.txt'


def test_dry_run_reports_file_bytes_and_empty_dirs_have_zero_bytes(tmp_path: Path) -> None:
    file = write(tmp_path / 'a.txt', b'abc')
    (tmp_path / 'empty').mkdir()
    manifest = {'root': str(tmp_path), 'items': [
        {'path': 'a.txt', 'sha256': digest(file), 'reason': 'candidate'},
        {'path': 'empty', 'kind': 'empty-dir', 'reason': 'candidate'},
    ]}
    result = delete_paths.run(manifest, apply=False)
    assert result['errors'] == []
    assert result['bytes_planned'] == 3


def test_cache_dir_rejects_protected_descendant(tmp_path: Path) -> None:
    write(tmp_path / '__pycache__' / '.git' / 'HEAD', b'ref')
    manifest = {'root': str(tmp_path), 'items': [
        {'path': '__pycache__', 'kind': 'cache-dir', 'reason': 'candidate'},
    ]}
    result = delete_paths.run(manifest, apply=True)
    assert result['deleted'] == []
    assert 'protected path inside cache dir' in result['errors'][0]['error']


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows symlink creation may require elevated privileges')
def test_dangling_symlink_is_detected_after_delete(tmp_path: Path) -> None:
    file = write(tmp_path / 'a.txt', b'a')
    manifest = {'root': str(tmp_path), 'items': [
        {'path': 'a.txt', 'sha256': digest(file), 'reason': 'candidate'},
    ]}
    original_remove = delete_paths.remove
    def recreate_link(target: Path, kind: str) -> int:
        size = original_remove(target, kind)
        target.symlink_to(tmp_path / 'missing')
        return size
    delete_paths.remove = recreate_link
    try:
        result = delete_paths.run(manifest, apply=True)
    finally:
        delete_paths.remove = original_remove
    assert result['deleted'] == []
    assert result['recreated_after_delete'] == ['a.txt']
