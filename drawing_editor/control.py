"""Sunrise Control schema v1: operational policy, not an authorization lease."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from queue import Queue, Empty
import re
import tempfile
import threading
import time
from urllib.request import Request, build_opener
from .release_feed import APP_ID, APP_VERSION, version_tuple, _NoRedirect

URL = 'https://raw.githubusercontent.com/Peter-msk/Sunrise_Control/main/control.txt'
LIMIT = 131072
OPERATIONS = ('allow', 'maintenance', 'block')
UPDATES = ('allow', 'block', 'required')


@dataclass(frozen=True)
class Policy:
    operation: str = 'allow'
    update: str = 'allow'
    minimum_version: str = ''
    message: str = ''
    source: str = 'fallback'
    ttl: int = 21600
    fallback_operation: str = 'allow'
    fallback_update: str = 'allow'

    @property
    def blocks_entry(self):
        return self.operation != 'allow'

    @property
    def requires_update(self):
        return self.update == 'required' and bool(self.minimum_version) and version_tuple(APP_VERSION) < version_tuple(self.minimum_version)

    def fallback(self):
        return Policy(self.fallback_operation, self.fallback_update)


class ControlDenied(RuntimeError):
    pass


def parse_control(body, source='online'):
    if not isinstance(body, str) or len(body.encode('utf-8')) > LIMIT:
        raise ValueError('Invalid control size')
    sections = {}
    current = None
    for raw in body.lstrip('\ufeff').splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip().lower()
            if not name or name in sections:
                raise ValueError('Duplicate/empty control section')
            current = sections[name] = {}
            continue
        key, sep, value = line.partition('=')
        key = key.strip().lower()
        if current is None or not sep or not key or key in current:
            raise ValueError('Invalid/duplicate control entry')
        current[key] = value.strip()
    glob = sections.get('global', {})
    if glob.get('schema_version') != '1':
        raise ValueError('Unsupported control schema')
    product = sections.get('product.' + APP_ID, {})
    op = product.get('operation', glob.get('default_operation', 'allow')).lower()
    update = product.get('update', glob.get('default_update', 'allow')).lower()
    fop = glob.get('fallback_operation', 'allow').lower()
    fup = glob.get('fallback_update', 'allow').lower()
    if op not in OPERATIONS or fop not in OPERATIONS or update not in UPDATES or fup not in UPDATES:
        raise ValueError('Unsupported control state')
    minimum = product.get('minimum_version', '')
    if minimum:
        version_tuple(minimum)
    raw_ttl = glob.get('cache_ttl_seconds', '')
    ttl = max(60, min(86400, int(raw_ttl))) if re.fullmatch(r'[0-9]{1,9}', raw_ttl) else 21600
    return Policy(op, update, minimum, product.get('message', ''), source, ttl, fop, fup)


def cache_path():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache')
    return base / 'Sunrise Group' / 'DrawingEditor' / 'control-v1-cache.json'


def fetch_control():
    # Bound caller wall-clock wait even if DNS stalls. The daemon only reads,
    # never writes a policy cache after its caller has timed out.
    result = Queue(maxsize=1)
    def receive():
        try:
            request = Request(URL, headers={'User-Agent': 'Sunrise-Drawing-Editor/' + APP_VERSION,
                                            'Accept-Encoding': 'identity'})
            with build_opener(_NoRedirect()).open(request, timeout=5) as response:
                payload = response.read(LIMIT + 1)
            if len(payload) > LIMIT:
                raise ValueError('Control response too large')
            result.put(payload.decode('utf-8-sig'))
        except Exception as exc:
            result.put(exc)
    threading.Thread(target=receive, daemon=True, name='sunrise-control-read').start()
    try:
        value = result.get(timeout=5)
    except Empty:
        raise TimeoutError('Control request timed out') from None
    if isinstance(value, Exception):
        raise value
    return value


def _read_cache(path, now):
    try:
        with path.open('rb') as stream:
            raw = stream.read(300001)
        if len(raw) > 300000:
            raise ValueError('Cache too large')
        record = json.loads(raw)
        stamp = record['fetched_at']
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError('Invalid cache time')
        policy = parse_control(record['content'], 'cache')
        if 0 <= now - stamp <= policy.ttl:
            return policy
        return policy.fallback()
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return Policy()


def _save_cache(path, body, now):
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.control-', delete=False) as stream:
            temp = Path(stream.name)
            json.dump({'content': body, 'fetched_at': now}, stream, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
        pass  # Valid online policy is independent of cache write access.
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def check_policy(*, fetch=fetch_control, path=None, now=None):
    path = cache_path() if path is None else Path(path)
    now = time.time() if now is None else now
    try:
        body = fetch()
        policy = parse_control(body)
    except Exception:
        return _read_cache(path, now)
    _save_cache(path, body, now)
    return policy


def ensure_update_allowed(policy, target_version=None):
    if policy.update == 'block':
        raise ControlDenied(policy.message or 'Sunrise Control 정책에 따라 업데이트가 차단되었습니다.')
    if target_version and policy.update == 'required' and policy.minimum_version:
        if version_tuple(target_version) < version_tuple(policy.minimum_version):
            raise ControlDenied('최소 지원 버전을 충족하는 업데이트가 필요합니다.')
