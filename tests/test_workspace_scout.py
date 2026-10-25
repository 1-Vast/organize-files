import importlib.util
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
