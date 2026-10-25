"""Check reviewed fact tuples against source and report bindings.

This is a bounded coverage check, not a semantic extractor or scientific verdict.
Callers supply independently extracted facts and an explicitly trusted bytes
resolver. Review declarations do not prove independence or completeness. No files
are changed and a passing selected claim never authorizes deletion by itself.
"""
from __future__ import annotations

import hashlib
import json
import re


DIMENSIONS = ('result', 'conditions', 'protocol', 'evidence_level', 'limitations', 'execution_status')
HASH = re.compile(r'[0-9a-f]{64}\Z')
PROTECTED = re.compile(r'sealed|blind|credential|secret|password|passwd|api[_-]?key|(?:^|[/_.-])token(?:[/_.-]|$)|(?:^|/)\.env|(?:^|/)(?:\.git|\.hg|\.svn|\.ssh|\.venv|venv|gpu_venv|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|\.npmrc|\.pypirc)(?:/|$)|(?:id_rsa|id_ed25519|authorized_keys)|\.(?:pem|key|p12|pfx|kdbx)$', re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def review_binding(claim):
    """Bind review to selected facts, source identities and the exact report quote.

    Unrelated report edits do not invalidate a quote-level review. The actual
    complete report digest is recorded separately by audit_claims.
    """
    body = {key: value for key, value in claim.items() if key != 'review'}
    return digest(json.dumps(body, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8'))


def text(data):
    return data.decode('utf-8-sig').replace('\r\n', '\n')


def json_equal(left, right):
    """Compare JSON values without Python's bool/number equality alias."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def json_pointer(document, pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')):
        raise ValueError('Expected a JSON pointer')
    for part in pointer.split('/')[1:] if pointer else []:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(document, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('Invalid JSON array index')
            document = document[int(part)]
        else:
            document = document[part]
    return document


def audit_claims(claims, report_bytes, *, source_resolver=None):
    """Validate bindings and reviewed tuples; return blocked facts explicitly.

    source_resolver(source_id) must return bytes. It is never imported from a
    project or selected by an untrusted module string. Its internal I/O is not
    measurable here; counters describe returned bytes and calls only.
    """
    if not isinstance(claims, list) or not claims:
        raise ValueError('At least one selected claim is required')
    report = text(report_bytes)
    checked, cache, seen, source_errors = [], {}, set(), []
    metrics = {'resolver_calls': 0, 'resolver_failures': 0, 'source_bytes_returned': 0}
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get('id'), str) or not claim['id'].strip():
            raise ValueError('Every claim needs a nonempty id')
        if claim['id'] in seen:
            raise ValueError('Duplicate claim id')
        seen.add(claim['id'])
        violations, pending = [], []
        for side in ('expected', 'observed'):
            fact = claim.get(side)
            if not isinstance(fact, dict):
                violations.append(f'{side}:missing_fact')
                continue
            for field in DIMENSIONS:
                value = fact.get(field)
                if (field not in fact or value is None
                        or isinstance(value, str) and not value.strip()
                        or isinstance(value, dict) and not value
                        or field in ('result', 'conditions', 'protocol') and isinstance(value, list) and not value):
                    violations.append(f'{side}:missing_{field}')
            if (not isinstance(fact.get('limitations'), list)
                    or any(not isinstance(value, str) or not value.strip() for value in fact['limitations'])):
                violations.append(f'{side}:limitations_must_be_explicit_list')
            if any(not isinstance(fact.get(field), str) or not fact[field].strip()
                   for field in ('evidence_level', 'execution_status')):
                violations.append(f'{side}:grade_and_execution_status_must_be_strings')
        if isinstance(claim.get('expected'), dict) and isinstance(claim.get('observed'), dict):
            for field in DIMENSIONS:
                if not json_equal(claim['expected'].get(field), claim['observed'].get(field)):
                    violations.append(f'fact_mismatch:{field}')
        quote = claim.get('report_quote')
        if not isinstance(quote, str) or not quote.strip() or report.count(quote.replace('\r\n', '\n')) != 1:
            violations.append('report_quote_missing_or_ambiguous')
        sources = claim.get('sources')
        if not isinstance(sources, list) or not sources:
            violations.append('missing_sources')
            sources = []
        for source in sources:
            if (not isinstance(source, dict) or not isinstance(source.get('id'), str)
                    or not source['id'].strip() or not isinstance(source.get('sha256'), str)
                    or not HASH.fullmatch(source['sha256']) or not isinstance(source.get('quote'), str)
                    or not source['quote'].strip()):
                violations.append('invalid_source_binding')
                continue
            sid = source['id']
            guarded_id = '/'.join(part.rstrip(' .') for part in sid.replace('\\', '/').split('/'))
            if PROTECTED.search(guarded_id):
                pending.append(f'protected_source:{sid}')
                continue
            if source_resolver is None:
                pending.append(f'unverified_source:{sid}')
                continue
            if sid not in cache:
                metrics['resolver_calls'] += 1
                try:
                    payload = source_resolver(sid)
                    if not isinstance(payload, bytes):
                        raise ValueError('Trusted resolver must return bytes')
                    metrics['source_bytes_returned'] += len(payload)
                    cache[sid] = (digest(payload), text(payload))
                except Exception as error:
                    metrics['resolver_failures'] += 1
                    source_errors.append({'source_id': sid, 'error_type': type(error).__name__})
                    cache[sid] = None
            binding = cache[sid]
            if binding is None:
                violations.append(f'source_unreadable:{sid}')
            elif binding[0] != source['sha256']:
                violations.append(f'source_digest_changed:{sid}')
            elif source['quote'].replace('\r\n', '\n') not in binding[1]:
                violations.append(f'source_quote_missing:{sid}')
            elif 'json_values' in source:
                try:
                    values = source['json_values']
                    if not isinstance(values, dict) or not values:
                        raise ValueError('json_values must be a nonempty pointer/value mapping')
                    document = json.loads(binding[1])
                    if any(not json_equal(json_pointer(document, pointer), expected) for pointer, expected in values.items()):
                        violations.append(f'source_json_value_changed:{sid}')
                except (ValueError, KeyError, IndexError, TypeError):
                    violations.append(f'source_json_binding_invalid:{sid}')
        disposition = claim.get('disposition', 'preserved')
        if disposition not in {'preserved', 'corrected', 'conflict', 'unresolved'}:
            violations.append('unknown_disposition')
        if disposition in {'conflict', 'unresolved'}:
            pending.append(disposition)
        amendment = claim.get('amendment_source')
        if disposition == 'corrected' and (not isinstance(amendment, str) or amendment not in {s['id'] for s in sources if isinstance(s, dict) and isinstance(s.get('id'), str)}):
            pending.append('missing_correction_basis')
        review = claim.get('review', {})
        if (not isinstance(review, dict) or review.get('status') != 'approved'
                or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()):
            pending.append('independent_review_not_recorded')
        elif review.get('binding_sha256') != review_binding(claim):
            pending.append('review_binding_changed')
        checked.append({'id': claim['id'], 'status': 'blocked' if violations else 'needs_review' if pending else 'checked',
                        'report_line': report[:report.index(quote.replace('\r\n', '\n'))].count('\n') + 1
                            if isinstance(quote, str) and quote.strip() and report.count(quote.replace('\r\n', '\n')) == 1 else None,
                        'violations': violations, 'pending': pending})
    return {'claims': checked, 'report_sha256': digest(report_bytes), 'metrics': metrics,
            'source_errors': source_errors,
            'selected_claims_checked': all(item['status'] == 'checked' for item in checked),
            'scope': 'Selected source/quote bindings and declared reviewed fact tuples only. '
                     'No automatic extraction, semantic entailment, exhaustive coverage, scientific validation, '
                     'reviewer authentication, actual resolver I/O measurement or cleanup authorization.'}
