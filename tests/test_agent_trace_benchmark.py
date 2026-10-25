"""Runtime logs must yield honest aggregate costs without exposing their text."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('bench_trace', SCRIPTS / 'benchmark_organization.py')
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def record(kind, payload, second=0):
    return {'type': kind, 'timestamp': f'2026-10-25T00:00:{second:02d}Z', 'payload': payload}


def test_overlapping_runtime_and_replayed_tokens_are_not_double_counted(tmp_path):
    rows = [record('event_msg', {'type': 'task_started', 'turn_id': 'one'})]
    epoch_ms = 1792886400000
    for name, start, end in [('Reasoning', 1, 4), ('CommandExecution', 2, 6)]:
        rows.append(record('event_msg', {'type': 'item_completed',
            'item': {'id': name, 'type': name, 'command': 'PRIVATE_TEXT', 'raw_content': 'PRIVATE_TEXT'},
            'started_at_ms': epoch_ms + 1000 * start, 'completed_at_ms': epoch_ms + 1000 * end}, end))
    usage = record('token_usage_record', {'response_id': 'r1', 'turn_id': 'one',
        'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 10,
                  'reasoning_output_tokens': 4, 'total_tokens': 110}}, 7)
    rows += [usage, usage, record('event_msg', {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 9999}}}, 8),
             record('event_msg', {'type': 'task_complete', 'turn_id': 'one'}, 10)]
    path = tmp_path / 'trace.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    result = bench.benchmark_trace(path)
    turn = result['turns'][0]
    assert turn['elapsed_seconds'] == 10
    assert turn['runtime_union_seconds'] == 5
    assert turn['unattributed_seconds'] == 5
    assert turn['runtime_items']['Reasoning']['wall_union_seconds'] == 3
    assert turn['runtime_items']['CommandExecution']['wall_union_seconds'] == 4
    assert turn['responses_with_usage'] == 1 and turn['token_usage']['input_tokens'] == 100
    assert 'PRIVATE_TEXT' not in json.dumps(result)


def test_active_trace_and_missing_usage_are_explicit(tmp_path):
    rows = [record('event_msg', {'type': 'task_started', 'turn_id': 'one'}),
            record('event_msg', {'type': 'item_completed', 'item': {'id': 'x', 'type': 'Reasoning'},
                                 'started_at_ms': None, 'completed_at_ms': None}, 3)]
    path = tmp_path / 'trace.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows) + '{"partial":', encoding='utf-8')
    result = bench.benchmark_trace(path, 'one')
    assert result['turns'][0]['complete'] is False
    assert result['turns'][0]['elapsed_seconds'] == 3
    assert result['turns'][0]['token_usage'] is None
    assert result['incomplete_trailing_records'] == 1
    with pytest.raises(ValueError, match='absent'):
        bench.benchmark_trace(path, 'absent')
    path.write_text('{bad}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Malformed complete'):
        bench.benchmark_trace(path)


def test_crossing_interval_is_clipped_and_unfinished_turn_stops_at_next_turn(tmp_path):
    epoch_ms = 1792886400000
    rows = [record('event_msg', {'type': 'task_started', 'turn_id': 'one'}),
        record('event_msg', {'type': 'task_started', 'turn_id': 'two'}, 10),
        record('event_msg', {'type': 'item_completed', 'item': {'id': 'command', 'type': 'CommandExecution'},
                            'started_at_ms': epoch_ms + 5000, 'completed_at_ms': epoch_ms + 15000}, 15),
        record('event_msg', {'type': 'task_complete', 'turn_id': 'two'}, 20)]
    path = tmp_path / 'trace.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    one, two = bench.benchmark_trace(path)['turns']
    assert one['complete'] is False and one['elapsed_seconds'] == 10
    assert one['runtime_union_seconds'] == two['runtime_union_seconds'] == 5
    assert two['elapsed_seconds'] == 10


@pytest.mark.parametrize('usage,valid', [
    (None, False),
    ({'input_tokens': True, 'output_tokens': 2}, False),
    ({'input_tokens': -1, 'output_tokens': 2}, False),
    ({'input_tokens': 10, 'output_tokens': 2, 'unexpected_debug': 'PRIVATE_SYNTHETIC_TEXT'}, True),
])
def test_usage_fields_are_numeric_whitelisted_and_missing_is_not_zero(tmp_path, usage, valid):
    rows = [record('event_msg', {'type': 'task_started', 'turn_id': 'one'}),
        record('token_usage_record', {'response_id': 'r1', 'turn_id': 'one', 'usage': usage}, 1),
        record('event_msg', {'type': 'task_complete', 'turn_id': 'one'}, 2)]
    path = tmp_path / 'trace.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    result = bench.benchmark_trace(path)
    turn = result['turns'][0]
    assert turn['responses_with_usage'] == int(valid)
    assert turn['responses_missing_usage'] == int(not valid)
    assert (turn['token_usage'] is not None) == valid
    assert 'PRIVATE_SYNTHETIC_TEXT' not in json.dumps(result)
