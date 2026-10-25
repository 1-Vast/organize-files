"""Deterministic operation guards and real recovery, without scientific fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/organization_ops.py'
SPEC = importlib.util.spec_from_file_location('organization_ops_under_test', SCRIPT)
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def make_plan(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    sources = {'draft.md': b'old report\r\n', 'raw.bin': b'\x00\xff\x01',
               'notes.txt': b'covered detail', 'prepared.md': b'detailed new report\n'}
    for name, data in sources.items():
        (root / name).write_bytes(data)
    digest = lambda name: hashlib.sha256(sources[name]).hexdigest()
    evidence = {'coverage': ['all unique observations retained in prepared.md'], 'review': 'independent fixture review'}
    plan = {'schema': 1, 'root': str(root), 'operations': [
        {'op': 'move', 'source': 'raw.bin', 'sha256': digest('raw.bin'), 'target': 'data/raw.bin', 'reason': 'group input'},
        {'op': 'remove', 'source': 'notes.txt', 'sha256': digest('notes.txt'), 'reason': 'covered in report', 'evidence': evidence},
        {'op': 'replace', 'source': 'draft.md', 'sha256': digest('draft.md'), 'replacement': 'prepared.md',
         'replacement_sha256': digest('prepared.md'), 'reason': 'integrate corrected findings', 'evidence': evidence},
    ]}
    return root, sources, plan


def test_dry_run_does_not_write_and_apply_round_trip_preserves_bytes_and_mtime(tmp_path):
    root, sources, plan = make_plan(tmp_path)
    original = {name: ((root / name).stat().st_mtime_ns, (root / name).stat().st_mode) for name in sources}
    assert ops.dry_run(plan) == plan['operations']
    assert {p.name for p in root.iterdir()} == set(sources)
    state_dir = tmp_path / 'transaction'
    state = ops.apply_plan(plan, state_dir)
    assert state['status'] == 'applied'
    assert (root / 'data/raw.bin').read_bytes() == sources['raw.bin']
    assert not (root / 'raw.bin').exists() and not (root / 'notes.txt').exists()
    assert (root / 'draft.md').read_bytes() == sources['prepared.md']
    with zipfile.ZipFile(state_dir / 'recovery.zip') as archive:
        assert [archive.read(str(i)) for i in range(3)] == [sources['raw.bin'], sources['notes.txt'], sources['draft.md']]
    assert ops.rollback(state_dir)['status'] == 'rolled_back'
    for name, data in sources.items():
        assert (root / name).read_bytes() == data
        assert ((root / name).stat().st_mtime_ns, (root / name).stat().st_mode) == original[name]
    assert not (root / 'data/raw.bin').exists()
    assert ops.rollback(state_dir)['status'] == 'rolled_back'


def test_source_changed_after_plan_is_rejected_before_creating_state(tmp_path):
    root, _, plan = make_plan(tmp_path)
    (root / 'notes.txt').write_bytes(b'new independent finding')
    with pytest.raises(ValueError, match='Source changed'):
        ops.apply_plan(plan, tmp_path / 'transaction')
    assert not (tmp_path / 'transaction').exists()
    assert (root / 'raw.bin').is_file()


@pytest.mark.parametrize('path', ['../outside', '/absolute', 'C:relative', 'C:/absolute', 'a/../b', 'file:stream', '.git/config',
                                 'file.txt.', 'file.txt ', '.git./config', 'dir/NUL.txt', 'a/COM1', 'LPT²', 'conin$'])
def test_path_escape_and_managed_git_are_rejected(tmp_path, path):
    _, _, plan = make_plan(tmp_path)
    plan['operations'][0]['target'] = path
    with pytest.raises(ValueError):
        ops.dry_run(plan)


def test_existing_target_is_not_overwritten(tmp_path):
    root, _, plan = make_plan(tmp_path)
    (root / 'data').mkdir()
    (root / 'data/raw.bin').write_bytes(b'different raw source')
    with pytest.raises(ValueError, match='Destination already exists'):
        ops.apply_plan(plan, tmp_path / 'transaction')
    assert (root / 'data/raw.bin').read_bytes() == b'different raw source'


def test_overlapping_operations_are_rejected(tmp_path):
    root, sources, plan = make_plan(tmp_path)
    plan['operations'][0]['target'] = 'notes.txt'
    with pytest.raises(ValueError):
        ops.dry_run(plan)
    plan['operations'][0]['target'] = 'notes.txt/child'
    # POSIX rejects a file used as a parent before the overlap check; Windows
    # can reach the overlap guard. Both must reject without changing sources.
    with pytest.raises((ValueError, NotADirectoryError)):
        ops.dry_run(plan)
    assert {name: (root / name).read_bytes() for name in sources} == sources


def test_replacement_source_cannot_also_be_changed(tmp_path):
    _, _, plan = make_plan(tmp_path)
    plan['operations'][2]['replacement'] = 'notes.txt'
    plan['operations'][2]['replacement_sha256'] = plan['operations'][1]['sha256']
    with pytest.raises(ValueError, match='replacement source'):
        ops.dry_run(plan)


def test_symlinked_target_parent_is_rejected_without_following_it(tmp_path):
    root, _, plan = make_plan(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            raise
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(root / 'linked'), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip('Neither symlinks nor junctions are available')
    plan['operations'][0]['target'] = 'linked/raw.bin'
    with pytest.raises(ValueError, match='reparse point'):
        ops.dry_run(plan)
    assert not list(outside.iterdir())


def test_remove_and_replace_require_review_record_not_implicit_semantic_proof(tmp_path):
    _, _, plan = make_plan(tmp_path)
    del plan['operations'][1]['evidence']
    with pytest.raises(ValueError, match='declared evidence'):
        ops.dry_run(plan)


def test_hardlink_topology_is_not_silently_lost_in_recovery(tmp_path):
    root, _, plan = make_plan(tmp_path)
    os.link(root / 'raw.bin', root / 'second-name.bin')
    with pytest.raises(ValueError, match='Hard-linked'):
        ops.dry_run(plan)


def test_rollback_does_not_change_external_hardlink_metadata(tmp_path):
    root, sources, plan = make_plan(tmp_path)
    state_dir = tmp_path / 'transaction'
    ops.apply_plan(plan, state_dir)
    outside = tmp_path / 'external.txt'
    outside.write_bytes(sources['notes.txt'])
    os.utime(outside, ns=(2_000_000_000, 2_000_000_000))
    os.link(outside, root / 'notes.txt')
    before = outside.stat().st_mtime_ns
    with pytest.raises(ValueError, match='hard-linked'):
        ops.rollback(state_dir)
    assert outside.stat().st_mtime_ns == before
    assert outside.read_bytes() == sources['notes.txt']
    assert not (root / 'raw.bin').exists()


@pytest.mark.parametrize('target', ['draft.md', 'data/raw.bin', 'notes.txt'])
def test_rollback_refuses_later_changes_before_restoring_any_file(tmp_path, target):
    root, _, plan = make_plan(tmp_path)
    state_dir = tmp_path / 'transaction'
    ops.apply_plan(plan, state_dir)
    (root / target).write_bytes(b'external new finding')
    with pytest.raises(ValueError):
        ops.rollback(state_dir)
    assert (root / target).read_bytes() == b'external new finding'
    assert not (root / 'raw.bin').exists()


def test_partial_execution_can_be_recovered_and_pending_sources_are_untouched(tmp_path, monkeypatch):
    root, sources, plan = make_plan(tmp_path)
    state_dir = tmp_path / 'transaction'
    original = ops._apply_one
    calls = []
    def fail_second(root, item):
        calls.append(item['op'])
        if len(calls) == 2:
            raise OSError('simulated sharing violation')
        original(root, item)
    monkeypatch.setattr(ops, '_apply_one', fail_second)
    with pytest.raises(OSError, match='sharing violation'):
        ops.apply_plan(plan, state_dir)
    state = json.loads((state_dir / 'state.json').read_text('utf8'))
    assert state['status'] == 'failed'
    assert [x['status'] for x in state['operations']] == ['done', 'started', 'pending']
    assert ops.rollback(state_dir)['status'] == 'rolled_back'
    assert all((root / name).read_bytes() == content for name, content in sources.items())


def test_crash_after_move_copy_before_source_removal_is_recoverable(tmp_path, monkeypatch):
    root, sources, plan = make_plan(tmp_path)
    def fail_after_copy(root, item):
        ops._copy_exclusive(root / item['source'], root / item['target'])
        raise OSError('interrupted after destination creation')
    monkeypatch.setattr(ops, '_apply_one', fail_after_copy)
    state_dir = tmp_path / 'transaction'
    with pytest.raises(OSError):
        ops.apply_plan(plan, state_dir)
    assert ops.rollback(state_dir)['status'] == 'rolled_back'
    assert (root / 'raw.bin').read_bytes() == sources['raw.bin']
    assert not (root / 'data/raw.bin').exists()


def test_corrupt_recovery_is_rejected_without_restoring_files(tmp_path):
    root, _, plan = make_plan(tmp_path)
    state_dir = tmp_path / 'transaction'
    ops.apply_plan(plan, state_dir)
    with (state_dir / 'recovery.zip').open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='checksum mismatch'):
        ops.rollback(state_dir)
    assert not (root / 'notes.txt').exists()


def test_state_cannot_be_reused_or_placed_inside_workspace(tmp_path):
    root, _, plan = make_plan(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        ops.apply_plan(plan, root / 'state')
    state_dir = tmp_path / 'already-exists'
    state_dir.mkdir()
    with pytest.raises(ValueError, match='already exist'):
        ops.apply_plan(plan, state_dir)


def test_cli_dry_run_and_help(tmp_path):
    _, _, plan = make_plan(tmp_path)
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan), encoding='utf8')
    result = subprocess.run([sys.executable, str(SCRIPT), 'dry-run', str(plan_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)) == 3


@pytest.mark.parametrize('field,name', [('source', 'sealed/source.bin'), ('target', 'blind/result.bin'),
                                      ('source', '.env'), ('target', 'credentials/result.bin'),
                                      ('replacement', 'private.key')])
def test_default_protected_paths_rejected_before_payload_read(tmp_path, monkeypatch, field, name):
    _, _, plan = make_plan(tmp_path)
    item = plan['operations'][2 if field == 'replacement' else 0]
    item[field] = name
    plan['operations'] = [item]
    monkeypatch.setattr(ops, 'digest', lambda *args: pytest.fail('Protected operation read a payload'))
    with pytest.raises(ValueError, match='Protected'):
        ops.dry_run(plan)


@pytest.mark.parametrize('field', ['source', 'target', 'replacement'])
def test_declared_protection_is_case_insensitive_prefix_and_checked_before_reads(tmp_path, monkeypatch, field):
    _, _, plan = make_plan(tmp_path)
    item = plan['operations'][2 if field == 'replacement' else 0]
    item[field] = 'Study/Reserve/input.bin'
    plan['operations'] = [item]
    plan['protected_sources'] = ['study/reserve']
    monkeypatch.setattr(ops, 'digest', lambda *args: pytest.fail('Declared protected payload read'))
    with pytest.raises(ValueError, match='Protected'):
        ops.dry_run(plan)


def test_protection_prefix_does_not_match_sibling_name(tmp_path):
    _, _, plan = make_plan(tmp_path)
    plan['protected_sources'] = ['raw']
    assert ops.dry_run(plan) == plan['operations']


@pytest.mark.parametrize('protection', ['outside', ['../outside'], ['C:/outside']])
def test_invalid_protection_prefix_rejected(tmp_path, protection):
    _, _, plan = make_plan(tmp_path)
    plan['protected_sources'] = protection
    with pytest.raises(ValueError):
        ops.dry_run(plan)


def test_recovery_policy_and_operation_paths_cannot_be_changed_in_journal(tmp_path):
    root, _, plan = make_plan(tmp_path)
    plan['protected_sources'] = ['reserve']
    state_dir = tmp_path / 'transaction'
    state = ops.apply_plan(plan, state_dir)
    for mutate in ('policy', 'source', 'target', 'replacement'):
        altered = json.loads(json.dumps(state))
        if mutate == 'policy':
            altered['protected_sources'] = []
        else:
            altered['operations'][2 if mutate == 'replacement' else 0][mutate] = 'reserve/asset.bin'
        (state_dir / 'state.json').write_text(json.dumps(altered), encoding='utf-8')
        with pytest.raises(ValueError, match='policy differs'):
            ops.rollback(state_dir)
        assert not (root / 'raw.bin').exists()
    (state_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    assert ops.rollback(state_dir)['status'] == 'rolled_back'


def test_legacy_recovery_requires_separately_reviewed_restore(tmp_path):
    root, _, plan = make_plan(tmp_path)
    state_dir = tmp_path / 'transaction'
    state = ops.apply_plan(plan, state_dir)
    archive_path = state_dir / 'recovery.zip'
    with zipfile.ZipFile(archive_path) as archive:
        members = [(name, archive.read(name)) for name in archive.namelist() if name != 'plan.json']
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for name, data in members:
            archive.writestr(name, data)
    state['recovery_sha256'] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (state_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    with pytest.raises(ValueError, match='Legacy recovery'):
        ops.rollback(state_dir)
    assert not (root / 'raw.bin').exists()


def test_large_overlap_index_matches_pairwise_reference():
    writes = [Path('/workspace') / f'group{i % 71}' / f'file{i}.bin' for i in range(6000)]
    reads = [Path('/workspace') / 'prepared' / f'file{i}.bin' for i in range(1000)]
    ops._check_overlap(writes, reads)
    for left, right in [(Path('/root/A'), Path('/root/a/child')), (Path('/root/a/child'), Path('/root/A'))]:
        with pytest.raises(ValueError, match='overlap'):
            ops._check_overlap([left], [right])
    # Read/read ancestry remains legal; only changes must be disjoint.
    ops._check_overlap([Path('/root/output')], [Path('/root/read'), Path('/root/read/child')])


def test_fixed_random_overlap_cases_match_original_rule():
    import random
    rng = random.Random(71023)
    pool = [Path('/workspace') / '/'.join(rng.choices(['a', 'b', 'c', 'd'], k=rng.randint(1, 5))) for _ in range(100)]
    for _ in range(300):
        writes, reads = rng.sample(pool, 5), rng.sample(pool, 5)
        expected = (len(set(writes)) != len(writes) or bool(set(writes) & set(reads))
                    or any(a != b and (a in b.parents or b in a.parents) for a in writes for b in writes + reads))
        try:
            ops._check_overlap(writes, reads)
        except ValueError:
            assert expected
        else:
            assert not expected


def test_hardlinked_sensitive_payload_is_rejected_before_hashing(tmp_path, monkeypatch):
    root, _, plan = make_plan(tmp_path)
    os.link(root / 'raw.bin', root / '.env')
    monkeypatch.setattr(ops, 'digest', lambda *args: pytest.fail('Hard-linked source payload read'))
    with pytest.raises(ValueError, match='Hard-linked'):
        ops.dry_run(plan)


def test_protected_root_cannot_be_used_to_hide_sensitive_prefix(tmp_path, monkeypatch):
    root = tmp_path / 'sealed_source'
    root.mkdir()
    monkeypatch.setattr(ops, 'digest', lambda *args: pytest.fail('Protected root payload read'))
    with pytest.raises(ValueError, match='Protected'):
        ops.dry_run({'schema': 1, 'root': str(root), 'operations': [{'op':'move','source':'a','target':'b','sha256':'0'*64,'reason':'test'}]})
