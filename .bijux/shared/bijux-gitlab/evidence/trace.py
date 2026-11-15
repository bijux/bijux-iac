"""Retain actual native trace sections without manufacturing step outcomes."""
from __future__ import annotations

from datetime import datetime
import hashlib
import math
import re

MAX_TRACE_BYTES = 32 * 1024 * 1024
RECORD_PREFIX = (rb'(?:\x1b\[0K|(?m:^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                 rb'(?:\.[0-9]{1,9})?Z [0-9]{2}[OE][ +](?:\x1b\[0K)?))')
MARKER = re.compile(RECORD_PREFIX + rb'section_(start|end):([0-9]{1,12}):([A-Za-z0-9_.-]{1,255})(\[[A-Za-z0-9_=,.-]+\])?\r\x1b\[0K')
CANDIDATE = re.compile(RECORD_PREFIX + rb'section_(?:start|end):')


def parse_sections(data: bytes, *, started_at: str, finished_at: str) -> dict:
    if not isinstance(data, bytes) or len(data) > MAX_TRACE_BYTES:
        raise ValueError('Native trace exceeds its bounded byte inventory')
    started, finished = (datetime.fromisoformat(value.replace('Z', '+00:00')) for value in (started_at, finished_at))
    if started.tzinfo is None or finished.tzinfo is None or started > finished:
        raise ValueError('Ordered timezone-bound job timestamps are required for trace sections')
    matches = list(MARKER.finditer(data))
    if len(matches) != len(list(CANDIDATE.finditer(data))):
        raise ValueError('Malformed native section marker')
    if len(matches) > 4096:
        raise ValueError('Native section inventory is unbounded')
    stack, sections, previous = [], [], None
    lower, upper = math.floor(started.timestamp()), math.floor(finished.timestamp())
    for match in matches:
        kind, epoch, name, options = match.groups()
        epoch, name = int(epoch), name.decode('ascii')
        if not lower <= epoch <= upper or previous is not None and epoch < previous:
            raise ValueError('Native section timestamp is outside its physical job or out of order')
        previous = epoch
        if kind == b'start':
            stack.append({'name': name, 'started_epoch': epoch, 'start_offset': match.start(),
                          'options': options.decode('ascii') if options else None, 'depth': len(stack)})
        else:
            if options or not stack or stack[-1]['name'] != name:
                raise ValueError('Unmatched or crossed native trace sections')
            record = stack.pop()
            sections.append({**record, 'finished_epoch': epoch, 'seconds': epoch - record['started_epoch'],
                             'end_offset': match.end()})
    if stack:
        raise ValueError('Native trace has unfinished sections')
    return {'schema': 1, 'status': 'observed' if matches else 'unavailable',
            'trace_sha256': hashlib.sha256(data).hexdigest(), 'trace_bytes': len(data),
            'sections': sorted(sections, key=lambda record: record['start_offset']),
            'limits': ['Trace sections retain native log markers with whole-second precision.',
                       'Sections can be emitted by scripts; they do not independently establish step success or artifact authority.',
                       'Missing native sections are explicit and never replaced by invented steps.']}
