"""Measure strict hashing/metadata scans or synthetic dry-run plans.

Index mode reads only explicitly indexed sources. Operations mode creates an external
temporary fixture and optionally imports an explicitly supplied local baseline.
Timings depend on run order and OS caches; index-mode counters cover source payload
I/O, not index loading. Metadata screening does not authorize cleanup.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time

import evidence_index
import organization_ops


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
    parser.add_argument('--root', type=Path)
    parser.add_argument('--baseline-ops', type=Path)
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args(argv)
    if args.index is not None and (args.root is None or args.baseline_ops is not None):
        parser.error('--index requires --root and cannot use --baseline-ops')
    if args.operations is not None and args.root is not None:
        parser.error('--operations cannot use --root; it always creates an external synthetic workspace')
    try:
        if args.operations is not None:
            result = benchmark_operations(args.operations, args.repeats, args.baseline_ops)
        else:
            index = json.loads(args.index.read_text(encoding='utf-8'))
            result = benchmark(index, args.root, args.repeats)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(run.get('errors') for run in result['runs']))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'benchmark_organization: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
