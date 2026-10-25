"""Actual MAESTRO sources/excerpts exercise bounded fact checks, not Agent superiority."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('claim_coverage', ROOT / 'scripts/claim_coverage.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
FIXTURE = json.loads((ROOT / 'tests/fixtures/maestro_claim_coverage.json').read_text(encoding='utf-8'))


def reviewed(claim):
    """Fixture assertion only; the checker cannot authenticate real reviewers."""
    claim = copy.deepcopy(claim)
    claim['review'] = {'status': 'approved', 'reviewer': 'fixture-evaluator',
                       'binding_sha256': tool.review_binding(claim)}
    return claim


def resolve(sid):
    return FIXTURE['source_payloads'][sid].encode('utf-8')


def audit(claim, report=None, resolver=resolve):
    return tool.audit_claims([claim], (report or FIXTURE['after_report']).encode('utf-8'), source_resolver=resolver)


@pytest.mark.parametrize('position,original_status', [(0, 'checked'), (1, 'blocked'),
    (2, 'blocked'), (3, 'blocked'), (4, 'blocked'), (5, 'blocked')])
def test_original_real_case_and_corrected_report(position, original_status):
    original = audit(reviewed(FIXTURE['before_claims'][position]), FIXTURE['before_report'])
    assert original['claims'][0]['status'] == original_status
    corrected = audit(reviewed(FIXTURE['after_claims'][position]))
    assert corrected['selected_claims_checked'] is True
    assert corrected['claims'][0]['report_line'] > 0


@pytest.mark.parametrize('position,dimension,value', [
    (0, 'conditions', {'threshold': '>0.20', 'endpoint': 'both purchased observations'}),
    (3, 'result', {'analytical': '0.160570499', 'repaired_estimate': '0.159568934'}),
    (3, 'evidence_level', 'independent_biological_confirmation'),
    (4, 'execution_status', 'not_executed'),
    (5, 'execution_status', 'executed_negative'),
    (4, 'limitations', []),
])
def test_same_numbers_do_not_excuse_changed_conditions_grade_or_failure_class(position, dimension, value):
    claim = copy.deepcopy(FIXTURE['after_claims'][position])
    claim['observed'][dimension] = value
    result = audit(reviewed(claim))
    assert result['selected_claims_checked'] is False
    assert f'fact_mismatch:{dimension}' in result['claims'][0]['violations']


def test_unverified_or_protected_sources_and_pending_reviews_cannot_pass():
    claim = reviewed(FIXTURE['after_claims'][0])
    assert audit(claim, resolver=None)['claims'][0]['status'] == 'needs_review'
    claim['sources'][0]['id'] = 'sealed/outcomes.json'
    calls = []
    def guarded(sid):
        assert not sid.startswith('sealed/')
        calls.append(sid)
        return resolve(sid)
    assert audit(reviewed(claim), resolver=guarded)['selected_claims_checked'] is False
    pending = copy.deepcopy(FIXTURE['after_claims'][0])
    assert audit(pending)['claims'][0]['status'] == 'needs_review'


def test_source_change_or_stale_review_blocks_reuse():
    claim = reviewed(FIXTURE['after_claims'][0])
    changed = audit(claim, resolver=lambda sid: resolve(sid) + b'\n')
    assert any('source_digest_changed' in v for v in changed['claims'][0]['violations'])
    claim['expected']['conditions'] = claim['observed']['conditions'] = {'threshold': '>0.20'}
    assert 'review_binding_changed' in audit(claim)['claims'][0]['pending']


def test_source_json_pointer_binds_threshold_to_value_not_just_occurrence():
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    source = claim['sources'][0]
    # The number still occurs in the source, but this endpoint is not that number.
    source['json_values'] = {'/summary/direct/0.1/repeat_positive': 1409}
    result = audit(reviewed(claim))
    assert result['selected_claims_checked'] is False
    assert any('source_json_' in v for v in result['claims'][0]['violations'])


def test_report_binding_detects_missing_condition_without_invalidating_unrelated_edits():
    claim = reviewed(FIXTURE['after_claims'][0])
    changed = FIXTURE['after_report'].replace('At the lower sensitivity threshold of >0,', 'For the comparison,')
    assert 'report_quote_missing_or_ambiguous' in audit(claim, changed)['claims'][0]['violations']
    unrelated = '# Unrelated maintenance note\n\n' + FIXTURE['after_report']
    result = audit(claim, unrelated)
    assert result['selected_claims_checked'] is True
    assert result['report_sha256'] != audit(claim)['report_sha256']


@pytest.mark.parametrize('sid', [r'records\.ENV', r'records\.git\config',
    'archive/passwd.txt', r'records\.ssh. \config', 'records/.env.production',
    'records/authorized_keys', r'records\node_modules\index.js',
    '.npmrc', '.pypirc', 'records/.NPMRC', r'records\.PYPIRC. ',
    'records/.hg/store', 'records/.svn/entries', 'records/.pytest_cache/state'])
def test_protected_spelling_aliases_never_reach_resolver(sid):
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['disposition'] = 'preserved'
    claim['sources'] = [{'id': sid, 'sha256': tool.digest(b'{}'), 'quote': '{}'}]
    calls = []
    def resolver(source_id):
        calls.append(source_id)
        return b'{}'
    result = audit(reviewed(claim), resolver=resolver)
    assert result['claims'][0]['status'] == 'needs_review'
    assert result['claims'][0]['pending'] == [f'protected_source:{sid}']
    assert calls == []
    assert result['metrics']['resolver_calls'] == 0


@pytest.mark.parametrize('left,right', [({'count': 1}, {'count': True}),
    ({'nested': [False]}, {'nested': [0]}), ({'value': {}}, {'value': []})])
def test_fact_tuple_json_types_are_binding(left, right):
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['expected']['result'], claim['observed']['result'] = left, right
    result = audit(reviewed(claim))
    assert 'fact_mismatch:result' in result['claims'][0]['violations']


@pytest.mark.parametrize('value,expected,passes', [(True, 1, False),
    (False, 0, False), ({'nested': [True]}, {'nested': [1]}, False),
    ({}, [], False), (1, 1.0, True)])
def test_source_json_pointer_enforces_json_types(value, expected, passes):
    payload = json.dumps({'value': value}).encode('utf-8')
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['disposition'] = 'preserved'
    claim['sources'] = [{'id': 'records/result.json', 'sha256': tool.digest(payload),
                         'quote': '"value"', 'json_values': {'/value': expected}}]
    result = audit(reviewed(claim), resolver=lambda sid: payload)
    assert result['selected_claims_checked'] is passes
    if not passes:
        assert 'source_json_value_changed:records/result.json' in result['claims'][0]['violations']


def test_fact_tuple_json_numbers_allow_equivalent_numeric_values():
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['expected']['result'] = {'count': 1}
    claim['observed']['result'] = {'count': 1.0}
    assert audit(reviewed(claim))['selected_claims_checked'] is True


@pytest.mark.parametrize('dimension', ['result', 'conditions', 'protocol'])
@pytest.mark.parametrize('value', [[], {}, ' \t\n'])
def test_substantive_dimensions_reject_empty_values(dimension, value):
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['expected'][dimension] = claim['observed'][dimension] = value
    result = audit(reviewed(claim))
    for side in ('expected', 'observed'):
        assert f'{side}:missing_{dimension}' in result['claims'][0]['violations']


def test_explicit_empty_limitations_list_is_valid():
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['expected']['limitations'] = claim['observed']['limitations'] = []
    assert audit(reviewed(claim))['selected_claims_checked'] is True


def test_resolver_exception_preserves_metrics_and_safe_failure_type():
    payload = b'{"result": 1}'
    claim = copy.deepcopy(FIXTURE['after_claims'][0])
    claim['sources'] = [{'id': sid, 'sha256': tool.digest(payload), 'quote': '"result"'}
                        for sid in ('records/result.json', 'records/failing.json', 'records/failing.json')]
    calls = []
    def resolver(sid):
        calls.append(sid)
        if sid.endswith('failing.json'):
            raise RuntimeError('sensitive resolver message')
        return payload
    result = audit(reviewed(claim), resolver=resolver)
    assert result['selected_claims_checked'] is False
    assert result['metrics'] == {'resolver_calls': 2, 'resolver_failures': 1,
                                 'source_bytes_returned': len(payload)}
    assert result['source_errors'] == [{'source_id': 'records/failing.json', 'error_type': 'RuntimeError'}]
    assert calls == ['records/result.json', 'records/failing.json']
    assert 'sensitive resolver message' not in json.dumps(result)
    assert 'source_unreadable:records/failing.json' in result['claims'][0]['violations']


def test_resolver_cancellation_is_not_swallowed():
    claim = reviewed(FIXTURE['after_claims'][0])
    def resolver(sid):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        audit(claim, resolver=resolver)
