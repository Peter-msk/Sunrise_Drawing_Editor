"""Optional external LibreCAD DWG->DXF adapter.

LibreCAD is a separate GPLv2 application. It is never vendored or bundled here;
users must install a build with DWGSUPPORT enabled. This adapter exchanges files
via documented CLI, without linking its code into the EXE.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import ezdxf


class ConverterError(RuntimeError):
    pass


def find_librecad() -> Path | None:
    options: list[Path] = []
    if os.environ.get('SUNRISE_LIBRECAD_EXE'):
        options.append(Path(os.environ['SUNRISE_LIBRECAD_EXE']).expanduser())
    for env_name in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(env_name):
            options.append(Path(os.environ[env_name]) / 'LibreCAD' / 'LibreCAD.exe')
    for command in ('LibreCAD.exe', 'librecad'):
        located = shutil.which(command)
        if located:
            options.append(Path(located))
    return next((p.resolve() for p in options if p.is_file()), None)


def read_dwg_with_librecad(source: Path, *, timeout: int = 600, exe: Path | None = None):
    tool = exe if exe is not None else find_librecad()
    if tool is None or not tool.is_file():
        raise ConverterError('LibreCAD를 찾지 못했습니다. DWGSUPPORT 지원 LibreCAD 또는 ODA File Converter가 필요합니다.')
    with tempfile.TemporaryDirectory(prefix='sunrise-dwg-') as directory:
        output = Path(directory) / 'converted.dxf'
        args = [str(tool), 'dwg2dxf', '-o', str(output), str(source)]
        try:
            result = subprocess.run(args, cwd=str(source.parent), shell=False,
                                    capture_output=True, text=True, errors='replace',
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ConverterError(f'LibreCAD 변환 제한시간({timeout}초) 초과') from exc
        except OSError as exc:
            raise ConverterError(f'LibreCAD 실행 불가: {exc}') from exc
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            details = (result.stderr or result.stdout or '').strip()[-500:]
            raise ConverterError('LibreCAD DWG 변환 실패. DWGSUPPORT 빌드 여부를 확인하세요.' +
                                 (f' 세부: {details}' if details else ''))
        try:
            return ezdxf.readfile(output)
        except (OSError, ValueError, ezdxf.DXFError) as exc:
            raise ConverterError(f'LibreCAD에서 변환된 DXF를 읽지 못했습니다: {exc}') from exc
