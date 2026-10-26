import importlib.util
import json
from pathlib import Path
from threading import Event

import pytest


SPEC = importlib.util.spec_from_file_location('agent_runner', Path(__file__).parents[1] / 'scripts/run_agent_benchmark.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    oracle = tmp_path / 'oracle'
    for name in ('cases/example/initial', 'public', 'private'):
        (oracle / name).mkdir(parents=True)
    (oracle / 'cases/example/initial/source.md').write_text('Original source.\n', encoding='utf-8')
    for name in ('prompt_first.txt', 'evaluator_prompt.txt'):
        (oracle / 'public' / name).write_text('A scoped test request.', encoding='utf-8')
    (oracle / 'private/answer_rubric.json').write_text('{"example": {}}', encoding='utf-8')
    (oracle / 'private/EVALUATOR_GUIDE.md').write_text('Test review.', encoding='utf-8')
    variant = tmp_path / 'variants/candidate'
    variant.mkdir(parents=True)
    (variant / 'SKILL.md').write_text('Test skill.', encoding='utf-8')
    for key, value in {'ROOT': tmp_path, 'ORACLE': oracle, 'VARIANT_ROOT': variant.parent,
                       'MODEL': 'test-model', 'CODEX': 'mock-codex',
                       'VARIANTS': {'candidate': ['candidate', 'fixed']}, 'RESOURCE_STOP': Event()}.items():
        monkeypatch.setattr(runner, key, value)
    return {'run_id': 'one', 'pair_id': 'first-1', 'stage': 'first', 'case': 'example', 'arm': 'candidate'}


def fake_process(monkeypatch, *, limit_role=None, limit_message='You have hit your usage limit.'):
    calls = []

    class Process:
        def __init__(self, command, **kwargs):
            self.command, self.output = command, kwargs['stdout']
            self.role = 'evaluation' if 'review-' in Path(self.output.name).name else 'worker'
            self.returncode = 1 if self.role == limit_role else 0
            calls.append(self.role)

        def communicate(self, prompt, timeout):
            if self.role == limit_role:
                event = {'type': 'error', 'message': limit_message}
                self.output.write(json.dumps(event) + '\n')
            else:
                self.output.write(json.dumps({'type': 'thread.started', 'thread_id': 'test-session'}) + '\n')
                self.output.write(json.dumps({'type': 'turn.completed', 'usage': {
                    'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 1}}) + '\n')
                if self.role == 'evaluation':
                    passed = calls.count('evaluation') > 1
                    verdict = {'passed': passed, 'missing_facts': [] if passed else ['condition'],
                               'incorrect_claims': [], 'feedback': 'Check condition.', 'limitations': []}
                    Path(self.command[self.command.index('-o') + 1]).write_text(json.dumps(verdict), encoding='utf-8')

    monkeypatch.setattr(runner.subprocess, 'Popen', Process)
    return calls


def test_actual_error_event_detects_explicit_usage_limit():
    assert runner.resource_limited([{'type': 'turn.failed', 'error': {'message': 'usage_limit_exceeded'}}])


@pytest.mark.parametrize('event', [
    {'type': 'error', 'message': 'Your workspace is out of credits. Add credits to continue.'},
    {'type': 'turn.failed', 'error': {'message': 'Your workspace is out of credits. Add credits to continue.'}},
])
def test_workspace_credit_exhaustion_stops_calls(event):
    assert runner.resource_limited([event])


def test_source_mentions_and_transient_errors_do_not_stop_the_suite():
    assert not runner.resource_limited([
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'usage limit'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Your workspace is out of credits.'}},
        {'type': 'error', 'message': 'Temporary connection error'},
    ])


@pytest.mark.parametrize('limit_message', [
    'You have hit your usage limit.',
    'Your workspace is out of credits. Add credits to continue.',
])
def test_worker_limit_preserves_failure_without_review_repair_or_new_trial(prepared, monkeypatch, limit_message):
    calls = fake_process(monkeypatch, limit_role='worker', limit_message=limit_message)
    runner.run_trial(prepared)
    record = json.loads((runner.ROOT / 'trials/one/result.json').read_text())
    assert calls == ['worker']
    assert record['execution_status'] == 'resource_limited' and record['passed'] is False
    assert len(record['attempts']) == 1
    assert record['attempts'][0]['worker']['usage'] is None
    assert record['attempts'][0]['evaluation']['not_called'] is True
    assert (runner.ROOT / 'trials/one/project/source.md').read_text() == 'Original source.\n'
    runner.run_trial({**prepared, 'run_id': 'two'})
    assert not (runner.ROOT / 'trials/two').exists()


def test_evaluator_limit_preserves_both_call_costs_and_stops_repairs(prepared, monkeypatch):
    calls = fake_process(monkeypatch, limit_role='evaluation')
    runner.run_trial(prepared)
    record = json.loads((runner.ROOT / 'trials/one/result.json').read_text())
    assert calls == ['worker', 'evaluation']
    assert record['passed'] is False and record['execution_status'] == 'resource_limited'
    assert record['attempts'][0]['worker']['usage']['input_tokens'] == 10
    assert record['attempts'][0]['evaluation']['usage'] is None


def test_semantic_failure_still_gets_one_repair_when_resources_are_available(prepared, monkeypatch):
    calls = fake_process(monkeypatch)
    runner.run_trial(prepared)
    record = json.loads((runner.ROOT / 'trials/one/result.json').read_text())
    assert calls == ['worker', 'evaluation', 'worker', 'evaluation']
    assert record['passed'] is True and len(record['attempts']) == 2
    assert not runner.RESOURCE_STOP.is_set()
