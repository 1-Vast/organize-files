"""Reuse bounded evidence snapshots within one task, without a persistent database.

Cached bytes and extracted facts describe an explicit snapshot, not today's file.
fresh=True re-reads selected sources; it does not prove semantic coverage or permit
deletion. Trusted resolvers own storage identity and their internal I/O. Nothing
is imported from user-supplied module strings, executed, or written to disk.
Create another context for a new root or protection scope; both are read-only.
"""
from __future__ import annotations

import copy
import hashlib
import json

import evidence_index as evidence
from workspace_scout import _sensitive


def _signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


class TaskContext:
    def __init__(self, root, opaque=(), *, source_resolver=None, max_bytes=2 * 1024 * 1024):
        self._root = evidence.checked_root(root)
        self._opaque = tuple(evidence.relative_path(value) for value in opaque)
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('max_bytes must be positive')
        if source_resolver is not None and not callable(source_resolver):
            raise ValueError('source_resolver must be an explicit trusted callable')
        self._resolver, self._limit = source_resolver, max_bytes
        self._sources, self._records = {}, {}
        self._metrics = {'payload_files_opened': 0, 'resolver_calls': 0, 'bytes_returned': 0,
                         'sha256_computations': 0, 'cache_hits': 0, 'source_stat_calls': 0}

    @property
    def metrics(self):
        return dict(self._metrics)

    @property
    def root(self):
        return self._root

    @property
    def opaque(self):
        return self._opaque

    def _load(self, source_id, fresh=False):
        evidence.relative_path(source_id)
        if (evidence.exclusion_reason(source_id, self.opaque)
                or any(_sensitive(part) for part in source_id.split('/'))):
            raise ValueError('Protected or opaque source is outside the read boundary')
        if not fresh and source_id in self._sources:
            self._metrics['cache_hits'] += 1
            return self._sources[source_id]
        # A failed fresh read must not fall back to stale cached bytes.
        previous = self._sources.pop(source_id, None)
        if self._resolver is None:
            path = evidence.checked_path(self.root, source_id)
            before = evidence.file_metadata(path, self._metrics)
            if before['size'] > self._limit:
                raise ValueError('Source exceeds the task read limit')
            with path.open('rb') as stream:
                self._metrics['payload_files_opened'] += 1
                payload = stream.read(self._limit + 1)
            self._metrics['bytes_returned'] += len(payload)
            if before != evidence.file_metadata(path, self._metrics):
                raise ValueError('Source changed while reading')
        else:
            self._metrics['resolver_calls'] += 1
            payload = self._resolver(source_id)
            if not isinstance(payload, bytes):
                raise TypeError('Trusted resolver must return bytes')
            self._metrics['bytes_returned'] += len(payload)
        if len(payload) > self._limit:
            raise ValueError('Source exceeds the task read limit')
        if b'\0' in payload:
            raise ValueError('Binary source is outside the text context boundary')
        lines = payload.decode('utf-8-sig').splitlines()
        self._metrics['sha256_computations'] += 1
        item = {'source_id': source_id, 'sha256': hashlib.sha256(payload).hexdigest(),
                'bytes': len(payload), 'lines': lines, 'locations': []}
        if previous and previous['sha256'] == item['sha256']:
            item['locations'] = previous['locations']
        self._sources[source_id] = item
        return item

    def excerpt(self, source_id, start_line=1, end_line=40, *, fresh=False):
        if (type(start_line) is not int or type(end_line) is not int
                or start_line < 1 or end_line < start_line or end_line - start_line >= 200):
            raise ValueError('Select 1 to 200 explicit source lines')
        item = self._load(source_id, fresh)
        if start_line > len(item['lines']):
            raise ValueError('Selected lines are outside the source')
        stop = min(end_line, len(item['lines']))
        excerpt = '\n'.join(item['lines'][start_line - 1:stop])
        if len(excerpt) > 12000:
            raise ValueError('Excerpt exceeds the compact output bound; select narrower lines')
        location = {'start_line': start_line, 'end_line': stop}
        if location not in item['locations']:
            item['locations'].append(location)
        return {'source_id': source_id, 'sha256': item['sha256'], 'bytes': item['bytes'],
                'start_line': start_line, 'end_line': stop,
                'excerpt': excerpt,
                'scope': 'Fixed task snapshot; live source was re-read for this call' if fresh
                         else 'Fixed task snapshot; current live bytes are not certified'}

    def batch(self, requests, *, fresh=False):
        results, refreshed = [], set()
        for request_index, request in enumerate(requests):
            sid = request.get('source_id') if isinstance(request, dict) else None
            try:
                if not isinstance(request, dict):
                    raise ValueError('Each request must declare source_id and line bounds')
                item = self.excerpt(sid, request.get('start_line', 1), request.get('end_line', 40),
                                    fresh=fresh and sid not in refreshed)
                refreshed.add(sid)
                results.append({'request_index': request_index, 'status': 'available', **item})
            except Exception as error:
                results.append({'request_index': request_index, 'status': 'unavailable',
                                'error_type': type(error).__name__})
        return {'complete': bool(results) and all(r['status'] == 'available' for r in results),
                'results': results, 'metrics': self.metrics}

    def record(self, key, source_ids, *, facts, dependencies=(), unresolved_questions=(),
               required_context=(), context_reviews=None):
        source_ids = tuple(source_ids)
        dependencies = tuple(dependencies)
        unresolved_questions = tuple(unresolved_questions)
        if not isinstance(key, str) or not key.strip() or not source_ids:
            raise ValueError('A record needs a nonempty key and selected sources')
        if key in dependencies or any(dep not in self._records for dep in dependencies):
            raise ValueError('Dependencies must be existing records other than this record')
        pending, seen = list(dependencies), set()
        while pending:
            dependency = pending.pop()
            if dependency == key:
                raise ValueError('Record dependencies must not form a cycle')
            if dependency not in seen:
                seen.add(dependency)
                pending.extend(self._records[dependency]['dependencies'])
        if any(not isinstance(q, str) or not q.strip() for q in unresolved_questions):
            raise ValueError('Unresolved questions must be explicit nonempty strings')
        if any(sid not in self._sources for sid in source_ids):
            raise ValueError('Read every selected source before recording facts')
        if isinstance(required_context, str):
            raise ValueError('Required context must be a sequence of dimension names')
        required_context = tuple(required_context)
        if (any(not isinstance(name, str) or not name.strip() for name in required_context)
                or len(set(required_context)) != len(required_context)):
            raise ValueError('Required context must contain unique nonempty dimension names')
        reviews = {} if context_reviews is None else copy.deepcopy(context_reviews)
        if not isinstance(reviews, dict) or any(name not in required_context for name in reviews):
            raise ValueError('Reviews must name declared context dimensions')
        for review in reviews.values():
            if (not isinstance(review, dict) or not isinstance(review.get('note'), str)
                    or not review['note'].strip() or not isinstance(review.get('citations'), list)
                    or not review['citations'] or review.get('status') not in ('reviewed', 'unknown')):
                raise ValueError('Each context review needs a status, note and nonempty citations')
            citations = []
            for citation in review['citations']:
                if not isinstance(citation, dict) or citation.get('source_id') not in source_ids:
                    raise ValueError('Context citations must belong to selected sources')
                source = self._sources[citation['source_id']]
                start, end = citation.get('start_line'), citation.get('end_line')
                if (type(start) is not int or type(end) is not int
                        or {'start_line': start, 'end_line': end} not in source['locations']
                        or citation.get('sha256') != source['sha256']
                        or citation.get('excerpt') != '\n'.join(source['lines'][start - 1:end])):
                    raise ValueError('Context citations must match an emitted snapshot excerpt')
                if review['status'] == 'reviewed' and not citation['excerpt'].strip():
                    raise ValueError('Reviewed context requires nonblank citations')
                citations.append({field: citation[field] for field in
                                  ('source_id', 'sha256', 'start_line', 'end_line', 'excerpt')})
            review['citations'] = citations
        body = {'source_bindings': {sid: self._sources[sid]['sha256'] for sid in source_ids},
                'source_locations': {sid: copy.deepcopy(self._sources[sid]['locations']) for sid in source_ids},
                'facts': copy.deepcopy(facts),
                'dependencies': {dep: self._records[dep]['signature'] for dep in dependencies},
                'unresolved_questions': list(unresolved_questions),
                'required_context': list(required_context), 'context_reviews': reviews}
        self._records[key] = {**body, 'signature': _signature(body)}
        return self.result(key)

    def result(self, key, *, fresh=False, compact=False):
        """Return declared coverage, never a semantic verdict.

        compact omits facts and review quotes, while retaining bindings and every
        pending dimension/question in the selected dependency closure.
        """
        if key not in self._records:
            raise KeyError(key)
        visited, sources, errors = set(), set(), []
        def collect(name):
            if name in visited:
                return
            visited.add(name)
            item = self._records[name]
            sources.update(item['source_bindings'])
            for dependency in item['dependencies']:
                collect(dependency)
        collect(key)
        if fresh:
            for source_id in sorted(sources):
                try:
                    self._load(source_id, True)
                except Exception as error:
                    errors.append({'error_type': type(error).__name__})
        invalid, unresolved, gaps, unassessed = [], [], {}, []
        for name in sorted(visited):
            item = self._records[name]
            if (any(self._sources.get(sid, {}).get('sha256') != digest
                    for sid, digest in item['source_bindings'].items())
                    or any(self._records[dep]['signature'] != digest
                           for dep, digest in item['dependencies'].items())):
                invalid.append(name)
            unresolved.extend(item['unresolved_questions'])
            if not item['required_context']:
                unassessed.append(name)
            missing = [dimension for dimension in item['required_context']
                       if item['context_reviews'].get(dimension, {}).get('status') != 'reviewed']
            if missing:
                gaps[name] = missing
        snapshot_status = 'stale' if invalid or errors else 'snapshot_reusable'
        closure_status = ('stale' if invalid or errors else 'needs_review' if unresolved or gaps else
                          'not_assessed' if unassessed else 'declared_covered')
        record = self._records[key]
        fields = ('signature', 'source_bindings', 'source_locations') if compact else record.keys()
        return {'key': key, **{field: copy.deepcopy(record[field]) for field in fields},
                'snapshot_status': snapshot_status, 'context_gaps': gaps,
                'closure_status': closure_status, 'unassessed_records': unassessed,
                'invalid_records': invalid, 'errors': errors, 'unresolved_questions_in_scope': unresolved,
                'scope': 'Declared facts bound to task snapshots only; not semantic proof or cleanup authorization',
                'metrics': self.metrics}
