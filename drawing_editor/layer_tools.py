"""Read-only layer classification and bounded, non-mutating extraction plans."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .batch import ExportJob, layer_name_key, planned_source
from .core import DrawingError

# Conservative, deterministic name hints. Classification is advisory, never a
# claim that the drawing actually contains the indicated environmental data.
GROUPS = {
    '도로': ('road', 'roads', 'street', '도로', '도로망', '차도'),
    '건축물': ('bldg', 'building', 'buildings', '건축물', '건물'),
    '수계': ('water', 'river', 'stream', '하천', '수계', '수로'),
    '지형': ('contour', 'contours', 'terrain', '등고선', '지형', '표고점'),
    '경계': ('boundary', 'border', 'parcel', '경계', '지적', '사업지구'),
    '문자': ('text', 'label', 'anno', 'annotation', '문자', '주기', '주석'),
    '식생': ('vegetation', 'forest', 'tree', '식생', '산림', '수목'),
}
_TOKEN_GROUP = {word: group for group, words in GROUPS.items() for word in words}
_TOKEN_PATTERN = re.compile(r'[^\W_]+')
UNKNOWN = '미분류'
GROUP_NAMES = tuple(GROUPS) + (UNKNOWN,)
MAX_JOBS = 1000
MAX_STATE_ENTRIES = 2_000_000


def classify(name):
    hits = {_TOKEN_GROUP[token] for token in _TOKEN_PATTERN.findall(layer_name_key(name))
            if token in _TOKEN_GROUP}
    return next(iter(hits)) if len(hits) == 1 else UNKNOWN


def group_layers(layers):
    result = defaultdict(list)
    for layer in layers:
        result[classify(layer.name)].append(layer)
    return {group: tuple(result[group]) for group in GROUP_NAMES if result[group]}


def _index(layers):
    result = defaultdict(list)
    for layer in layers:
        key = layer_name_key(layer.name)
        if key:
            result[key].append(layer)
    return result


def common_layers(docs):
    """Only names unique and unlocked in EVERY chosen document qualify."""
    if not docs or any(not doc.loaded for doc in docs):
        raise DrawingError('선택한 도면의 레이어 분석을 완료하세요.')
    first = _index(docs[0].layers())
    common = {key for key, items in first.items() if len(items) == 1 and not items[0].locked}
    for doc in docs[1:]:
        if not common:
            break
        index = _index(doc.layers())
        common.intersection_update(key for key, items in index.items()
                                   if len(items) == 1 and not items[0].locked)
    return {key: first[key][0].name for key in sorted(common)}


def apply_common_layers(docs, keys, visible):
    eligible = common_layers(docs)
    selected = set(keys)
    if not selected or not selected <= eligible.keys():
        raise DrawingError('변경 가능한 공통 레이어를 선택하세요.')
    changed = 0
    for doc in docs:
        delta = {layer.key: bool(visible) for layer in doc.layers()
                 if layer_name_key(layer.name) in selected and layer.visible != bool(visible)}
        doc.apply_snapshot(delta)
        changed += len(delta)
    return changed


def apply_group(doc, group, visible):
    if group not in GROUP_NAMES or not doc.loaded:
        raise DrawingError('유효한 레이어 그룹을 선택하세요.')
    delta = {layer.key: bool(visible) for layer in group_layers(doc.layers()).get(group, ())
             if not layer.locked and layer.visible != bool(visible)}
    doc.apply_snapshot(delta)
    return len(delta)


def parse_page_range(page_range):
    if (not isinstance(page_range, str) or len(page_range) > 24
            or not re.fullmatch(r'\s*\d+\s*(?:-\s*\d+\s*)?', page_range)):
        raise DrawingError('페이지 범위는 1 또는 1-5 형태로 입력하세요.')
    values = [int(value) for value in page_range.split('-')]
    start, end = values[0], values[-1]
    if not 1 <= start <= end or end-start+1 > MAX_JOBS:
        raise DrawingError('페이지 범위는 양의 정수이며 최대 1,000페이지여야 합니다.')
    return start, end


def page_indices(doc, scope, page_range=''):
    if scope == 'current':
        return (doc.page_index,)
    if scope == 'all':
        if doc.pages > MAX_JOBS:
            raise DrawingError('한 번에 최대 1,000개 출력 작업을 지원합니다.')
        return tuple(range(doc.pages))
    if scope != 'range':
        raise DrawingError('지원하지 않는 페이지 범위 설정입니다.')
    start, end = parse_page_range(page_range)
    if not 1 <= start <= end <= doc.pages or end-start+1 > MAX_JOBS:
        raise DrawingError(f'{doc.path.name}: 페이지 범위가 유효하지 않습니다. (1~{doc.pages})')
    return tuple(range(start-1, end))


def _isolated_snapshot(layers, selected):
    # A selected locked layer must already be visible; no unselected visible
    # locked content may be emitted under the label of an isolated layer.
    for layer in layers:
        if layer.locked and layer.visible != (layer.key in selected):
            raise DrawingError('잠긴 레이어가 있어 요청한 단독 분리 상태를 만들 수 없습니다.')
    return {layer.key: layer.key in selected for layer in layers}


def _variants(doc, mode, groups, rules):
    if mode == 'current':
        yield '', doc.states()
        return
    layers = doc.layers()
    if mode == 'layers':
        for i, layer in enumerate(layers, 1):
            if layer.visible and not layer.locked:
                yield f'L{i:04d}_{layer.name}', _isolated_snapshot(layers, {layer.key})
    elif mode == 'groups':
        grouped = group_layers(layers)
        for group in groups:
            members = grouped.get(group, ())
            # Explicitly refuse missing groups on any selected drawing to avoid
            # a partial plan being mistaken for a complete export set.
            if not members:
                raise DrawingError(f'{doc.path.name}: {group} 그룹이 없습니다.')
            yield group, _isolated_snapshot(layers, {layer.key for layer in members})
    elif mode == 'rules':
        index = _index(layers)
        for rule in rules:
            if rule.kind != doc.kind:
                raise DrawingError(f'{doc.path.name}: {rule.name} 규칙의 도면 형식이 다릅니다.')
            selected = set()
            for name, visible in rule.layers:
                matches = index.get(layer_name_key(name), ())
                if len(matches) != 1 or matches[0].locked:
                    raise DrawingError(f'{doc.path.name}: {rule.name} 규칙의 이름 누락·중복·잠김 ({name})')
                if visible:
                    selected.add(matches[0].key)
            if not selected:
                raise DrawingError(f'{rule.name}: 켜진 레이어가 없습니다.')
            # Explicit strict mode: unspecified layers are OFF, not inherited.
            yield rule.name, _isolated_snapshot(layers, selected)
    else:
        raise DrawingError('지원하지 않는 추출 방식입니다.')


def _safe_label(value, limit):
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:limit].rstrip(' .')
    return label or '도면'


def plan_advanced_exports(docs, folder, options, *, mode='current', scope='current',
                          page_range='', groups=(), rules=()):
    """Plan everything before starting worker. Never change GUI/source state."""
    opts = options.checked()
    if opts.crop_margins and mode != 'current':
        raise DrawingError('레이어 분리 추출에는 자동 여백 제거를 적용할 수 없습니다.')
    root = Path(folder).expanduser().resolve()
    if not root.is_dir() or not docs or any(not doc.loaded for doc in docs):
        raise DrawingError('저장 폴더와 분석 완료된 도면을 선택하세요.')
    if mode == 'groups' and (not groups or not set(groups) <= set(GROUP_NAMES)):
        raise DrawingError('추출할 레이어 그룹을 선택하세요.')
    if mode == 'rules' and not rules:
        raise DrawingError('추출할 저장 규칙을 선택하세요.')
    reserved = {p.name.casefold() for p in root.iterdir()}
    result, entries = [], 0
    next_number = {}
    for doc in docs:
        signature = planned_source(doc)
        from .vector_export import check_vector_source
        check_vector_source(doc.kind, opts, signature[2])
        if opts.region is not None and doc.kind != 'pdf':
            raise DrawingError('지정 영역 추출은 PDF만 지원합니다.')
        base = _safe_label(doc.path.stem, 90)
        pages = page_indices(doc, scope, page_range)
        before = len(result)
        for label, snapshot in _variants(doc, mode, groups, rules):
            entries += len(snapshot)*len(pages)
            if len(result)+len(pages) > MAX_JOBS or entries > MAX_STATE_ENTRIES:
                raise DrawingError('출력 계획의 규모가 너무 큽니다. 도면 또는 레이어 선택을 줄이세요.')
            safe_suffix = '_' + _safe_label(label, 65) if label else ''
            for page in pages:
                stem = f'{base}_p{page+1:04d}{safe_suffix}' + ('_영역' if opts.region else '')
                key = stem.casefold()
                number = next_number.get(key, 1)
                while True:
                    suffix = '' if number == 1 else f'_{number}'
                    name = f'{stem}{suffix}.{opts.fmt}'
                    if name.casefold() not in reserved:
                        reserved.add(name.casefold())
                        next_number[key] = number + 1
                        break
                    number += 1
                result.append(ExportJob(str(doc.path), dict(snapshot), page, str(root/name), signature))
        if len(result) == before:
            raise DrawingError(f'{doc.path.name}: 추출할 레이어가 없습니다.')
    return result
