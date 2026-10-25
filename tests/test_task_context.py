"""Task-local snapshots reduce reading without asserting live or semantic truth."""
import importlib.util
import json
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


def test_required_context_gaps_survive_compaction_and_dependencies(tmp_path):
    (tmp_path / 'report.md').write_text('Result: 0.70\nShared latents only\nReplay not completed\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    result = context.excerpt('report.md', 1, 1)
    recorded = context.record('claim', ['report.md'], facts={'result': 0.70},
                              required_context=iter(['result', 'conditions', 'replay']),
                              context_reviews={'result': {'status': 'reviewed', 'note': 'Observed value', 'citations': [result]}})
    assert recorded['status'] == 'needs_review'
    assert recorded['context_gaps'] == {'claim': ['conditions', 'replay']}
    context.record('report', ['report.md'], facts={'text': 'x' * 10000}, dependencies=['claim'])
    brief = context.result('report', compact=True)
    full = context.result('report')
    for field in ('status', 'closure_status', 'context_gaps', 'signature', 'source_bindings', 'source_locations'):
        assert brief[field] == full[field]
    assert brief['closure_status'] == 'needs_review'
    assert 'facts' not in brief and 'context_reviews' not in brief
    assert len(json.dumps(brief)) < len(json.dumps(full))
    assert context.metrics['payload_files_opened'] == 1


def test_reviewed_context_is_snapshot_declaration_and_output_edits_invalidate_it(tmp_path):
    (tmp_path / 'source.md').write_text('Development result\nReplay unavailable\n', encoding='utf-8')
    output = tmp_path / 'REPORT.md'
    output.write_text('Development result; replay unavailable\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    source = context.excerpt('source.md')
    report = context.excerpt('REPORT.md')
    context.record('output', ['source.md', 'REPORT.md'], facts={'scope': 'development'},
                   required_context=['limitations'], context_reviews={
                       'limitations': {'status': 'reviewed', 'note': 'Report preserves replay boundary', 'citations': [source, report]}})
    assert context.result('output', compact=True)['closure_status'] == 'declared_covered'
    output.write_text('Confirmed result; replay available\n', encoding='utf-8')
    assert context.result('output', fresh=True, compact=True)['closure_status'] == 'stale'
    assert context.result('output')['invalid_records'] == ['output']


@pytest.mark.parametrize('change', [
    {'sha256': '0' * 64}, {'excerpt': 'fabricated condition'}, {'start_line': True},
    {'end_line': 2}, {'source_id': 'other.md'},
])
def test_review_rejects_forged_or_unread_citations_without_replacing_record(tmp_path, change):
    (tmp_path / 'report.md').write_text('Result\nCondition\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    citation = context.excerpt('report.md', 1, 1)
    before = context.record('claim', ['report.md'], facts={'result': 'pending'}, required_context=['conditions'])
    with pytest.raises(ValueError, match='citations'):
        context.record('claim', ['report.md'], facts={}, required_context=['conditions'], context_reviews={
            'conditions': {'status': 'reviewed', 'note': 'Condition review', 'citations': [{**citation, **change}]}})
    assert context.result('claim')['signature'] == before['signature']


@pytest.mark.parametrize('required,reviews', [
    ('conditions', {}), (['conditions', 'conditions'], {}), ([''], {}),
    (['conditions'], {'replay': {}}), (['conditions'], {'conditions': {}}),
    (['conditions'], {'conditions': {'status': 'reviewed', 'note': 'not recorded', 'citations': []}}),
])
def test_empty_or_malformed_reviews_cannot_close_a_gap(tmp_path, required, reviews):
    (tmp_path / 'report.md').write_text('Result\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    context.excerpt('report.md')
    with pytest.raises(ValueError):
        context.record('claim', ['report.md'], facts={}, required_context=required, context_reviews=reviews)


def test_new_review_invalidates_dependent_record_until_rebound(tmp_path):
    (tmp_path / 'report.md').write_text('Shared latents only\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    citation = context.excerpt('report.md')
    context.record('claim', ['report.md'], facts={}, required_context=['conditions'])
    context.record('summary', ['report.md'], facts={}, dependencies=['claim'])
    context.record('claim', ['report.md'], facts={}, required_context=['conditions'], context_reviews={
        'conditions': {'status': 'reviewed', 'note': 'Limited to shared latents', 'citations': [citation]}})
    assert context.result('summary', compact=True)['status'] == 'stale'
    context.record('summary', ['report.md'], facts={}, dependencies=['claim'])
    assert context.result('summary')['status'] == 'snapshot_reusable'
    assert context.result('summary')['closure_status'] == 'not_assessed'


def test_questions_and_failed_refresh_remain_visible_in_compact_output(tmp_path):
    path = tmp_path / 'report.md'
    path.write_text('Unknown protocol\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    citation = context.excerpt('report.md')
    context.record('claim', ['report.md'], facts={}, required_context=['protocol'], context_reviews={
        'protocol': {'status': 'unknown', 'note': 'Source does not record protocol', 'citations': [citation]}},
        unresolved_questions=['Which protocol produced this result?'])
    assert context.result('claim', compact=True)['closure_status'] == 'needs_review'
    path.unlink()
    result = context.result('claim', fresh=True, compact=True)
    assert result['status'] == 'stale' and result['errors']
    assert result['unresolved_questions_in_scope'] == ['Which protocol produced this result?']


def test_unknown_context_cannot_pass_even_without_an_extra_question(tmp_path):
    (tmp_path / 'report.md').write_text('Protocol was not recorded\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    citation = context.excerpt('report.md')
    context.record('claim', ['report.md'], facts={}, required_context=['protocol'], context_reviews={
        'protocol': {'status': 'unknown', 'note': 'No protocol in retained record', 'citations': [citation]}})
    result = context.result('claim', fresh=True, compact=True)
    assert result['status'] == result['closure_status'] == 'needs_review'
    assert result['context_gaps'] == {'claim': ['protocol']}


def test_unchanged_refresh_preserves_citations_but_changed_bytes_reject_them(tmp_path):
    path = tmp_path / 'report.md'
    path.write_text('Shared latents only\n', encoding='utf-8')
    context = tool.TaskContext(tmp_path)
    citation = context.excerpt('report.md')
    review = {'conditions': {'status': 'reviewed', 'note': 'Shared latents', 'citations': [citation]}}
    context.record('claim', ['report.md'], facts={}, required_context=['conditions'], context_reviews=review)
    context.result('claim', fresh=True)
    result = context.record('claim', ['report.md'], facts={}, required_context=['conditions'], context_reviews=review)
    assert result['closure_status'] == 'declared_covered'
    path.write_text('Independent latents\n', encoding='utf-8')
    context.result('claim', fresh=True)
    with pytest.raises(ValueError, match='citations'):
        context.record('claim', ['report.md'], facts={}, required_context=['conditions'], context_reviews=review)
