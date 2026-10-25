"""Measure strict scans, synthetic plans or aggregate explicit local Agent traces.

Index mode reads only explicitly indexed sources. Operations mode creates an external
temporary fixture and optionally imports an explicitly supplied local baseline.
Timings depend on run order and OS caches; index-mode counters cover source payload
I/O, not index loading. Metadata screening does not authorize cleanup.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time

import evidence_index
import organization_ops


def _union_seconds(intervals):
    end, total = float('-inf'), 0.0
    for start, stop in sorted(intervals):
        total += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return total


def benchmark_trace(path, turn_id=None):
    """Aggregate an explicitly supplied local Codex trace without exporting text.

    Runtime item intervals may overlap. Their per-type unions are not additive.
    Usage records are per-response, unlike repeated token_count cumulative events.
    Subagent traces and semantic reading/synthesis attribution are not inferred.
    """
    turns, items, usage = {}, {}, {}
    last_time, incomplete_lines = 0.0, 0
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # An active JSONL file may end with an incomplete write; do not
                # silently accept corruption in an earlier complete line.
                if line.endswith('\n'):
                    raise ValueError('Malformed complete trace record') from None
                incomplete_lines += 1
                continue
            timestamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
            last_time = max(last_time, timestamp)
            payload = row.get('payload', {})
            kind = payload.get('type')
            if row['type'] == 'event_msg' and kind == 'task_started':
                turns[payload['turn_id']] = {'start': timestamp, 'end': None}
            elif row['type'] == 'event_msg' and kind == 'task_complete':
                if payload['turn_id'] in turns:
                    turns[payload['turn_id']]['end'] = timestamp
            elif row['type'] == 'event_msg' and kind == 'item_completed':
                item = payload['item']
                if isinstance(payload.get('started_at_ms'), (int, float)) and isinstance(payload.get('completed_at_ms'), (int, float)):
                    items[item['id']] = {'type': item['type'],
                        'start': payload['started_at_ms'] / 1000,
                        'end': payload['completed_at_ms'] / 1000}
            elif row['type'] == 'token_usage_record':
                # Deduplicate replayed response records; never sum token_count.
                usage[payload['response_id']] = (timestamp, payload.get('turn_id'), payload['usage'])
    if turn_id is not None and turn_id not in turns:
        raise ValueError('Requested turn is absent from trace')
    results = []
    ordered = list(turns.items())
    token_fields = {'input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                    'output_tokens', 'reasoning_output_tokens', 'total_tokens'}
    for number, (tid, turn) in enumerate(ordered, 1):
        if turn_id is not None and tid != turn_id:
            continue
        next_start = ordered[number][1]['start'] if number < len(ordered) else last_time
        start, end = turn['start'], turn['end'] or min(next_start, last_time)
        selected = [item for item in items.values() if item['start'] < end and item['end'] >= start]
        by_type = {}
        for kind in sorted({item['type'] for item in selected}):
            intervals = [(max(start, item['start']), min(end, item['end']))
                         for item in selected if item['type'] == kind and item['end'] >= item['start']]
            by_type[kind] = {'items': sum(item['type'] == kind for item in selected),
                            'wall_union_seconds': _union_seconds(intervals)}
        tokens, responses, missing_usage = Counter(), 0, 0
        for stamp, record_tid, values in usage.values():
            if record_tid == tid:
                if (not isinstance(values, dict) or not {'input_tokens', 'output_tokens'} <= values.keys()
                        or any(type(values[key]) is not int or values[key] < 0 for key in token_fields & values.keys())):
                    missing_usage += 1
                    continue
                responses += 1
                tokens.update({key: values[key] for key in token_fields & values.keys()})
        measured = _union_seconds([(max(start, item['start']), min(end, item['end']))
                                   for item in selected if item['end'] >= item['start']])
        results.append({'turn_number': number, 'complete': turn['end'] is not None,
            'elapsed_seconds': end - start, 'runtime_items': by_type,
            'runtime_union_seconds': measured, 'unattributed_seconds': max(0.0, end - start - measured),
            'responses_with_usage': responses, 'responses_missing_usage': missing_usage,
            'token_usage': dict(tokens) if responses else None})
    return {'schema_version': 1, 'mode': 'agent_trace', 'turns': results,
        'incomplete_trailing_records': incomplete_lines,
        'scope': 'Only this explicitly supplied local trace. No prompts, commands, reasoning text or file payloads exported. '
                 'Runtime item intervals are observations, not CPU time or semantic reading/synthesis phases; per-type unions overlap. '
                 'Token usage sums deduplicated per-response records, includes cached input, and excludes separate subagent traces. '
                 'Reasoning tokens are a subset of output tokens. Missing usage is null, not zero. '
                 'Unattributed wall time may include scheduling, waits and unlogged activity. No same-input speedup is established.'}


def benchmark(index, root, repeats=1):
    if repeats < 1:
        raise ValueError('repeats must be positive')
    runs = []
    for iteration in range(repeats):
        previous = None
        for mode in ('strict_initial', 'strict_repeat', 'metadata_scan'):
            started = time.perf_counter()
            result = (evidence_index.scan_index(index, root, previous)
                      if mode == 'metadata_scan' else evidence_index.snapshot_index(index, root))
            elapsed = time.perf_counter() - started
            runs.append({'iteration': iteration + 1, 'mode': mode, 'seconds': elapsed,
                         'verification_mode': result['verification_mode'],
                         'metrics': result['metrics'], 'errors': result['errors'],
                         'unverified_sources': result['unverified_sources'],
                         'candidate_sources': result.get('candidate_sources', []),
                         'needs_strict_verification': result.get('needs_strict_verification', [])})
            if mode != 'metadata_scan':
                previous = result
    return {'schema_version': 1, 'root': str(Path(root).absolute()), 'runs': runs,
            'scope': 'Selected indexed sources only. Fixed order; caches and filesystem affect timings. '
                     'Counters exclude index JSON reads and path-safety metadata calls. '
                     'Zero payload I/O in metadata_scan does not establish unchanged bytes, '
                     'scientific validity, safe deletion or a speed advantage for real Agent work.'}


def benchmark_operations(count, repeats=1, baseline=None):
    if count < 1 or repeats < 1:
        raise ValueError('operations and repeats must be positive')
    implementations = {'current': organization_ops}
    if baseline is not None:
        baseline = Path(baseline).resolve(strict=True)
        if baseline.suffix != '.py':
            raise ValueError('baseline-ops must be an explicitly supplied local Python file')
        spec = importlib.util.spec_from_file_location('_organization_benchmark_baseline', baseline)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, 'dry_run', None)):
            raise ValueError('baseline-ops must expose dry_run(plan)')
        implementations['baseline'] = module

    def workspace_state(root):
        result = {}
        for path in root.rglob('*'):
            if path.is_dir():
                result[path.relative_to(root).as_posix()] = {'type': 'directory'}
            else:
                info = path.stat()
                result[path.relative_to(root).as_posix()] = {
                    'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'mode': info.st_mode,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        return result

    runs = []
    with tempfile.TemporaryDirectory(prefix='organization-ops-benchmark-') as temporary:
        root = Path(temporary)
        operations = []
        for number in range(count):
            name = f'source_{number:08d}.bin'
            data = f'Synthetic benchmark source {number}\n'.encode('ascii')
            (root / name).write_bytes(data)
            operations.append({'op': 'move', 'source': name, 'target': f'organized/{name}',
                               'sha256': hashlib.sha256(data).hexdigest(), 'reason': 'Synthetic plan benchmark'})
        plan = {'schema': 1, 'root': str(root), 'operations': operations}
        expected_plan = json.loads(json.dumps(plan))
        expected_state = workspace_state(root)
        for iteration in range(repeats):
            for name, implementation in implementations.items():
                started = time.perf_counter()
                result = implementation.dry_run(plan)
                elapsed = time.perf_counter() - started
                if result != expected_plan['operations'] or plan != expected_plan:
                    raise ValueError(f'{name} dry-run changed the plan or returned different operations')
                if workspace_state(root) != expected_state:
                    raise ValueError(f'{name} dry-run changed the synthetic workspace')
                runs.append({'iteration': iteration + 1, 'implementation': name, 'seconds': elapsed,
                             'operations': count, 'plan_equal': True, 'workspace_unchanged': True})
    return {'schema_version': 1, 'mode': 'operations_dry_run', 'runs': runs,
            'implementations': {name: {'source': str(Path(module.__file__).resolve()),
                                      'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
                                for name, module in implementations.items()},
            'scope': 'Synthetic unique-file move plans in an external temporary directory only. '
                     'The harness downloads nothing; explicitly supplied local baseline code runs normally. '
                     'Fixture generation/digests and unchanged-workspace/plan checks are outside timing; '
                     'all hashing and path checks performed by dry_run itself are timed. '
                     'Fixed current-then-baseline order; OS caches and filesystem affect results. '
                     'No apply/rollback, real-project cleanup, scientific semantics or Agent costs are measured.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--index', type=Path)
    modes.add_argument('--operations', type=int)
    modes.add_argument('--trace', type=Path, help='Explicit local Codex JSONL; aggregate only, never publish raw logs')
    parser.add_argument('--turn-id', help='Select one trace turn; default reports each observed turn')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--baseline-ops', type=Path)
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args(argv)
    if args.trace is not None and (args.root is not None or args.baseline_ops is not None):
        parser.error('--trace cannot use --root or --baseline-ops')
    if args.turn_id is not None and args.trace is None:
        parser.error('--turn-id requires --trace')
    if args.index is not None and (args.root is None or args.baseline_ops is not None):
        parser.error('--index requires --root and cannot use --baseline-ops')
    if args.operations is not None and args.root is not None:
        parser.error('--operations cannot use --root; it always creates an external synthetic workspace')
    try:
        if args.trace is not None:
            result = benchmark_trace(args.trace, args.turn_id)
        elif args.operations is not None:
            result = benchmark_operations(args.operations, args.repeats, args.baseline_ops)
        else:
            index = json.loads(args.index.read_text(encoding='utf-8'))
            result = benchmark(index, args.root, args.repeats)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(run.get('errors') for run in result.get('runs', [])))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'benchmark_organization: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
