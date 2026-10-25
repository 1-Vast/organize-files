import importlib.util
import json
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location('scout', Path(__file__).parents[1] / 'scripts/workspace_scout.py')
scout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scout)


def test_delta_and_opaque_without_reading_source(tmp_path, monkeypatch):
    root = tmp_path / 'research'
    (root / 'src').mkdir(parents=True)
    (root / 'data' / 'external').mkdir(parents=True)
    (root / '.git').mkdir()
    (root / 'src' / 'main.py').write_text('print(1)')
    (root / 'data' / 'external' / 'raw.csv').write_text('large data')
    (root / '.git' / 'config').write_text('secret ignored')
    (root / '.env').write_text('SECRET=1')
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('Source payload opened'))
    first = scout.inventory(root, ('data/external',))
    assert first['stats']['files'] == 1
    assert first['stats']['excluded_counts']['managed'] == 1
    assert first['stats']['excluded_counts']['explicit_opaque'] == 1
    assert first['stats']['excluded_counts']['sensitive'] == 1
    second = scout.inventory(root, ('data/external',))
    assert scout.delta(second, first)['change_counts']['metadata_unchanged'] == 1


def test_add_change_remove_and_scope(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'a.txt').write_text('old')
    before = scout.inventory(root)
    (root / 'a.txt').write_text('new content')
    (root / 'b.txt').write_text('added')
    after = scout.inventory(root)
    changes = scout.delta(after, before)
    assert changes['change_counts']['added'] == 1
    assert changes['change_counts']['metadata_changed'] == 1
    assert changes['change_preview']['added'] == ['b.txt']
    (root / 'a.txt').unlink()
    third = scout.inventory(root)
    assert scout.delta(third, after)['change_preview']['missing'] == ['a.txt']
    with pytest.raises(ValueError, match='scope'):
        scout.delta(third, {'schema': 1, 'root': third['root'], 'opaque': ['data'], 'entries': {}})


def test_symlink_and_invalid_opaque(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('secret')
    try:
        (root / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable')
    result = scout.inventory(root)
    assert result['stats']['excluded_counts']['linked'] == 1
    with pytest.raises(ValueError, match='Unsafe'):
        scout.inventory(root, ('../outside',))
    with pytest.raises(ValueError, match='Linked project root'):
        scout.inventory(root / 'linked')


def test_snapshot_only_outside_project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    snapshot = scout.inventory(root)
    with pytest.raises(ValueError, match='outside'):
        scout.write_snapshot(root / 'scan.json', root, snapshot)
    target = tmp_path / 'snapshot.json'
    scout.write_snapshot(target, root, snapshot)
    assert target.exists()


@pytest.mark.parametrize('parent', ['.git', 'sealed_results', '.venv', 'credentials'])
def test_protected_root_and_ancestor_rejected_before_enumeration(tmp_path, monkeypatch, parent):
    root = tmp_path / parent / 'child'
    root.mkdir(parents=True)
    monkeypatch.setattr(scout.os, 'scandir', lambda *args: pytest.fail('Protected root enumerated'))
    with pytest.raises(ValueError, match='Protected project root'):
        scout.inventory(root)


def test_opaque_uses_platform_case_rules(tmp_path):
    root = tmp_path / 'project'
    (root / 'Data' / 'Raw').mkdir(parents=True)
    (root / 'Data' / 'Raw' / 'input.csv').write_text('synthetic')
    result = scout.inventory(root, ('data/raw',))
    assert ('Data/Raw/input.csv' not in result['entries']) == (scout.os.name == 'nt')


def test_snapshot_parent_reparse_rejected_without_writing_inside_project(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    snapshot = scout.inventory(root)
    linked = scout._linked
    # Models a directory reparse point without requiring symlink privileges.
    monkeypatch.setattr(scout, '_linked', lambda path: path == outside or linked(path))
    with pytest.raises(ValueError, match='Linked snapshot path'):
        scout.write_snapshot(outside / 'snapshot.json', root, snapshot)
    assert not (outside / 'snapshot.json').exists()


def test_opaque_invalid_prefix_is_checked_without_symlink_support(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    with pytest.raises(ValueError, match='Unsafe'):
        scout.inventory(root, ('../outside',))


def test_full_delta_includes_changes_beyond_preview_without_unchanged_paths(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    for number in range(27):
        (root / f'old_{number:02}.txt').write_text('old')
    (root / 'stable.txt').write_text('stable')
    before = scout.inventory(root)
    baseline = scout.delta(before, None, include_changes=True)
    assert len(baseline['change_paths']['baseline']) == 28
    assert baseline['change_preview_truncated']['baseline'] is True
    for number in range(27):
        (root / f'new_{number:02}.txt').write_text('new')
        if number < 23:
            (root / f'old_{number:02}.txt').write_text('changed content')
        else:
            (root / f'old_{number:02}.txt').unlink()
    after = scout.inventory(root)
    summary = scout.delta(after, before)
    assert 'change_paths' not in summary
    assert len(summary['change_preview']['added']) == 20
    assert summary['change_preview_truncated']['added'] is True
    assert summary['change_preview_truncated']['metadata_changed'] is True
    complete = scout.delta(after, before, max_preview=0, include_changes=True)
    paths = complete['change_paths']
    assert len(paths['added']) == 27 and 'new_26.txt' in paths['added']
    assert len(paths['metadata_changed']) == 23
    assert paths['missing'] == [f'old_{number:02}.txt' for number in range(23, 27)]
    assert 'metadata_unchanged' not in paths and 'stable.txt' not in json.dumps(paths)
    assert complete['change_counts']['metadata_unchanged'] == 1


def test_sensitive_directory_and_link_names_are_count_only(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'sealed_private_experiment').mkdir()
    (root / 'sealed_private_experiment' / 'result.bin').write_bytes(b'do not read')
    (root / 'secret_payload.txt').write_text('do not read')
    (root / '.git').mkdir()
    scandir = scout.os.scandir
    def guarded_scan(directory):
        assert Path(directory) == root, 'Protected directory was descended into'
        return scandir(directory)
    monkeypatch.setattr(scout.os, 'scandir', guarded_scan)
    result = scout.inventory(root)
    assert result['stats']['excluded_counts']['sensitive'] == 2
    assert 'sealed_private_experiment' not in json.dumps(result)
    assert 'secret_payload.txt' not in json.dumps(result)
    assert result['stats']['excluded_paths'] == [{'path': '.git', 'reason': 'managed'}]
    class SensitiveLink:
        name = 'sealed_link'
        def stat(self, **kwargs):
            pytest.fail('Sensitive link metadata was accessed')
    class Scan:
        def __enter__(self):
            return iter([SensitiveLink()])
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(scout.os, 'scandir', lambda directory: Scan())
    result = scout.inventory(root)
    assert result['stats']['excluded_counts'] == {'sensitive': 1}
    assert 'sealed_link' not in json.dumps(result)


def test_cli_writes_all_changes_externally_but_keeps_stdout_bounded(tmp_path, capsys):
    root = tmp_path / 'project'
    root.mkdir()
    for number in range(27):
        (root / f'item_{number:02}.txt').write_text('synthetic')
    snapshot, changes = tmp_path / 'snapshot.json', tmp_path / 'changes.json'
    assert scout.main(['--root', str(root), '--snapshot-out', str(snapshot),
                       '--changes-out', str(changes), '--max-preview', '2']) == 0
    summary = json.loads(capsys.readouterr().out)
    full = json.loads(changes.read_text(encoding='utf-8'))
    assert len(summary['change_preview']['baseline']) == 2
    assert 'change_paths' not in summary
    assert len(full['changes']['baseline']) == 27
    assert full['change_counts']['baseline'] == 27 and snapshot.exists()
    assert scout.main(['--root', str(root), '--previous', str(snapshot),
                       '--changes-out', str(changes)]) == 0
    capsys.readouterr()
    repeat = json.loads(changes.read_text(encoding='utf-8'))
    assert repeat['change_counts']['metadata_unchanged'] == 27
    assert all(not value for value in repeat['changes'].values())


@pytest.mark.parametrize('collision', ['outputs', 'previous_snapshot', 'previous_changes'])
def test_cli_rejects_output_collisions_before_any_writes(tmp_path, capsys, collision):
    root = tmp_path / 'project'
    root.mkdir()
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps(scout.inventory(root)), encoding='utf-8')
    original = previous.read_bytes()
    snapshot, changes = tmp_path / 'snapshot.json', tmp_path / 'changes.json'
    if collision == 'outputs':
        changes = snapshot
    elif collision == 'previous_snapshot':
        snapshot = previous
    else:
        changes = previous
    with pytest.raises(SystemExit) as error:
        scout.main(['--root', str(root), '--previous', str(previous),
                    '--snapshot-out', str(snapshot), '--changes-out', str(changes)])
    assert error.value.code == 2
    capsys.readouterr()
    assert previous.read_bytes() == original
    assert not (tmp_path / 'snapshot.json').exists()
    assert not (tmp_path / 'changes.json').exists()


def test_cli_rejects_hardlink_alias_of_previous_snapshot(tmp_path, capsys):
    root = tmp_path / 'project'
    root.mkdir()
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps(scout.inventory(root)), encoding='utf-8')
    alias = tmp_path / 'alias.json'
    scout.os.link(previous, alias)
    original = previous.read_bytes()
    with pytest.raises(SystemExit) as error:
        scout.main(['--root', str(root), '--previous', str(previous), '--changes-out', str(alias)])
    assert error.value.code == 2
    capsys.readouterr()
    assert previous.read_bytes() == alias.read_bytes() == original
