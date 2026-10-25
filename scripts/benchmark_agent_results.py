"""Summarize explicit local Agent trials, including review, repair and failures.

Inputs are result.json files from an external paired trial suite. No model is
called and no project payload or transcript text is exported. Review declarations
are measurements supplied by the evaluator, not an automatic semantic proof.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def total_usage(calls):
    return {field: (sum(call['usage'][field] for call in calls)
                    if all(isinstance(call.get('usage'), dict)
                           and type(call['usage'].get(field)) is int
                           and call['usage'][field] >= 0 for call in calls) else None)
            for field in TOKEN_FIELDS}


def distribution(values):
    known = [value for value in values if value is not None]
    return {'observed': len(known), 'missing': len(values) - len(known),
            'median': statistics.median(known) if known else None,
            'min': min(known) if known else None, 'max': max(known) if known else None}


def summarize(records):
    runs, pairs, groups, seen = [], defaultdict(dict), defaultdict(list), set()
    for record in records:
        if record['run_id'] in seen:
            raise ValueError('Duplicate run id')
        seen.add(record['run_id'])
        if not isinstance(record.get('finished_utc'), str) or not record['finished_utc'].strip():
            raise ValueError('Incomplete trial must not be silently counted as complete')
        attempts = record['attempts']
        if not attempts:
            raise ValueError('A completed trial needs at least one attempt')
        workers = [attempt['worker'] for attempt in attempts]
        reviewers = [attempt['evaluation'] for attempt in attempts]
        calls = workers + reviewers
        for seconds in [record['end_to_end_seconds']] + [call['seconds'] for call in calls]:
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError('Elapsed times must be finite nonnegative numbers')
        if record['end_to_end_seconds'] + 0.001 < sum(call['seconds'] for call in calls):
            raise ValueError('End-to-end duration omits serial worker or review costs')
        for attempt in attempts:
            verdict = attempt['verdict']
            if any(not isinstance(verdict.get(field), list) for field in ('missing_facts', 'incorrect_claims')):
                raise ValueError('Missing quality measurements are not empty defect lists')
            if not attempt['gates'] or any(type(value) is not bool for value in attempt['gates'].values()):
                raise ValueError('Operational gates must be explicit boolean measurements')
            valid_pass = (attempt['worker']['returncode'] == 0 and attempt['evaluation']['returncode'] == 0
                          and verdict.get('passed') is True and not verdict.get('missing_facts')
                          and not verdict.get('incorrect_claims') and bool(attempt['gates'])
                          and all(value is True for value in attempt['gates'].values()))
            if type(attempt['passed']) is not bool or attempt['passed'] != valid_pass:
                raise ValueError('Attempt pass flag disagrees with its quality/execution gates')
        if type(record['passed']) is not bool or record['passed'] != attempts[-1]['passed']:
            raise ValueError('Final pass flag disagrees with the last attempt')
        row = {key: record[key] for key in ('run_id', 'pair_id', 'stage', 'case', 'arm',
                                            'skill_commit', 'input_sha256', 'model', 'reasoning', 'passed')}
        row.update(attempts=len(attempts), first_pass=attempts[0]['passed'],
                   content_review_passed=(attempts[-1]['evaluation']['returncode'] == 0
                       and attempts[-1]['verdict']['passed'] is True
                       and not attempts[-1]['verdict']['missing_facts']
                       and not attempts[-1]['verdict']['incorrect_claims']),
                   operational_gates_passed=all(attempts[-1]['gates'].values()),
                   end_to_end_seconds=record['end_to_end_seconds'],
                   worker_seconds=sum(call['seconds'] for call in workers),
                   review_seconds=sum(call['seconds'] for call in reviewers),
                   repair_seconds=sum(a['worker']['seconds'] + a['evaluation']['seconds'] for a in attempts[1:]),
                   tokens=total_usage(calls), worker_tokens=total_usage(workers), review_tokens=total_usage(reviewers),
                   worker_tool_calls=sum(call['tool_calls'] for call in workers))
        if row['arm'] not in ('baseline', 'candidate') or row['arm'] in pairs[row['pair_id']]:
            raise ValueError('Each pair needs distinct baseline and candidate arms')
        pairs[row['pair_id']][row['arm']] = row
        groups[(row['stage'], row['arm'])].append(row)
        runs.append(row)
    for arm in ('baseline', 'candidate'):
        if len({row['skill_commit'] for row in runs if row['arm'] == arm}) > 1:
            raise ValueError('A comparator arm must use one frozen skill revision')
    comparisons = []
    for pair_id, arms in sorted(pairs.items()):
        if set(arms) != {'baseline', 'candidate'}:
            raise ValueError(f'Incomplete pair: {pair_id}')
        before, after = arms['baseline'], arms['candidate']
        for field in ('input_sha256', 'case', 'stage', 'model', 'reasoning'):
            if before[field] != after[field]:
                raise ValueError(f'Unmatched paired {field}: {pair_id}')
        eligible = before['passed'] and after['passed']
        comparisons.append({'pair_id': pair_id, 'stage': before['stage'], 'eligible': eligible,
                            'reason': None if eligible else 'quality_gate_failed',
                            'seconds_difference': after['end_to_end_seconds'] - before['end_to_end_seconds'] if eligible else None,
                            'input_tokens_difference': (after['tokens']['input_tokens'] - before['tokens']['input_tokens']
                                if eligible and all(r['tokens']['input_tokens'] is not None for r in (before, after)) else None)})
    summaries = []
    for (stage, arm), rows in sorted(groups.items()):
        summaries.append({'stage': stage, 'arm': arm, 'runs': len(rows),
                          'first_pass': sum(row['first_pass'] for row in rows),
                          'final_pass': sum(row['passed'] for row in rows),
                          'content_review_pass': sum(row['content_review_passed'] for row in rows),
                          'operational_gates_pass': sum(row['operational_gates_passed'] for row in rows),
                          'end_to_end_seconds_all_runs': distribution([row['end_to_end_seconds'] for row in rows]),
                          'worker_seconds_all_runs': distribution([row['worker_seconds'] for row in rows]),
                          'repair_seconds_all_runs': distribution([row['repair_seconds'] for row in rows]),
                          'input_tokens_all_runs': distribution([row['tokens']['input_tokens'] for row in rows])})
    return {'schema_version': 1, 'runs': runs, 'groups': summaries, 'pairs': comparisons,
            'scope': 'All completed trials and all attempts retained. Wall time includes organizer, independent '
                     'review and repairs. Token totals include cached input and evaluator usage; missing usage '
                     'stays null. Pair differences only for identical inputs/settings with both quality gates '
                     'passed. Semantic verdicts require independent audit; no general speedup is inferred.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite-root', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads((path / 'result.json').read_text(encoding='utf-8'))
               for path in sorted((args.suite_root / 'trials').iterdir()) if path.is_dir()]
    if not records:
        parser.error('No completed trial results found')
    schedule = json.loads((args.suite_root / 'schedule.json').read_text(encoding='utf-8'))
    if {row['run_id'] for row in records} != {row['run_id'] for row in schedule}:
        parser.error('Result set does not cover the complete planned schedule')
    print(json.dumps(summarize(records), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
