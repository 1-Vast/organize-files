"""Task-local snapshots reduce reading without asserting live or semantic truth."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('task_context', SCRIPTS / 'task_context.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def test_batch_reuses_one_read_and_binds_exact_lines(tmp_path):
    (tmp_path / 'report.md').write_bytes(b'protocol\nresult -0.1\nstop\n')
    context = tool.TaskContext(tmp_path)
    result = context.batch([{'source_id': 'report.md', 'start_line': 2, 'end_line': 2},
                            {'source_id': 'report.md', 'start_line': 3, 'end_line': 3}])
    assert result['complete']
    assert [r['excerpt'] for r in result['results']] == ['result -0.1', 'stop']
    assert result['results'][0]['sha256'] == result['results'][1]['sha256']
    assert context.metrics['payload_files_opened'] == 1
    assert context.metrics['cache_hits'] == 1
    recorded = context.record('stop', ['report.md'], facts={'outcome': 'negative'})
    assert recorded['source_locations'] == {'report.md': [
        {'start_line': 2, 'end_line': 2}, {'start_line': 3, 'end_line': 3}]}
    context.result('stop')
    assert context.metrics['payload_files_opened'] == 1


def test_fresh_reads_detect_same_size_and_restored_mtime_changes(tmp_path):
    path = tmp_path / 'report.md'
    path.write_bytes(b'old result\n')
    context = tool.TaskContext(tmp_path)
    initial = context.excerpt('report.md')
    context.record('claim', ['report.md'], facts={'result': 'old'})
    metadata = path.stat()
    path.write_bytes(b'new result\n')
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert context.excerpt('report.md')['sha256'] == initial['sha256']
    assert context.result('claim')['status'] == 'snapshot_reusable'
    result = context.result('claim', fresh=True)
    assert result['status'] == 'stale'
    assert context.metrics['payload_files_opened'] == 2


def test_dependencies_and_unresolved_questions_control_reuse(tmp_path):
    (tmp_path / 'result.txt').write_text('negative\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    context.excerpt('result.txt')
    context.record('experiment', ['result.txt'], facts={'outcome': 'negative'})
    context.record('report', ['result.txt'], facts={'decision': 'stop'}, dependencies=['experiment'])
    context.record('experiment', ['result.txt'], facts={'outcome': 'unresolved'}, unresolved_questions=['Which protocol?'])
    result = context.result('report')
    assert result['status'] == 'stale' and result['invalid_records'] == ['report']
    assert result['unresolved_questions_in_scope'] == ['Which protocol?']
    context.record('report', ['result.txt'], facts={'decision': 'pending'}, dependencies=['experiment'])
    assert context.result('report')['status'] == 'needs_review'


@pytest.mark.parametrize('sid', ['sealed/outcome.txt', 'Data/Raw/input.txt', '.git/config',
                                'passwords.txt', '../outside', '.npmrc', '.pypirc', 'tokens/session.txt'])
def test_protected_and_opaque_sources_never_call_resolver(tmp_path, sid):
    calls = []
    context = tool.TaskContext(tmp_path, opaque=('data/raw',), source_resolver=lambda name: calls.append(name) or b'data')
    result = context.batch([{'source_id': sid}])
    assert result['complete'] is False and not calls
    assert context.metrics['resolver_calls'] == 0


@pytest.mark.parametrize('sid', ['.npmrc', '.pypirc'])
def test_sensitive_configuration_is_rejected_before_local_open(tmp_path, sid):
    (tmp_path / sid).write_text('synthetic-config', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    with pytest.raises(ValueError, match='Protected or opaque'):
        context.excerpt(sid)
    assert context.metrics['payload_files_opened'] == 0


def test_batch_partial_failure_and_fresh_failure_cannot_reuse_old_source(tmp_path):
    path = tmp_path / 'report.md'
    path.write_text('report\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    result = context.batch([{'source_id': 'report.md'}, {'source_id': 'absent.txt'}])
    assert not result['complete']
    assert [r['status'] for r in result['results']] == ['available', 'unavailable']
    assert [r['request_index'] for r in result['results']] == [0, 1]
    context.record('claim', ['report.md'], facts={'result': 'old'})
    path.unlink()
    assert context.result('claim', fresh=True)['status'] == 'stale'
    assert context.result('claim')['status'] == 'stale'


def test_returned_facts_cannot_mutate_record_and_new_task_rereads(tmp_path):
    (tmp_path / 'report.md').write_text('report\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    context.excerpt('report.md')
    result = context.record('claim', ['report.md'], facts={'value': [1]})
    result['facts']['value'].append(2)
    assert context.result('claim')['facts']['value'] == [1]
    other = tool.TaskContext(tmp_path)
    other.excerpt('report.md')
    assert other.metrics['payload_files_opened'] == 1


def test_bounds_binary_and_large_sources_are_rejected(tmp_path):
    (tmp_path / 'binary.txt').write_bytes(b'bad\0data')
    (tmp_path / 'large.txt').write_bytes(b'x' * 100)
    context = tool.TaskContext(tmp_path, max_bytes=20)
    with pytest.raises(ValueError, match='Binary'):
        context.excerpt('binary.txt')
    with pytest.raises(ValueError, match='exceeds'):
        context.excerpt('large.txt')
    assert context.metrics['payload_files_opened'] == 1
    with pytest.raises(ValueError, match='200'):
        context.excerpt('large.txt', 1, 201)


def test_linked_source_is_not_opened_without_symlink_privileges(tmp_path, monkeypatch):
    path = tmp_path / 'report.md'
    path.write_text('report\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    original = tool.evidence.linked_path
    monkeypatch.setattr(tool.evidence, 'linked_path', lambda p: p == path or original(p))
    with pytest.raises(ValueError, match='Linked'):
        context.excerpt('report.md')
    assert context.metrics['payload_files_opened'] == 0


def test_scope_cannot_change_after_caching_and_output_is_bounded(tmp_path):
    context = tool.TaskContext(tmp_path)
    with pytest.raises(AttributeError):
        context.root = tmp_path.parent
    with pytest.raises(AttributeError):
        context.opaque = ()
    (tmp_path / 'one_long_line.txt').write_text('x' * 12001, encoding='utf-8')
    with pytest.raises(ValueError, match='compact output'):
        context.excerpt('one_long_line.txt')


def test_trusted_resolver_is_explicit_and_fresh_batch_reads_each_source_once(tmp_path):
    calls = []
    def resolve(sid):
        calls.append(sid)
        return b'first\nsecond\n'
    context = tool.TaskContext(tmp_path, source_resolver=resolve)
    requests = [{'source_id': 'historical/report.md', 'start_line': 1, 'end_line': 1},
                {'source_id': 'historical/report.md', 'start_line': 2, 'end_line': 2}]
    assert context.batch(requests, fresh=True)['complete']
    assert calls == ['historical/report.md']
    assert context.metrics['resolver_calls'] == 1
    assert context.metrics['payload_files_opened'] == 0


def test_updating_record_cannot_introduce_dependency_cycle(tmp_path):
    (tmp_path / 'report.md').write_text('report\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    context.excerpt('report.md')
    context.record('A', ['report.md'], facts={'step': 'A'})
    context.record('B', ['report.md'], facts={'step': 'B'}, dependencies=['A'])
    with pytest.raises(ValueError, match='cycle'):
        context.record('A', ['report.md'], facts={'step': 'A'}, dependencies=['B'])
    assert context.result('B')['status'] == 'snapshot_reusable'


def test_nonregular_path_rejected_before_payload_open(tmp_path):
    (tmp_path / 'directory.txt').mkdir()
    context = tool.TaskContext(tmp_path)
    with pytest.raises(ValueError, match='not a regular file'):
        context.excerpt('directory.txt')
    assert context.metrics['payload_files_opened'] == 0


def test_failed_batch_request_is_locatable_without_protected_name(tmp_path):
    context = tool.TaskContext(tmp_path)
    result = context.batch([{'source_id': 'sealed/private_report.md'}])
    assert result['results'] == [{'request_index': 0, 'status': 'unavailable', 'error_type': 'ValueError'}]


def test_record_iterators_cannot_silently_drop_sources_or_questions(tmp_path):
    (tmp_path / 'report.md').write_text('report\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    context.excerpt('report.md')
    result = context.record('claim', iter(['report.md']), facts={'result': 'pending'},
                            unresolved_questions=iter(['What condition?']))
    assert result['source_bindings'].keys() == {'report.md'}
    assert result['status'] == 'needs_review'
    with pytest.raises(ValueError, match='selected sources'):
        context.record('empty', iter([]), facts={})
