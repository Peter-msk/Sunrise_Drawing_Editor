"""Read-only registered drawing diagnostics and portable extraction profiles."""
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from .batch import layer_name_key, planned_source
from .core import DrawingError, OutputOptions
from .layer_tools import classify, GROUP_NAMES, parse_page_range

PROFILE_LIMIT = 64 * 1024


def structure_report(doc):
    return _structure_report(doc, doc.layers())


def _structure_report(doc, layers):
    signature = planned_source(doc)
    counts = Counter(classify(layer.name) for layer in layers)
    names = Counter(layer_name_key(layer.name) for layer in layers)
    return {'name': doc.path.name, 'format': doc.kind.upper(), 'bytes': signature[2],
            'pages': doc.pages, 'layers': len(layers), 'visible': sum(l.visible for l in layers),
            'locked': sum(l.locked for l in layers), 'groups': dict(counts),
            'duplicate_names': sorted(k for k, n in names.items() if k and n > 1),
            'unnamed': names.get('', 0)}


def checked_profile(data):
    if not isinstance(data, dict) or set(data) != {'schema_version','options','mode','scope','page_range','groups','rules'} or type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise DrawingError('지원하지 않는 작업 프로파일 형식입니다.')
    try:
        raw_options = data['options']
        if not isinstance(raw_options, dict):
            raise ValueError('출력 설정 항목 불일치')
        # Existing extraction-only profiles remain usable; never silently drop a color override.
        if 'cad_color' in raw_options:
            if raw_options['cad_color'] is not None:
                raise ValueError('레이어 색상 변경 기능이 제거되었습니다. 색상 지정 없는 프로파일을 사용하세요.')
            raw_options = {k: v for k, v in raw_options.items() if k != 'cad_color'}
            data = dict(data, options=raw_options)
        if set(raw_options) != set(asdict(OutputOptions())):
            raise ValueError('출력 설정 항목 불일치')
        opts = OutputOptions(**data['options']).checked()
        if data['mode'] not in ('current','layers','groups','rules') or data['scope'] not in ('current','all','range'):
            raise ValueError('추출 방식/페이지 범위 오류')
        if not isinstance(data['page_range'], str) or len(data['page_range']) > 24:
            raise ValueError('페이지 범위 오류')
        if data['scope'] == 'range':
            parse_page_range(data['page_range'])
        for key, maximum, minimum in (('width', 2_147_483_647, 1), ('height', 2_147_483_647, 1), ('dpi', 2400, 36)):
            value = data['options'][key]
            if value is not None and (type(value) is not int or not minimum <= value <= maximum):
                raise ValueError('출력 크기 또는 DPI 오류')
        # JSON permits escaped lone surrogates; reject before Qt/UTF-8 I/O.
        json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        for k in ('groups','rules'):
            v = data[k]
            if not isinstance(v,list) or len(v)>100 or any(not isinstance(x,str) or not 1<=len(x)<=60 for x in v) or len(set(v))!=len(v):
                raise ValueError('선택 목록 오류')
        if not set(data['groups']) <= set(GROUP_NAMES):
            raise ValueError('그룹 이름 오류')
        if (data['mode']=='groups') != bool(data['groups']) or (data['mode']=='rules') != bool(data['rules']):
            raise ValueError('추출 방식과 목록 불일치')
        return opts, data
    except (TypeError, ValueError, KeyError) as exc:
        raise DrawingError(f'작업 프로파일 오류: {exc}') from exc


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'중복 JSON 항목: {key}')
        result[key] = value
    return result


def load_profile(path):
    try:
        with open(path,'rb') as stream:
            raw = stream.read(PROFILE_LIMIT+1)
        if len(raw)>PROFILE_LIMIT:
            raise DrawingError('프로파일 파일이 너무 큽니다.')
        return checked_profile(json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_json_object))
    except (OSError, ValueError, RecursionError) as exc:
        raise DrawingError(f'프로파일 읽기 실패: {exc}') from exc


def save_profile(path, options, *, mode, scope, page_range, groups, rules):
    payload = dict(schema_version=1, options=asdict(options), mode=mode, scope=scope,
                   page_range=page_range, groups=list(groups), rules=list(rules))
    checked_profile(payload)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    if len(raw)>PROFILE_LIMIT:
        raise DrawingError('프로파일 파일이 너무 큽니다.')
    requested = Path(path).expanduser()
    target = requested.parent.resolve() / requested.name
    if target.suffix.casefold() != '.sdeprofile':
        raise DrawingError('프로파일 확장자는 .sdeprofile이어야 합니다.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.profile-',delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary,target)  # do not overwrite any source or existing profile
    except OSError as exc:
        raise DrawingError(f'프로파일 저장 실패 (기존 파일 보호): {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inspect_source(snapshot, cancelled=None):
    """Bounded optional source diagnostics, separate from registered UI state."""
    from .core import verify_source
    path, _, page, signature = snapshot
    path = Path(path)
    def check():
        if cancelled and cancelled(): raise DrawingError('원본 분석이 취소되었습니다.')
        verify_source(path,signature)
    if signature is None:
        raise DrawingError('등록된 원본 식별정보가 없습니다. 도면을 다시 불러오세요.')
    check()
    kind=path.suffix.casefold()
    if kind == '.pdf':
        import fitz
        with fitz.open(path) as pdf:
            if pdf.needs_pass or not 0 <= page < pdf.page_count:
                raise DrawingError('PDF 페이지를 읽을 수 없습니다.')
            p=pdf[page]
            result={'파일':path.name,'페이지':page+1,'전체 페이지':pdf.page_count,
                    '표시 페이지 크기 (pt)':[p.rect.width,p.rect.height], '페이지 회전 (도)':p.rotation,
                    '이미지 리소스 항목':len(p.get_images(full=True)), '글꼴 리소스 항목':len(p.get_fonts(full=True)),
                    'OCG 레이어':len(pdf.get_ocgs() or {}),
                    '주의':'리소스 항목은 실제 표시 객체 수가 아닙니다. CRS, 실제 축척, 벡터 객체 수는 판정하지 않습니다.'}
    elif kind == '.dxf':
        import ezdxf
        if signature[2] > 16*1024*1024:
            from .cad_catalog import inspect_large_ascii_dxf
            result = inspect_large_ascii_dxf(path, check=check, size=signature[2])
            check(); return result
        cad=ezdxf.readfile(str(path));check()
        types, layer_counts=Counter(),Counter()
        for i,entity in enumerate(cad.modelspace()):
            if i%256==0:check()
            types[entity.dxftype()]+=1
            layer_counts[str(entity.dxf.get('layer','0'))]+=1
        result={'파일':path.name,'DXF 버전':cad.dxfversion,'INSUNITS 코드':cad.header.get('$INSUNITS',0),
                '모델 공간 최상위 객체 수':sum(types.values()),'객체 유형별':dict(types),
                '레이어별 최상위 객체 수':dict(layer_counts),
                '주의':'블록 내부 객체·외부참조 확장 및 CRS 판정은 하지 않습니다. INSUNITS는 좌표체계가 아닙니다.'}
    else:
        raise DrawingError('원본 상세 분석은 PDF/DXF만 지원합니다.')
    check();return result
