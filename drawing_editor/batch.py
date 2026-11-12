"""Reusable layer-name presets and safe sequential multi-drawing export.

No new PDF/CAD parser: reuse DrawingDocument / its proven tile exporter.
Presets never store source paths or PDF OCG IDs, which vary by sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from typing import Callable, Sequence

from .core import DrawingDocument, DrawingError, OutputOptions, export_snapshot


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
    name = str(name).strip()
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise DrawingError('규칙 이름은 1~60자의 한 줄 텍스트여야 합니다.')
    return name


class LayerRuleStore:
    """Presets stored in user data directory, replaced atomically."""

    def __init__(self, storage_path: str | Path):
        self.path = Path(storage_path)

    def load(self) -> dict[str, LayerRule]:
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 2_000_000:
                raise DrawingError('레이어 규칙 파일이 너무 큽니다.')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('presets'), list):
                raise ValueError('presets 목록이 없습니다.')
            if len(data['presets']) > 100:
                raise ValueError('규칙 개수가 허용 범위를 넘었습니다.')
            result: dict[str, LayerRule] = {}
            for raw in data['presets']:
                name = _check_preset_name(raw['name'])
                kind = raw['kind']
                if kind not in ('pdf', 'dxf', 'dwg'):
                    raise ValueError('지원되지 않는 규칙의 도면 형식입니다.')
                raw_layers = raw['layers']
                if not isinstance(raw_layers, list) or not 1 <= len(raw_layers) <= 10000:
                    raise ValueError('규칙의 레이어 수가 유효하지 않습니다.')
                layers: list[tuple[str, bool]] = []
                names: set[str] = set()
                for entry in raw_layers:
                    text, flag = entry['name'], entry['visible']
                    if not isinstance(text, str) or len(text) > 1024 or type(flag) is not bool:
                        raise ValueError('규칙 레이어 항목이 유효하지 않습니다.')
                    key = layer_name_key(text)
                    if not key or key in names:
                        raise ValueError('규칙에 빈 이름 또는 중복 레이어가 있습니다.')
                    names.add(key)
                    layers.append((text, flag))
                if name in result:
                    raise ValueError('중복 규칙 이름이 있습니다.')
                result[name] = LayerRule(name, kind, tuple(layers))
            return result
        except DrawingError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             prefix='.rule-', suffix='.json',
                                             dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(body, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
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


@dataclass(frozen=True)
class BatchResult:
    completed: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    cancelled: bool


def plan_exports(docs: Sequence[DrawingDocument], folder: str | Path,
                 options: OutputOptions) -> list[ExportJob]:
    """Reserve unique names for all selected drawings, never overwrite existing output."""
    opts = options.checked()
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise DrawingError('이미지 저장 폴더가 존재하지 않습니다.')
    if not docs:
        raise DrawingError('이미지 추출할 도면을 선택하세요.')
    reserved: set[str] = set()
    jobs: list[ExportJob] = []
    for doc in docs:
        stem = doc.path.stem[:150] + '_레이어적용'
        number = 1
        while True:
            suffix = '' if number == 1 else f'_{number}'
            destination = root / f'{stem}{suffix}.{opts.fmt}'
            key = destination.name.casefold()  # Windows filesystem is usually case-insensitive.
            if key not in reserved and not destination.exists():
                reserved.add(key)
                break
            number += 1
        jobs.append(ExportJob(str(doc.path), doc.states(), doc.page_index, str(destination)))
    return jobs


def run_batch_exports(jobs: Sequence[ExportJob], options: OutputOptions,
                      progress: Callable[[int, int, float, str], None] | None = None,
                      cancelled: Callable[[], bool] | None = None) -> BatchResult:
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
            result = export_snapshot(
                job.source, job.states, job.page_index, job.target, options,
                progress=(lambda value, idx=index, name=Path(job.source).name:
                          progress(idx, total, value, name)) if progress else None,
                cancelled=cancelled,
            )
            completed.append(result)
        except Exception as exc:
            if cancelled and cancelled():
                return BatchResult(tuple(completed), tuple(errors), True)
            errors.append((Path(job.source).name, str(exc)))
        if progress:
            progress(index + 1, total, 0., Path(job.source).name)
    return BatchResult(tuple(completed), tuple(errors), False)
