"""User-approved Windows Onefile update. Not enabled by default.

Only a fully verified release can be started as the temporary replacement helper.
The existing executable and a rollback copy remain intact until the final swap.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from .release_feed import (APP_VERSION, LOCAL_EXE_NAME, ASSET_NAME, version_tuple,
                           validated_download, fetch_text, parse_release)
from .control import check_policy, ensure_update_allowed
from .version_gate import verify_candidate_version
from .update_policy import STAGE, STARTUP_PENDING

EXE_NAME = LOCAL_EXE_NAME
STAGE_PREFIX = '.sunrise-update-'
CHUNK = 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}')


class UpdateError(RuntimeError):
    pass


def check_update_url(url, initial):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443) or parts.fragment):
        raise UpdateError('허용되지 않은 업데이트 URL')
    # The first request is pinned to the product; GitHub may redirect release
    # assets to its dedicated HTTPS binary delivery domains.
    if url == initial:
        return
    if parts.hostname not in ('release-assets.githubusercontent.com',
                              'objects.githubusercontent.com',
                              'github-releases.githubusercontent.com'):
        raise UpdateError('허용되지 않은 다운로드 리디렉션')


class _ReleaseRedirect(HTTPRedirectHandler):
    def __init__(self, initial):
        self.initial = initial

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_update_url(newurl, self.initial)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()


def stream_verified(source, destination, size, sha256, *, cancelled=None, progress=None):
    h = hashlib.sha256()
    written = 0
    deadline = time.monotonic() + 900
    while True:
        if cancelled and cancelled():
            raise UpdateError('업데이트 다운로드 취소')
        if time.monotonic() > deadline:
            raise UpdateError('업데이트 다운로드 시간 초과')
        block = source.read(CHUNK)
        if not block:
            break
        written += len(block)
        if written > size:
            raise UpdateError('업데이트 파일 크기 불일치')
        destination.write(block)
        h.update(block)
        if progress:
            progress(written, size)
    if written != size or h.hexdigest() != sha256:
        raise UpdateError('업데이트 파일 크기 또는 SHA-256 불일치')


def verify_release_authority(previous, expected, sha256, size):
    """Recheck official HTTPS metadata before the helper replaces the old EXE."""
    try:
        release = parse_release(fetch_text('latest.json'), current=previous)
    except (ValueError, OSError) as exc:
        raise UpdateError('공식 업데이트 정보 재확인 실패') from exc
    if (release is None or not release.automatic or release.version != expected
            or release.sha256 != sha256 or release.size != size):
        raise UpdateError('공식 업데이트 정보와 신규 EXE 불일치')


def report_update_error(exc, stage='업데이트 검증'):
    """Expose useful diagnostics without signed download URL/query or local document paths."""
    if isinstance(exc, UpdateError):
        detail = str(exc)
    elif isinstance(exc, HTTPError):
        detail = f'다운로드 HTTP {exc.code}'
    elif isinstance(exc, URLError):
        detail = '다운로드 네트워크 또는 TLS 연결 실패'
    elif isinstance(exc, subprocess.TimeoutExpired):
        detail = '신규 EXE 검사 시간 초과'
    elif isinstance(exc, OSError):
        detail = f'{type(exc).__name__} (OS 오류 {getattr(exc, "winerror", None) or exc.errno})'
    elif isinstance(exc, ValueError):
        detail = '신규 EXE 버전 또는 메타데이터 검증 실패'
    else:
        detail = type(exc).__name__
    message = (stage + ': ' + detail).replace('\r', ' ').replace('\n', ' ')[:500]
    try:
        location = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache')
        folder = location / 'Sunrise Group' / 'DrawingEditor'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'update-last-error.txt').write_text(message + '\n', encoding='utf-8')
    except OSError:
        pass
    return message


def _independent_env():
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def _target(path):
    target = Path(path).resolve(strict=True)
    if target.name.casefold() not in (EXE_NAME.casefold(), ASSET_NAME.casefold()) or not target.is_file():
        raise UpdateError('공식 Onefile 파일명 또는 위치가 아닙니다. 수동 교체가 필요합니다.')
    return target


def stage_update(release, *, cancelled=None, progress=None):
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise UpdateError('Windows Onefile에서만 자동 업데이트할 수 있습니다.')
    if not release.automatic or version_tuple(release.version) <= version_tuple(APP_VERSION):
        raise UpdateError('자동 업데이트가 승인되지 않았습니다.')
    try:
        expected = validated_download(release.version, release.download)
    except ValueError as exc:
        raise UpdateError('잘못된 업데이트 다운로드 주소') from exc
    if (not isinstance(release.sha256, str) or not HEX.fullmatch(release.sha256)
            or type(release.size) is not int or not 1 <= release.size <= 2_000_000_000):
        raise UpdateError('잘못된 업데이트 메타데이터')
    ensure_update_allowed(check_policy(), release.version)
    target = _target(sys.executable)
    old_sha = digest(target)
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=target.parent))
    candidate = stage / 'candidate.exe'
    try:
        request = Request(expected, headers={'User-Agent': 'Sunrise-Drawing-Editor/' + APP_VERSION,
                                             'Accept-Encoding': 'identity'})
        with build_opener(_ReleaseRedirect(expected)).open(request, timeout=15) as response:
            check_update_url(response.geturl(), expected)
            with candidate.open('xb') as out:
                stream_verified(response, out, release.size, release.sha256,
                                cancelled=cancelled, progress=progress)
                out.flush()
                os.fsync(out.fileno())
        if cancelled and cancelled():
            raise UpdateError('업데이트 취소')
        # Release authenticity follows the pinned HTTPS feed and exact byte digest.
        # Windows public-CA trust is not a product update condition.
        try:
            verify_candidate_version(candidate, release.version, _independent_env())
        except subprocess.TimeoutExpired as exc:
            raise UpdateError('신규 EXE 버전 응답 시간 초과') from exc
        except ValueError as exc:
            raise UpdateError('신규 EXE 버전 응답 불일치') from exc
        if cancelled and cancelled():
            raise UpdateError('업데이트 취소')
        try:
            smoke = subprocess.run([str(candidate), '--self-test'], env=_independent_env(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=120,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise UpdateError('신규 EXE 사전 실행검사 시간 초과') from exc
        if smoke.returncode:
            raise UpdateError('신규 EXE 사전 실행검사 실패')
        if cancelled and cancelled():
            raise UpdateError('업데이트 취소')
        if digest(candidate) != release.sha256:
            raise UpdateError('검증 이후 EXE가 변경되었습니다.')
        return (str(candidate), str(target), old_sha, release.sha256, release.version)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def discard_prepared(prepared):
    """Remove only an unused candidate directory created by this workflow."""
    if not prepared:
        return
    candidate, target, *_ = prepared
    candidate = Path(candidate)
    if (candidate.name == 'candidate.exe' and candidate.parent.name.startswith(STAGE_PREFIX)
            and candidate.parent.parent == Path(target).parent
            and not (candidate.parent / 'rollback.exe').exists()):
        shutil.rmtree(candidate.parent, ignore_errors=True)


def launch_update(prepared):
    candidate, target, old_sha, new_sha, version = prepared
    if digest(candidate) != new_sha or digest(target) != old_sha:
        raise UpdateError('검증 이후 실행파일 변경')
    subprocess.Popen([candidate, '--apply-onefile-update', target, old_sha, new_sha,
                      version, APP_VERSION, str(os.getpid())],
                     env=_independent_env(), cwd=str(Path(target).parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)


def _wait_for_exit(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    open_process = kernel.OpenProcess
    open_process.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    open_process.restype = w.HANDLE
    wait = kernel.WaitForSingleObject
    wait.argtypes = [w.HANDLE, w.DWORD]
    wait.restype = w.DWORD
    close = kernel.CloseHandle
    close.argtypes = [w.HANDLE]
    close.restype = w.BOOL
    handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        if ctypes.get_last_error() == 87:  # already exited
            return
        raise UpdateError('기존 프로세스 종료를 확인할 수 없습니다.')
    try:
        if wait(handle, 120000) != 0:
            raise UpdateError('기존 프로그램 종료 대기 실패')
    finally:
        close(handle)


def apply_update(args):
    """Runs only from the verified temporary new EXE, before the GUI starts."""
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False) or len(args) != 6:
        raise UpdateError('잘못된 업데이트 실행 경로')
    path, old_sha, new_sha, expected, previous, pid = args
    if (not HEX.fullmatch(old_sha) or not HEX.fullmatch(new_sha)
            or expected != APP_VERSION or version_tuple(APP_VERSION) <= version_tuple(previous)):
        raise UpdateError('버전 또는 무결성 조건 불일치')
    target = _target(path)
    candidate = Path(sys.executable).resolve(strict=True)
    stage = candidate.parent
    if (candidate.name != 'candidate.exe' or stage.parent != target.parent
            or not STAGE.fullmatch(stage.name) or set(stage.iterdir()) != {candidate}):
        raise UpdateError('허용되지 않은 업데이트 임시 경로')
    if digest(candidate) != new_sha or digest(target) != old_sha:
        raise UpdateError('실행파일 해시 불일치')
    verify_release_authority(previous, expected, new_sha, candidate.stat().st_size)
    _wait_for_exit(int(pid))
    ensure_update_allowed(check_policy(), expected)
    if digest(target) != old_sha:
        raise UpdateError('종료 이후 기존 EXE가 변경되었습니다.')
    backup, replacement = stage / 'rollback.exe', stage / 'replacement.exe'
    # Copy before swapping, never overwrite the previous rollback.
    for dst, source in ((backup, target), (replacement, candidate)):
        with source.open('rb') as src, dst.open('xb') as out:
            shutil.copyfileobj(src, out, CHUNK)
            out.flush()
            os.fsync(out.fileno())
    if digest(backup) != old_sha or digest(replacement) != new_sha:
        raise UpdateError('교체 전 복사본 무결성 오류')
    pending = stage / STARTUP_PENDING
    with pending.open('x', encoding='ascii') as stream:
        stream.write(new_sha)
    _replace_with_retry(replacement, target)
    try:
        if digest(target) != new_sha:
            raise UpdateError('교체 후 EXE 무결성 오류')
        process = subprocess.Popen([str(target), '--update-completed', str(stage), old_sha, new_sha],
                         cwd=str(target.parent), env=_independent_env(), close_fds=True)
    except BaseException:
        _rollback(backup, target, old_sha, new_sha)
        raise
    # Do not confuse Popen success with GUI startup. A running but unresponsive
    # process must NOT be killed or overwritten; leave its backup for recovery.
    deadline = time.monotonic() + 120
    while pending.exists():
        if process.poll() is not None:
            if not pending.exists():  # acknowledge/exit race
                break
            _rollback(backup, target, old_sha, new_sha)
            raise UpdateError('신규 EXE가 정상 시작 전에 종료되어 이전 버전으로 복원했습니다.')
        if time.monotonic() >= deadline:
            raise UpdateError('신규 EXE 시작 확인 시간 초과; 롤백 파일 보존')
        time.sleep(.25)
    return 0


def _replace_with_retry(source, target, timeout=60):
    # A PyInstaller parent bootloader can outlive its Python process.
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise UpdateError('실행파일 잠금으로 교체하지 못했습니다. 복구 파일 보존') from exc
            time.sleep(.5)


def _rollback(backup, target, old_sha, new_sha):
    if digest(backup) != old_sha or digest(target) != new_sha:
        raise UpdateError('롤백 무결성 조건 불일치; 복구 파일 보존')
    _replace_with_retry(backup, target)



def helper_main(args):
    try:
        return apply_update(args)
    except Exception as exc:
        if sys.platform != 'win32':
            return 1
        ctypes.windll.user32.MessageBoxW(None, report_update_error(exc, 'EXE 교체') + '\n기존 EXE 또는 임시 롤백 파일을 보존했습니다.',
                                         'Sunrise Drawing Editor 업데이트 실패', 0x10)
        return 1
