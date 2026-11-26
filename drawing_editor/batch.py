"""Reusable layer-name presets and safe sequential multi-drawing export.

No new PDF/CAD parser: reuse DrawingDocument / its proven tile exporter.
Presets never store source paths or PDF OCG IDs, which vary by sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import stat
from pathlib import Path
import tempfile
import unicodedata
from typing import Callable, Sequence

from .core import DrawingDocument, DrawingError, OutputOptions, export_snapshot, source_signature, verify_source


def layer_name_key(name: str) -> str:
    """Normalize benign Unicode differences, not arbitrary naming differences."""
    return unicodedata.normalize('NFKC', str(name)).strip().casefold()


@dataclass(frozen=True)
class LayerRule:
    name: str
    kind: str
    layers: tuple[tuple[str, bool], ...]

    @classmethod
    def from_document(cls, name: str, doc: DrawingDocument) -> 'LayerRule':
        name = _check_preset_name(name)
        seen: set[str] = set()
        entries: list[tuple[str, bool]] = []
        for layer in doc.layers():
            if layer.locked:
                continue  # Read-only OCG controls must not become editable policies.
            normalized = layer_name_key(layer.name)
            if not normalized:
                raise DrawingError('이름이 없는 레이어를 규칙으로 저장할 수 없습니다.')
            if normalized in seen:
                raise DrawingError(f'중복 레이어 이름이 있어 규칙을 만들 수 없습니다: {layer.name}')
            seen.add(normalized)
            entries.append((layer.name, layer.visible))
        if not entries:
            raise DrawingError('저장할 수 있는 레이어가 없습니다.')
        return cls(name, doc.kind, tuple(entries))


def _check_preset_name(name: str) -> str:
    if not isinstance(name, str):
        raise DrawingError('규칙 이름은 문자열이어야 합니다.')
    name = name.strip()
    try:
        name.encode('utf-8')
    except UnicodeError as exc:
        raise DrawingError('규칙 이름 인코딩 오류') from exc
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise DrawingError('규칙 이름은 1~60자의 한 줄 텍스트여야 합니다.')
    return name


class LayerRuleStore:
    """Presets stored in user data directory, replaced atomically."""

    def __init__(self, storage_path: str | Path):
        self.path = Path(storage_path)

    @staticmethod
    def _decode(data):
        if not isinstance(data, dict) or set(data) != {'presets'} or not isinstance(data['presets'], list):
            raise ValueError('presets 목록이 없습니다.')
        if len(data['presets']) > 100:
            raise ValueError('규칙 개수가 허용 범위를 넘었습니다.')
        result = {}
        for raw in data['presets']:
            if not isinstance(raw, dict) or set(raw) != {'name', 'kind', 'layers'}:
                raise ValueError('규칙 항목 오류')
            name = _check_preset_name(raw['name'])
            kind = raw['kind']
            if kind not in ('pdf', 'dxf', 'dwg'):
                raise ValueError('지원되지 않는 규칙의 도면 형식입니다.')
            raw_layers = raw['layers']
            if not isinstance(raw_layers, list) or not 1 <= len(raw_layers) <= 10000:
                raise ValueError('규칙의 레이어 수가 유효하지 않습니다.')
            layers, names = [], set()
            for entry in raw_layers:
                if not isinstance(entry, dict) or set(entry) != {'name', 'visible'}:
                    raise ValueError('규칙 레이어 항목 오류')
                text, flag = entry['name'], entry['visible']
                if not isinstance(text, str) or len(text) > 1024 or type(flag) is not bool:
                    raise ValueError('규칙 레이어 항목이 유효하지 않습니다.')
                text.encode('utf-8')
                key = layer_name_key(text)
                if not key or key in names:
                    raise ValueError('규칙에 빈 이름 또는 중복 레이어가 있습니다.')
                names.add(key)
                layers.append((text, flag))
            if name in result:
                raise ValueError('중복 규칙 이름이 있습니다.')
            result[name] = LayerRule(name, kind, tuple(layers))
        return result

    def load(self) -> dict[str, LayerRule]:
        def unique(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError('중복 JSON 키')
            return result
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise DrawingError('레이어 규칙 파일이 너무 큽니다.')
            return self._decode(json.loads(raw.decode('utf-8'), object_pairs_hook=unique))
        except FileNotFoundError:
            return {}
        except DrawingError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise DrawingError(f'레이어 규칙 파일을 읽지 못했습니다: {exc}') from exc

    def save_all(self, rules: dict[str, LayerRule]) -> None:
        if len(rules) > 100:
            raise DrawingError('최대 100개의 규칙을 저장할 수 있습니다.')
        body = {
            'presets': [
                {'name': p.name, 'kind': p.kind,
                 'layers': [{'name': n, 'visible': v} for n, v in p.layers]}
                for p in rules.values()
            ]
        }
        temporary: Path | None = None
        try:
            self._decode(body)
            encoded = json.dumps(body, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
            if len(encoded) > 2_000_000:
                raise DrawingError('레이어 규칙 파일이 너무 큽니다.')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='wb',
                                             prefix='.rule-', suffix='.json',
                                             dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise DrawingError(f'레이어 규칙 저장 실패: {exc}') from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ApplyResult:
    matching_kind: bool
    matched: int = 0
    changed: int = 0
    missing: int = 0
    ambiguous: int = 0
    locked: int = 0


def apply_rule(doc: DrawingDocument, rule: LayerRule) -> ApplyResult:
    """Match layer names; apply all changes with ONE document snapshot update.

    Missing, locked and ambiguous names remain untouched. A PDF preset is never
    silently applied to CAD and vice versa. No file contents are modified.
    """
    if doc.kind != rule.kind:
        return ApplyResult(False)
    by_name: dict[str, list] = {}
    for layer in doc.layers():
        by_name.setdefault(layer_name_key(layer.name), []).append(layer)
    delta: dict[int | str, bool] = {}
    matched = missing = ambiguous = locked = changed = 0
    for name, desired in rule.layers:
        candidates = by_name.get(layer_name_key(name), [])
        if not candidates:
            missing += 1
        elif len(candidates) != 1:
            ambiguous += 1
        elif candidates[0].locked:
            locked += 1
        else:
            layer = candidates[0]
            matched += 1
            if layer.visible != desired:
                changed += 1
                delta[layer.key] = desired
    if delta:
        doc.apply_snapshot(delta)
    return ApplyResult(True, matched, changed, missing, ambiguous, locked)


@dataclass(frozen=True)
class ExportJob:
    source: str
    states: dict[int | str, bool]
    page_index: int
    target: str
    source_signature: tuple[int, ...] | None = None


@dataclass(frozen=True)
class BatchResult:
    completed: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    cancelled: bool
    worker_error: str = ""


def checked_output_parent(target) -> Path:
    """Reject changed or noncanonical planned output directories."""
    parent = Path(target).parent
    if (not parent.is_absolute() or not parent.is_dir()
            or parent.resolve(strict=True) != parent
            or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
        raise DrawingError("출력 폴더 없음 또는 경로 변경")
    return parent


def confirmed_output(target) -> bool:
    try:
        checked_output_parent(target)
        info = Path(target).lstat()
        return stat.S_ISREG(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)
    except (DrawingError, OSError, ValueError, RuntimeError):
        return False


def planned_source(doc):
    signature = getattr(doc, 'source_signature', None)
    if signature is None:
        signature = source_signature(doc.path)
    verify_source(doc.path, signature)
    return signature


def plan_exports(docs: Sequence[DrawingDocument], folder: str | Path,
                 options: OutputOptions, *, source_root=None) -> list[ExportJob]:
    """Reserve unique names for all selected drawings, never overwrite existing output."""
    opts = options.checked()
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise DrawingError('이미지 저장 폴더가 존재하지 않습니다.')
    if not docs:
        raise DrawingError('이미지 추출할 도면을 선택하세요.')
    if any(not getattr(doc, 'loaded', True) for doc in docs):
        raise DrawingError('선택한 도면의 레이어 분석을 완료하세요.')
    if opts.region is not None and any(doc.kind != 'pdf' for doc in docs):
        raise DrawingError('지정 영역 추출은 PDF만 지원합니다.')
    from .layer_tools import MAX_JOBS, MAX_STATE_ENTRIES
    if len(docs) > MAX_JOBS:
        raise DrawingError('한 번에 최대 1,000개 출력 작업을 지원합니다.')
    entries = 0
    reserved: set[str] = set()
    jobs: list[ExportJob] = []
    next_number = {}
    requested_source = Path(source_root).expanduser().absolute() if source_root is not None else None
    if requested_source is not None:
        info = requested_source.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise DrawingError('사업 폴더는 연결 폴더일 수 없습니다.')
    base_source = requested_source.resolve(strict=True) if requested_source is not None else None
    if base_source is not None and not base_source.is_dir():
        raise DrawingError('사업 폴더가 올바르지 않습니다.')
    for doc in docs:
        signature = planned_source(doc)
        from .vector_export import check_vector_source
        check_vector_source(doc.kind, opts, signature[2])
        subfolder = Path('.')
        if base_source is not None:
            # Each selected file must belong to the explicitly chosen tree.
            try:
                original = Path(doc.path).absolute()
                relative = original.relative_to(base_source)
                # Reject links in the entire project-relative chain, including
                # the source file. A resolved path is not sufficient on its own.
                cursor = base_source
                for part in relative.parts:
                    cursor = cursor / part
                    info = cursor.lstat()
                    if (stat.S_ISLNK(info.st_mode) or
                            getattr(info, 'st_file_attributes', 0) & 0x400):
                        raise DrawingError('사업 폴더의 연결 파일 또는 폴더를 허용하지 않습니다.')
                if original.resolve(strict=True) != original:
                    raise DrawingError('사업 폴더 외부로 연결된 원본을 허용하지 않습니다.')
            except ValueError as exc:
                raise DrawingError(f'{doc.path.name}: 선택한 사업 폴더 밖의 도면입니다.') from exc
            if any(part in ('..', '') for part in relative.parts):
                raise DrawingError('잘못된 사업 폴더 상대 경로입니다.')
            subfolder = relative.parent
        stem = doc.path.stem[:150] + '_레이어적용'
        key_base = (subfolder.as_posix() + '/' + stem).casefold()
        number = next_number.get(key_base, 1)
        while True:
            suffix = '' if number == 1 else f'_{number}'
            destination = root / subfolder / f'{stem}{suffix}.{opts.fmt}'
            key = str(destination).casefold()  # Windows filesystem is usually case-insensitive.
            if key not in reserved and not os.path.lexists(destination):
                reserved.add(key)
                next_number[key_base] = number + 1
                break
            number += 1
        snapshot = doc.states()
        entries += len(snapshot)
        if entries > MAX_STATE_ENTRIES:
            raise DrawingError('출력 계획의 레이어 상태 규모가 너무 큽니다.')
        jobs.append(ExportJob(str(doc.path), snapshot, doc.page_index, str(destination), signature))
    return jobs


def run_batch_exports(jobs: Sequence[ExportJob], options: OutputOptions,
                      progress: Callable[[int, int, float, str], None] | None = None,
                      cancelled: Callable[[], bool] | None = None,
                      render_gate=None, *, outcome=None) -> BatchResult:
    """Sequential bounded-memory exports; per-file failures do not cancel others."""
    completed: list[str] = []
    errors: list[tuple[str, str]] = []
    total = len(jobs)
    for index, job in enumerate(jobs):
        if cancelled and cancelled():
            return BatchResult(tuple(completed), tuple(errors), True)
        if progress:
            progress(index, total, 0., Path(job.source).name)
        try:
            acquired = False
            if render_gate is not None:
                while not render_gate.acquire(timeout=0.15):
                    if cancelled and cancelled():
                        raise InterruptedError('이미지 추출이 취소되었습니다.')
                acquired = True
            try:
                if cancelled and cancelled():
                    raise InterruptedError('이미지 추출이 취소되었습니다.')
                checked_output_parent(job.target)
                result = export_snapshot(
                    job.source, job.states, job.page_index, job.target, options,
                    progress=(lambda value, idx=index, name=Path(job.source).name:
                              progress(idx, total, value, name)) if progress else None,
                    cancelled=cancelled, expected_source=job.source_signature,
                )
            finally:
                if acquired:
                    render_gate.release()
            completed.append(result)
        except InterruptedError:
            return BatchResult(tuple(completed), tuple(errors), True)
        except Exception as exc:
            if cancelled and cancelled():
                return BatchResult(tuple(completed), tuple(errors), True)
            errors.append((job.target, str(exc)))
            if outcome is not None:
                outcome(index, None, str(exc))
        else:
            if outcome is not None:
                outcome(index, result, None)
        if progress:
            progress(index + 1, total, 0., Path(job.source).name)
    return BatchResult(tuple(completed), tuple(errors), False)


def prepare_output_folders(jobs, output_root):
    """Create only required descendant folders after explicit export confirmation.

    A reparse/symlink in any existing ancestor is rejected. Never create a
    source directory, and never allow a planned target to escape output_root.
    """
    root = Path(output_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise DrawingError('출력 폴더가 존재하지 않습니다.')
    for job in jobs:
        destination = Path(job.target)
        if not destination.is_absolute():
            raise DrawingError('출력 경로는 절대경로여야 합니다.')
        try:
            relative = destination.parent.relative_to(root)
        except ValueError as exc:
            raise DrawingError('출력 폴더 밖의 작업이 있습니다.') from exc
        cursor = root
        for part in relative.parts:
            if part in ('..', '.', ''):
                raise DrawingError('잘못된 출력 하위 폴더 이름입니다.')
            cursor = cursor / part
            if os.path.lexists(cursor):
                info = cursor.lstat()
                if not cursor.is_dir() or cursor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise DrawingError(f'출력 경로의 연결 또는 비정상 폴더를 허용하지 않습니다: {cursor}')
            else:
                cursor.mkdir()  # fails closed if raced by another process
        # Existing targets remain per-job conflicts; never overwrite them.
        # The batch worker reports a failure without dropping other jobs.
