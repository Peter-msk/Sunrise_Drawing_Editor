"""Bounded drawing discovery and restart-safe batch recovery; no renderer duplication."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat
import tempfile

from .core import DrawingError, OutputOptions, verify_source
from .batch import ExportJob, checked_output_parent, confirmed_output

MAX_FILES = 1000
MAX_ENTRIES = 100_000
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_STATES = 2_000_000


def discover_drawings(folder, *, recursive=False, cancelled=None):
    """Never follow symlinks/reparse points; fail without partial registration."""
    requested = Path(folder).expanduser().absolute()
    # A directory picker can return a junction/reparse point as the root.
    # Resolving it first would silently bypass the link policy below.
    root_info = requested.lstat()
    if (stat.S_ISLNK(root_info.st_mode) or
            getattr(root_info, 'st_file_attributes', 0) & 0x400):
        raise DrawingError('연결 폴더 또는 재분석 지점은 검색할 수 없습니다.')
    root = requested.resolve(strict=True)
    if not root.is_dir():
        raise DrawingError('도면 폴더가 아닙니다.')
    pending, found, scanned = [root], [], 0
    while pending:
        if cancelled and cancelled():
            raise InterruptedError('폴더 검색 취소')
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if cancelled and cancelled():
                    raise InterruptedError('폴더 검색 취소')
                scanned += 1
                if scanned > MAX_ENTRIES:
                    raise DrawingError('폴더 항목 100,000개 초과: 검색 범위를 줄이세요.')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    continue
                if recursive and stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode) and Path(entry.name).suffix.casefold() in ('.pdf', '.dxf', '.dwg'):
                    found.append(entry.path)
                    if len(found) > MAX_FILES:
                        raise DrawingError('도면 1,000개 초과: 검색 범위를 줄이세요.')
    return tuple(sorted(found, key=lambda p: (p.casefold(), p)))


@dataclass
class BatchSession:
    """Restarts only known original jobs, never imports executable jobs from reports."""
    jobs: tuple
    options: object

    def __post_init__(self):
        self.jobs = tuple(self.jobs)
        self._completed = set()
        self._errors = {}
        self.attempts = 0
        self.last_status = 'pending'
        self.worker_error = ''
        if len(self.jobs) > MAX_FILES:
            raise DrawingError('일괄 작업은 최대 1,000개입니다.')
        if sum(len(j.states) for j in self.jobs) > MAX_STATES:
            raise DrawingError('일괄 작업 레이어 상태가 너무 많습니다.')
        names = [str(Path(j.target)).casefold() for j in self.jobs]
        if len(names) != len(set(names)):
            raise DrawingError('중복 출력 파일명은 재실행 기록에 사용할 수 없습니다.')

    def record(self, attempted, result=None, error=''):
        self.attempts += 1
        self.worker_error = str(error or (result.worker_error if result is not None else ""))[:20000]
        allowed = {j.target for j in attempted}
        for target in allowed:
            self._errors.pop(target, None)
        if result is None:
            self.last_status = 'worker_error'
            return
        # A worker acknowledgement alone is insufficient if the file vanished or
        # a junction/symlink was substituted before the GUI handled the result.
        for target in result.completed:
            if target in allowed and confirmed_output(target):
                self._completed.add(target)
        by_target = {j.target: j.target for j in attempted}
        # Legacy worker replies can use basenames, but they are ambiguous
        # for equal filenames in different project subfolders. Never guess.
        by_name = {}
        ambiguous = set()
        for job in attempted:
            name = Path(job.target).name
            if name in by_name:
                ambiguous.add(name)
            else:
                by_name[name] = job.target
        for name, message in result.errors:
            target = by_target.get(name)
            if target is None and name not in ambiguous:
                target = by_name.get(name)
            if target is not None and target not in self._completed:
                self._errors[target] = str(message)[:2000]
        self.last_status = ('worker_error' if self.worker_error else 'cancelled' if result.cancelled
                            else 'errors' if result.errors else 'finished')

    def retry_plan(self):
        eligible, blocked = [], []
        for job in self.jobs:
            if job.target in self._completed:
                continue
            if os.path.lexists(job.target):
                blocked.append((job.target, '출력 파일이 이미 존재하여 재실행하지 않음 (성공 미확인)'))
                continue
            try:
                if job.source_signature is None:
                    raise DrawingError('등록 원본 식별정보 없음')
                verify_source(job.source, job.source_signature)
                checked_output_parent(job.target)
            except (DrawingError, OSError, ValueError, RuntimeError) as exc:
                blocked.append((job.target, str(exc)))
                continue
            eligible.append(job)
        return tuple(eligible), tuple(blocked)

    def report(self):
        _, blocked = self.retry_plan()
        reasons = dict(blocked)
        return {'schema_version': 1, 'attempts': self.attempts, 'last_status': self.last_status,
                'worker_error': self.worker_error, 'options': asdict(self.options),
                'jobs': [{'source': j.source, 'target': j.target, 'page': j.page_index + 1,
                          'status': ('completed' if j.target in self._completed else
                                     'blocked' if j.target in reasons else
                                     'failed' if j.target in self._errors else 'pending'),
                          'error': self._errors.get(j.target, ''),
                          'blocked_reason': reasons.get(j.target, '')} for j in self.jobs]}

    def save_report(self, path):
        # Exclusive create; even dangling symlinks are never followed.
        data = json.dumps(self.report(), ensure_ascii=False, indent=2, allow_nan=False)
        target = Path(path).expanduser().absolute()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                             prefix='.sde-report-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


    def checkpoint_payload(self):
        """Serializable, inert job data. This is NOT a command/script format."""
        jobs = []
        for job in self.jobs:
            states = [[key, value] for key, value in job.states.items()]
            jobs.append({'source': job.source, 'target': job.target,
                         'page_index': job.page_index,
                         'states': states, 'source_signature': list(job.source_signature)
                         if job.source_signature is not None else None})
        return {'schema': 'sunrise.batch-session', 'schema_version': 3,
                'options': asdict(self.options), 'jobs': jobs,
                'completed': sorted(self._completed),
                'errors': [[key, value] for key, value in sorted(self._errors.items())],
                'attempts': self.attempts, 'last_status': self.last_status,
                'worker_error': self.worker_error}

    def save_checkpoint(self, path):
        """Atomic replace; no source/output file is ever modified."""
        destination = Path(path).expanduser().absolute()
        data = json.dumps(self.checkpoint_payload(), ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(data) > MAX_CHECKPOINT_BYTES:
            raise DrawingError('작업 기록이 16MiB를 초과했습니다. 도면을 나누어 추출하세요.')
        tmp = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.sde-checkpoint-',
                                             suffix='.tmp', delete=False) as handle:
                tmp = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # os.replace replaces the link itself, not a symlink's target.
            os.replace(tmp, destination)
        except OSError as exc:
            raise DrawingError(f'작업 기록 저장 실패: {exc}') from exc
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    @classmethod
    def load_checkpoint(cls, path):
        """Recover only bounded data. Every source/target is rechecked at retry."""
        def no_duplicates(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError('중복 JSON 키')
            return value
        try:
            with Path(path).open('rb') as handle:
                data = handle.read(MAX_CHECKPOINT_BYTES + 1)
            if len(data) > MAX_CHECKPOINT_BYTES:
                raise ValueError('작업 기록 용량 초과')
            root = json.loads(data.decode('utf-8'), object_pairs_hook=no_duplicates)
            fields = {'schema', 'schema_version', 'options', 'jobs', 'completed',
                      'attempts', 'last_status', 'worker_error'}
            if type(root) is not dict or type(root.get('schema_version')) is not int:
                raise ValueError('작업 기록 형식 오류')
            version = root['schema_version']
            required = fields | ({'errors'} if version == 3 else set())
            if (version not in (2, 3) or set(root) != required or
                    root['schema'] != 'sunrise.batch-session'):
                raise ValueError('작업 기록 형식 또는 버전 불일치')
            options_data = root['options']
            if type(options_data) is not dict or set(options_data) != set(OutputOptions.__dataclass_fields__):
                raise ValueError('출력 옵션 필드가 일치하지 않습니다.')
            if options_data['region'] is not None:
                options_data['region'] = tuple(options_data['region'])
            options = OutputOptions(**options_data).checked()
            raw_jobs = root['jobs']
            if type(raw_jobs) is not list or not 1 <= len(raw_jobs) <= MAX_FILES:
                raise ValueError('작업 개수가 범위를 벗어났습니다.')
            entries, jobs = 0, []
            for value in raw_jobs:
                if type(value) is not dict or set(value) != {
                    'source', 'target', 'page_index', 'states', 'source_signature'}:
                    raise ValueError('작업 필드 오류')
                source, target, page, states, signature = (
                    value['source'], value['target'], value['page_index'],
                    value['states'], value['source_signature'])
                if (type(source) is not str or type(target) is not str or
                    not source or not target or not Path(source).is_absolute() or
                    not Path(target).is_absolute() or source == target or
                    Path(source).suffix.casefold() not in ('.pdf', '.dxf', '.dwg') or
                    Path(target).suffix.casefold() != '.' + options.fmt or
                    type(page) is not int or not 0 <= page < 1000000 or
                    type(signature) is not list or len(signature) != 5 or
                    any(type(v) is not int or v < 0 for v in signature) or
                    type(states) is not list):
                    raise ValueError('원본·결과 경로 또는 페이지·원본 식별정보 오류')
                entries += len(states)
                if entries > MAX_STATES:
                    raise ValueError('레이어 상태 규모 초과')
                parsed = {}
                for pair in states:
                    if (type(pair) is not list or len(pair) != 2 or
                        (type(pair[0]) is not int and type(pair[0]) is not str) or
                        type(pair[1]) is not bool or pair[0] in parsed):
                        raise ValueError('레이어 상태 중복 또는 형식 오류')
                    parsed[pair[0]] = pair[1]
                jobs.append(ExportJob(source, parsed, page, target, tuple(signature)))
            session = cls(tuple(jobs), options)
            completed = root['completed']
            if (type(completed) is not list or len(completed) > len(jobs) or
                not all(type(item) is str for item in completed) or
                len(set(completed)) != len(completed) or
                not set(completed).issubset({job.target for job in jobs})):
                raise ValueError('완료 작업 목록 오류')
            # Completed jobs are never reissued after restore, even if their
            # output was subsequently deleted. A fresh plan is required then.
            session._completed = set(completed)
            if version == 3:
                stored_errors = root['errors']
                if type(stored_errors) is not list or len(stored_errors) > len(jobs):
                    raise ValueError('실패 작업 기록 형식 오류')
                allowed_targets = {job.target for job in jobs}
                for pair in stored_errors:
                    if (type(pair) is not list or len(pair) != 2 or
                            type(pair[0]) is not str or type(pair[1]) is not str or
                            len(pair[1]) > 2000 or pair[0] not in allowed_targets or
                            pair[0] in session._completed or pair[0] in session._errors):
                        raise ValueError('실패 작업 기록이 중복되거나 범위를 벗어났습니다.')
                    session._errors[pair[0]] = pair[1]
            if type(root['attempts']) is not int or not 0 <= root['attempts'] <= 100000:
                raise ValueError('시도 횟수 오류')
            if root['last_status'] not in ('pending','worker_error','cancelled','errors','finished'):
                raise ValueError('작업 상태 오류')
            if type(root['worker_error']) is not str or len(root['worker_error']) > 20000:
                raise ValueError('작업 오류 기록 오류')
            session.attempts = root['attempts']
            session.last_status = root['last_status']
            session.worker_error = root['worker_error']
            return session
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError, DrawingError) as exc:
            raise DrawingError(f'이전 작업 기록을 안전하게 불러올 수 없습니다: {exc}') from exc
