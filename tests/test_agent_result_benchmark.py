import copy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('agent_results', Path(__file__).parents[1] / 'scripts/benchmark_agent_results.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def trial(arm='baseline', repair=False, passed=True):
    call = {'seconds': 10, 'returncode': 0, 'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 5}, 'tool_calls': 2}
    def attempt(ok):
        return {'worker': copy.deepcopy(call), 'evaluation': copy.deepcopy(call),
                'verdict': {'passed': ok, 'missing_facts': [] if ok else ['condition omitted'], 'incorrect_claims': []},
                'gates': {'preserved': True}, 'passed': ok}
    return {'run_id': arm, 'pair_id': 'first-1', 'stage': 'first', 'case': 'synthetic', 'arm': arm,
            'skill_commit': arm, 'input_sha256': 'same', 'model': 'fixed', 'reasoning': 'fixed',
            'finished_utc': 'recorded', 'end_to_end_seconds': 40 if repair else 20,
            'attempts': [attempt(False), attempt(passed)] if repair else [attempt(passed)], 'passed': passed}


def test_repairs_and_independent_reviews_are_included_in_cost():
    result = tool.summarize([trial(), trial('candidate', repair=True)])
    row = result['runs'][1]
    assert row['tokens']['input_tokens'] == 400 and row['worker_tokens']['input_tokens'] == 200
    assert row['repair_seconds'] == 20 and row['first_pass'] is False
    assert result['pairs'][0]['seconds_difference'] == 20


def test_failed_trials_stay_in_denominator_but_cannot_claim_speedup():
    result = tool.summarize([trial(), trial('candidate', passed=False)])
    assert result['groups'][1]['runs'] == 1 and result['groups'][1]['final_pass'] == 0
    assert result['pairs'][0]['eligible'] is False
    assert result['pairs'][0]['seconds_difference'] is None


def test_partial_usage_is_unknown_not_zero():
    record = trial(repair=True)
    record['attempts'][0]['evaluation']['usage'] = None
    row = tool.summarize([record, trial('candidate')])['runs'][0]
    assert row['tokens']['input_tokens'] is None
    assert row['worker_tokens']['input_tokens'] == 200


@pytest.mark.parametrize('field', ['input_sha256', 'model', 'reasoning', 'case', 'stage'])
def test_incomparable_pairs_are_rejected(field):
    candidate = trial('candidate')
    candidate[field] = 'different'
    with pytest.raises(ValueError, match='Unmatched'):
        tool.summarize([trial(), candidate])


def test_stale_or_forged_pass_and_incomplete_trials_are_rejected():
    record = trial()
    record['attempts'][0]['gates']['preserved'] = False
    with pytest.raises(ValueError, match='gate'):
        tool.summarize([record])
    record = trial()
    del record['finished_utc']
    with pytest.raises(ValueError, match='Incomplete'):
        tool.summarize([record])


def test_missing_arm_cannot_be_omitted_from_comparison():
    with pytest.raises(ValueError, match='Incomplete pair'):
        tool.summarize([trial()])


def test_end_to_end_duration_cannot_omit_review_or_repair_costs():
    candidate = trial('candidate', repair=True)
    candidate['end_to_end_seconds'] = 0
    with pytest.raises(ValueError, match='omits'):
        tool.summarize([trial(), candidate])


def test_missing_verdict_lists_are_not_evidence_of_zero_defects():
    candidate = trial('candidate')
    candidate['attempts'][0]['verdict'] = {'passed': True}
    with pytest.raises(ValueError, match='quality measurements'):
        tool.summarize([trial(), candidate])


def test_empty_completion_marker_is_rejected():
    candidate = trial('candidate')
    candidate['finished_utc'] = None
    with pytest.raises(ValueError, match='Incomplete'):
        tool.summarize([trial(), candidate])


def test_correct_report_with_unnecessary_write_is_not_a_scientific_omission():
    candidate = trial('candidate')
    candidate['attempts'][0]['gates']['no_write'] = False
    candidate['attempts'][0]['passed'] = candidate['passed'] = False
    row = tool.summarize([trial(), candidate])['runs'][1]
    assert row['content_review_passed'] is True
    assert row['operational_gates_passed'] is False and row['passed'] is False


def test_mixing_revisions_within_an_arm_is_rejected():
    other = trial()
    other.update(run_id='other', pair_id='first-2', skill_commit='changed')
    with pytest.raises(ValueError, match='frozen'):
        tool.summarize([trial(), trial('candidate'), other])


@pytest.mark.parametrize('fault', ['defect', 'review_failure'])
def test_contradictory_verdict_is_not_counted_as_content_success(fault):
    candidate = trial('candidate', passed=False)
    candidate['attempts'][0]['verdict']['passed'] = True
    if fault == 'review_failure':
        candidate['attempts'][0]['verdict']['missing_facts'] = []
        candidate['attempts'][0]['evaluation']['returncode'] = 1
    row = tool.summarize([trial(), candidate])['runs'][1]
    assert row['content_review_passed'] is False


def test_truthy_text_is_not_a_measured_operational_gate():
    candidate = trial('candidate', passed=False)
    candidate['attempts'][0]['gates']['preserved'] = 'unknown'
    with pytest.raises(ValueError, match='boolean'):
        tool.summarize([trial(), candidate])


def test_interrupted_duration_bound_is_retained_but_not_reported_as_exact_time():
    candidate = trial('candidate', passed=False)
    candidate['duration_complete'] = False
    candidate['attempts'][0]['worker']['usage'] = None
    result = tool.summarize([trial(), candidate])
    row = result['runs'][1]
    assert row['end_to_end_seconds'] is None
    assert row['duration_lower_bounds']['end_to_end_seconds'] == 20
    assert row['tokens']['input_tokens'] is None
    assert result['groups'][1]['runs'] == 1
    assert result['groups'][1]['end_to_end_seconds_all_runs']['missing'] == 1
    assert result['pairs'][0]['seconds_difference'] is None


def test_later_success_cannot_make_incomplete_cost_eligible_for_speed_comparison():
    candidate = trial('candidate', repair=True)
    candidate['duration_complete'] = False
    result = tool.summarize([trial(), candidate])
    assert result['runs'][1]['passed'] is True
    assert result['pairs'][0]['reason'] == 'duration_incomplete'
    assert result['pairs'][0]['seconds_difference'] is None


def test_truthy_duration_measurement_is_rejected():
    candidate = trial('candidate')
    candidate['duration_complete'] = 'unknown'
    with pytest.raises(ValueError, match='Duration completeness'):
        tool.summarize([trial(), candidate])


def test_no_evaluator_call_has_zero_known_cost_but_missing_worker_usage_stays_unknown():
    candidate = trial('candidate', passed=False)
    candidate['attempts'][0]['worker']['usage'] = None
    review = candidate['attempts'][0]['evaluation']
    review.update(not_called=True, usage=None, returncode=-1, seconds=0, tool_calls=0)
    row = tool.summarize([trial(), candidate])['runs'][1]
    assert row['tokens']['input_tokens'] is None
    assert row['review_tokens']['input_tokens'] == 0


def test_not_called_flag_cannot_erase_recorded_call_costs():
    candidate = trial('candidate')
    candidate['attempts'][0]['evaluation']['not_called'] = True
    with pytest.raises(ValueError, match='cannot hide'):
        tool.summarize([trial(), candidate])
