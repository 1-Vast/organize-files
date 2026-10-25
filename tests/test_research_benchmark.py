"""Small research-asset integration benchmark; no claim of semantic or agent superiority."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import statistics
import zipfile

import pytest


SKILL = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_fixture(root: Path):
    """Create identical public inputs. Evaluator facts remain in this test, outside root."""
    root.mkdir(parents=True, exist_ok=False)
    payloads = {
        'README.md': b'# Synthetic research workspace\nInspect reports, data and execution records.\n',
        'legacy/hypothesis.md': b'H1: context feedback improves mean accuracy over 0.65.\n',
        'legacy/result.md': b'Old summary: three-seed mean accuracy is 0.80.\n',
        'legacy/erratum.md': b'Correction: seeds 7/8/9 scored 0.60/0.70/0.80; mean 0.70. The old 0.80 was the best seed.\n',
        'experiments/positive/metrics.csv': b'seed,accuracy\n7,0.60\n8,0.70\n9,0.80\n',
        'experiments/positive/run.py': b'import csv, statistics\nfrom pathlib import Path\nrows = csv.DictReader(Path(__file__).with_name("metrics.csv").open())\nprint(statistics.mean(float(r["accuracy"]) for r in rows))\n',
        'experiments/negative/result.json': b'{"status":"completed","candidate":0.68,"baseline":0.70,"decision":"stop_this_extension","independent_confirmation":false}\n',
        'experiments/interrupted/console.log': b'Status: incomplete\nFileNotFoundError: missing input matrix\nNo accuracy was computed.\n',
        'draft_a/result.txt': b'Unique note A: measured feedback used eight actions.\n',
        'draft_b/result.txt': b'Unique note B: donor-generalization experiment was not run.\n',
        'papers/source.txt': b'Synthetic source S1, version 2; exposed development data only.\n',
        'frozen/trace.bin': bytes(range(256)) + b'\x00\xfffrozen raw trace\r\n',
        'notes/unrelated.txt': b'Control topic: microscope booking, unrelated to H1.\n',
        '.env': b'SYNTHETIC_SECRET=do-not-read-or-index\n',
        'sealed/outcome.bin': b'SYNTHETIC_SEALED_OUTCOME_DO_NOT_OPEN\x00\xff',
    }
    config = {'learning_rate': 0.001, 'seeds': [7, 8, 9], 'code_sha256': sha(payloads['experiments/positive/run.py']),
              'source_id': 'S1', 'source_version': 2, 'exposure': 'development'}
    payloads['experiments/positive/config.json'] = (json.dumps(config, sort_keys=True) + '\n').encode()
    freeze = {'files': {name: sha(payloads[name]) for name in
                        ('frozen/trace.bin', 'experiments/positive/config.json', 'experiments/positive/run.py')}}
    payloads['frozen/FREEZE.json'] = (json.dumps(freeze, sort_keys=True) + '\n').encode()
    for name, data in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {name: sha(data) for name, data in payloads.items() if name != '.env' and not name.startswith('sealed/')}


def write_reviewed_report(root):
    """A supplied reference output, not an output generated or semantically judged by the tools."""
    (root / 'REPORT.md').write_text('''# Context-feedback research

H1 asked whether context feedback improves accuracy over the fixed 0.65 reference.
The exposed S1 version-2 development run used learning rate 0.001 and seeds 7, 8 and 9.
Its accuracies were 0.60, 0.70 and 0.80, so the mean is 0.70. The former 0.80 summary
reported the best seed as the mean. This corrects aggregation; it is not independent confirmation.

The extension completed but scored 0.68 against 0.70, so that extension was stopped.
The interrupted run had a missing input and computed no accuracy; it cannot refute H1.
Feedback used eight actions; donor generalization was not run. Those two facts came
from different notes with the same basename and are not duplicate information.

Use the [metrics](experiments/positive/metrics.csv), [parameters](experiments/positive/config.json),
[code](experiments/positive/run.py), [source](papers/source.txt),
[negative result](experiments/negative/result.json), [interruption](experiments/interrupted/console.log)
and [frozen bindings](frozen/FREEZE.json) to check the claims. Detailed notes are
[A](research_notes/feedback.txt) and [B](research_notes/generalization.txt).
The missing donor experiment is a recorded limitation, not permission to run it.
''', encoding='utf-8')


def fixture_index():
    def obj(identity, kind, status, path, **extra):
        return {'id': identity, 'kind': kind, 'status': status, 'sources': [{'path': path}], **extra}
    return {'schema_version': 1, 'excluded_sources': ['.env', 'sealed'], 'objects': [
        obj('exp:positive', 'experiment', 'completed_development', 'experiments/positive/metrics.csv', stage='exploration'),
        obj('exp:negative', 'experiment', 'completed_negative', 'experiments/negative/result.json', stage='exploration'),
        obj('exp:interrupted', 'experiment', 'incomplete', 'experiments/interrupted/console.log', stage='exploration'),
        obj('claim:mean', 'claim', 'corrected_development_only', 'legacy/erratum.md'),
        obj('decision:continue', 'decision', 'independent_confirmation_not_established', 'legacy/hypothesis.md'),
        obj('report:current', 'report', 'maintained', 'REPORT.md'),
        obj('note:unrelated', 'note', 'unrelated', 'notes/unrelated.txt'),
        {'id': 'asset:sealed', 'kind': 'asset', 'status': 'protected',
         'sources': [{'path': 'sealed/outcome.bin', 'protected': True}]},
    ], 'relations': [
        {'from': 'exp:positive', 'to': 'claim:mean', 'type': 'supports'},
        {'from': 'decision:continue', 'to': 'claim:mean', 'type': 'depends_on'},
        {'from': 'report:current', 'to': 'claim:mean', 'type': 'depends_on'},
        {'from': 'report:current', 'to': 'exp:negative', 'type': 'depends_on'},
        {'from': 'report:current', 'to': 'exp:interrupted', 'type': 'depends_on'},
    ]}


def current_broken_links(root):
    broken = []
    for document in root.rglob('*.md'):
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', document.read_text('utf-8')):
            if '://' not in target and not target.startswith('#') and not (document.parent / target.split('#')[0]).exists():
                broken.append((document.relative_to(root).as_posix(), target))
    return broken


def test_refactoring_reduces_scattered_files_and_preserves_every_original(tmp_path):
    ops = load_tool('organization_ops')
    root = tmp_path / 'project'
    baseline = build_fixture(root)
    before_count = sum(p.is_file() for p in root.rglob('*'))
    protected_metadata = {name: ((root / name).stat().st_size, (root / name).stat().st_mtime_ns)
                          for name in ('.env', 'sealed/outcome.bin')}
    write_reviewed_report(root)
    changes = []
    for name in ('legacy/hypothesis.md', 'legacy/result.md', 'legacy/erratum.md'):
        changes.append({'op': 'remove', 'source': name, 'sha256': baseline[name],
                        'reason': 'Consolidated into the supplied detailed scientific report',
                        'evidence': {'coverage': 'REPORT.md includes hypothesis, all seeds, correction and limits',
                                     'review': 'Fixture reference synthesis; semantic quality needs separate review'}})
    destinations = {'draft_a/result.txt': 'research_notes/feedback.txt',
                    'draft_b/result.txt': 'research_notes/generalization.txt'}
    for old, new in destinations.items():
        changes.append({'op': 'move', 'source': old, 'target': new, 'sha256': baseline[old],
                        'reason': 'Different notes share a basename; preserve their distinct purposes'})
    plan = {'schema': 1, 'root': str(root), 'operations': changes}
    preview = ops.dry_run(plan)
    assert len(preview) == 5
    assert all((root / name).is_file() for name in baseline)
    state_dir = tmp_path / 'recovery'
    state = ops.apply_plan(plan, state_dir)
    assert state['status'] == 'applied'
    recovered = {}
    with zipfile.ZipFile(state_dir / 'recovery.zip') as archive:
        for i, operation in enumerate(state['operations']):
            recovered[operation['source']] = sha(archive.read(str(i)))
    for original, expected in baseline.items():
        current = root / destinations.get(original, original)
        assert (sha(current.read_bytes()) if current.exists() else recovered.get(original)) == expected
    assert sum(p.is_file() for p in root.rglob('*')) == before_count - 2
    assert len(state['operations']) == 5  # Recovery members are not counted as project-file reduction.
    assert current_broken_links(root) == []
    for name, metadata in protected_metadata.items():
        path = root / name
        assert (path.stat().st_size, path.stat().st_mtime_ns) == metadata
    freeze = json.loads((root / 'frozen/FREEZE.json').read_text('utf-8'))
    assert all(sha((root / path).read_bytes()) == expected for path, expected in freeze['files'].items())
    with (root / 'experiments/positive/metrics.csv').open() as stream:
        scores = [float(row['accuracy']) for row in csv.DictReader(stream)]
    assert statistics.mean(scores) == pytest.approx(0.70)
    assert json.loads((root / 'experiments/negative/result.json').read_text())['status'] == 'completed'
    ops.rollback(state_dir)
    assert all(sha((root / name).read_bytes()) == expected for name, expected in baseline.items())


def test_incremental_review_reaches_dependents_without_rewriting_them(tmp_path):
    evidence = load_tool('evidence_index')
    root = tmp_path / 'project'
    build_fixture(root)
    write_reviewed_report(root)
    index = fixture_index()
    before = evidence.snapshot_index(index, root)
    report_before = (root / 'REPORT.md').read_bytes()
    path = root / 'experiments/positive/metrics.csv'
    path.write_bytes(path.read_bytes().replace(b'9,0.80', b'9,0.83'))
    after = evidence.snapshot_index(index, root)
    result = evidence.impact(before, after)
    assert set(result['direct_changes']) == {'exp:positive'}
    assert set(result['affected_objects']) == {'claim:mean', 'decision:continue', 'report:current'}
    assert {'exp:negative', 'exp:interrupted', 'note:unrelated'} <= set(result['reusable_objects'])
    assert (root / 'REPORT.md').read_bytes() == report_before
    # The tool identifies a review boundary. It does not compute a new scientific decision.
    assert set(result['review_required']) == {'exp:positive', 'claim:mean', 'decision:continue', 'report:current'}


def test_incremental_review_does_not_call_incomplete_execution_a_negative_result(tmp_path):
    evidence = load_tool('evidence_index')
    root = tmp_path / 'project'
    build_fixture(root)
    write_reviewed_report(root)
    index = fixture_index()
    before = evidence.snapshot_index(index, root)
    (root / 'experiments/interrupted/console.log').unlink()
    after = evidence.snapshot_index(index, root)
    result = evidence.impact(before, after)
    assert set(result['direct_changes']) == {'exp:interrupted'}
    assert set(result['affected_objects']) == {'report:current'}
    assert 'claim:mean' in result['reusable_objects']
    assert next(obj for obj in index['objects'] if obj['id'] == 'exp:interrupted')['status'] == 'incomplete'


def test_linked_root_cannot_expand_the_scientific_scope(tmp_path):
    evidence = load_tool('evidence_index')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'result.csv').write_bytes(b'outside scope')
    linked = tmp_path / 'linked-project'
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('Creating directory links unavailable')
        import _winapi
        _winapi.CreateJunction(str(outside), str(linked))
    index = {'schema_version': 1, 'objects': [{'id': 'x', 'kind': 'source', 'status': 'declared',
                                             'sources': [{'path': 'result.csv'}]}]}
    try:
        assert not evidence.validate_index(index, linked)['valid']
    finally:
        if linked.is_symlink():
            linked.unlink()
        else:
            linked.rmdir()


def test_hardlink_cannot_bypass_a_protected_source_name(tmp_path, monkeypatch):
    evidence = load_tool('evidence_index')
    root = tmp_path / 'project'
    root.mkdir()
    secret = root / '.env'
    secret.write_bytes(b'SYNTHETIC_SECRET')
    os.link(secret, root / 'innocent.csv')
    index = {'schema_version': 1, 'objects': [{'id': 'x', 'kind': 'source', 'status': 'declared',
                                             'sources': [{'path': 'innocent.csv'}]}]}
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('Opened linked protected payload'))
    assert not evidence.validate_index(index, root)['valid']


@pytest.mark.parametrize('alias', ['a.txt.', 'a.txt ', '.git./config', '.git /config'])
def test_windows_name_aliases_do_not_bypass_scope_or_conflict_guards(tmp_path, alias):
    evidence, ops = load_tool('evidence_index'), load_tool('organization_ops')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'a.txt').write_bytes(b'A')
    index = {'schema_version': 1, 'objects': [{'id': 'x', 'kind': 'source', 'status': 'declared',
                                             'sources': [{'path': alias}]}]}
    assert not evidence.validate_index(index, root)['valid']
    plan = {'schema': 1, 'root': str(root), 'operations': [
        {'op': 'move', 'source': 'a.txt', 'sha256': sha(b'A'), 'target': alias, 'reason': 'test scope'}]}
    with pytest.raises(ValueError):
        ops.dry_run(plan)


def test_recovery_refuses_a_later_hardlink_without_touching_external_metadata(tmp_path):
    ops = load_tool('organization_ops')
    root = tmp_path / 'project'
    root.mkdir()
    source = root / 'note.txt'
    source.write_bytes(b'original')
    plan = {'schema': 1, 'root': str(root), 'operations': [
        {'op': 'remove', 'source': 'note.txt', 'sha256': sha(b'original'), 'reason': 'covered note',
         'evidence': {'coverage': 'supplied report', 'review': 'fixture'}}]}
    state = tmp_path / 'state'
    ops.apply_plan(plan, state)
    outside = tmp_path / 'external.txt'
    outside.write_bytes(b'original')
    os.utime(outside, ns=(1_000_000_000, 2_000_000_000))
    os.link(outside, source)
    metadata = outside.stat().st_mtime_ns
    with pytest.raises(ValueError):
        ops.rollback(state)
    assert outside.stat().st_mtime_ns == metadata
