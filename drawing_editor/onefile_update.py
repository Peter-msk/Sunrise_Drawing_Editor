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
from uuid import UUID

from .release_feed import APP_VERSION, RELEASES, version_tuple

EXE_NAME = 'Sunrise Drawing Editor.exe'
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


class _TrustFile(ctypes.Structure):
    _fields_ = [('cbStruct', w.DWORD), ('pcwszFilePath', w.LPCWSTR),
                ('hFile', w.HANDLE), ('pgKnownSubject', ctypes.c_void_p)]


class _TrustData(ctypes.Structure):
    _fields_ = [('cbStruct', w.DWORD), ('pPolicyCallbackData', ctypes.c_void_p),
                ('pSIPClientData', ctypes.c_void_p), ('dwUIChoice', w.DWORD),
                ('fdwRevocationChecks', w.DWORD), ('dwUnionChoice', w.DWORD),
                ('pFile', ctypes.POINTER(_TrustFile)), ('dwStateAction', w.DWORD),
                ('hWVTStateData', w.HANDLE), ('pwszURLReference', w.LPWSTR),
                ('dwProvFlags', w.DWORD), ('dwUIContext', w.DWORD),
                ('pSignatureSettings', ctypes.c_void_p)]


class _CertContext(ctypes.Structure):
    _fields_ = [('dwCertEncodingType', w.DWORD), ('pbCertEncoded', ctypes.c_void_p),
                ('cbCertEncoded', w.DWORD), ('pCertInfo', ctypes.c_void_p),
                ('hCertStore', w.HANDLE)]


class _ProviderCertHead(ctypes.Structure):
    _fields_ = [('cbStruct', w.DWORD), ('pCert', ctypes.POINTER(_CertContext))]


def verified_signer(path):
    """Return fingerprint of the actual WinVerifyTrust-validated leaf signer.

    Untrusted self-signed builds, revoked/unverifiable signatures, and renamed
    publishers fail closed. Never install a certificate or disable revocation.
    """
    if sys.platform != 'win32':
        raise UpdateError('Windows Authenticode 검증 환경이 아닙니다.')
    dll = ctypes.WinDLL('wintrust', use_last_error=True)
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(UUID('00aac56b-cd44-11d0-8cc2-00c04fc295ee').bytes_le)
    info = _TrustFile()
    info.cbStruct = ctypes.sizeof(info)
    info.pcwszFilePath = str(Path(path).resolve(strict=True))
    data = _TrustData()
    data.cbStruct = ctypes.sizeof(data)
    data.dwUIChoice = 2  # WTD_UI_NONE
    data.fdwRevocationChecks = 1  # WTD_REVOKE_WHOLECHAIN
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(info)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    data.dwProvFlags = 0x80  # WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT
    verify = dll.WinVerifyTrust
    verify.argtypes = [w.HWND, ctypes.c_void_p, ctypes.POINTER(_TrustData)]
    verify.restype = w.LONG
    try:
        status = verify(None, ctypes.byref(guid), ctypes.byref(data))
        if status != 0:
            raise UpdateError(f'Authenticode 신뢰 검증 실패: 0x{status & 0xffffffff:08x}')
        provider = dll.WTHelperProvDataFromStateData
        provider.argtypes = [w.HANDLE]
        provider.restype = ctypes.c_void_p
        signer = dll.WTHelperGetProvSignerFromChain
        signer.argtypes = [ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD]
        signer.restype = ctypes.c_void_p
        cert = dll.WTHelperGetProvCertFromChain
        cert.argtypes = [ctypes.c_void_p, w.DWORD]
        cert.restype = ctypes.POINTER(_ProviderCertHead)
        prov = provider(data.hWVTStateData)
        sg = signer(prov, 0, False, 0) if prov else None
        cp = cert(sg, 0) if sg else None
        if not cp or not cp.contents.pCert:
            raise UpdateError('실제 검증된 서명자 인증서가 없습니다.')
        ctx = cp.contents.pCert
        name_fn = crypt.CertGetNameStringW
        name_fn.argtypes = [ctypes.POINTER(_CertContext), w.DWORD, w.DWORD,
                            ctypes.c_void_p, w.LPWSTR, w.DWORD]
        name_fn.restype = w.DWORD
        n = name_fn(ctx, 4, 0, None, None, 0)  # CERT_NAME_SIMPLE_DISPLAY_TYPE
        if not 1 < n < 1024:
            raise UpdateError('유효한 게시자 이름이 없습니다.')
        name = ctypes.create_unicode_buffer(n)
        name_fn(ctx, 4, 0, None, name, n)
        if name.value != 'Sunrise Group':
            raise UpdateError('공식 Sunrise Group 게시자와 일치하지 않습니다.')
        leaf = ctx.contents
        if not leaf.pbCertEncoded or not 1 <= leaf.cbCertEncoded <= 65536:
            raise UpdateError('서명자 인증서 형식 오류')
        return hashlib.sha256(ctypes.string_at(leaf.pbCertEncoded, leaf.cbCertEncoded)).hexdigest()
    finally:
        data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
        verify(None, ctypes.byref(guid), ctypes.byref(data))


def _independent_env():
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def _target(path):
    target = Path(path).resolve(strict=True)
    if target.name.casefold() != EXE_NAME.casefold() or not target.is_file():
        raise UpdateError('공식 Onefile 파일명 또는 위치가 아닙니다. 수동 교체가 필요합니다.')
    return target


def stage_update(release, *, cancelled=None, progress=None):
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise UpdateError('Windows Onefile에서만 자동 업데이트할 수 있습니다.')
    if not release.automatic or version_tuple(release.version) <= version_tuple(APP_VERSION):
        raise UpdateError('자동 업데이트가 승인되지 않았습니다.')
    expected = RELEASES + '/download/v' + release.version + '/Sunrise%20Drawing%20Editor.exe'
    if release.download != expected or not HEX.fullmatch(release.sha256):
        raise UpdateError('잘못된 업데이트 메타데이터')
    target = _target(sys.executable)
    current_signer = verified_signer(target)
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
        if verified_signer(candidate) != current_signer:
            raise UpdateError('기존 EXE와 새 EXE의 검증된 서명 인증서가 다릅니다.')
        if cancelled and cancelled():
            raise UpdateError('업데이트 취소')
        smoke = subprocess.run([str(candidate), '--self-test'], env=_independent_env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=120,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
            or not stage.name.startswith(STAGE_PREFIX)):
        raise UpdateError('허용되지 않은 업데이트 임시 경로')
    if digest(candidate) != new_sha or digest(target) != old_sha:
        raise UpdateError('실행파일 해시 불일치')
    if verified_signer(candidate) != verified_signer(target):
        raise UpdateError('서명자 일치 검증 실패')
    _wait_for_exit(int(pid))
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
    # The PyInstaller parent bootloader can outlive its Python GUI process.
    deadline = time.monotonic() + 60
    while True:
        try:
            os.replace(replacement, target)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise UpdateError('기존 EXE가 잠겨 있어 교체하지 않았습니다.')
            time.sleep(.5)
    try:
        if digest(target) != new_sha:
            raise UpdateError('교체 후 EXE 무결성 오류')
        subprocess.Popen([str(target)], cwd=str(target.parent), env=_independent_env(),
                         close_fds=True)
    except BaseException:
        os.replace(backup, target)
        raise
    # Keep rollback until the user verifies the new version. The helper itself
    # is running from stage, so Windows may not allow removing that folder yet.
    return 0


def helper_main(args):
    try:
        return apply_update(args)
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc) + '\n기존 EXE 또는 임시 롤백 파일을 보존했습니다.',
                                         'Sunrise Drawing Editor 업데이트 실패', 0x10)
        return 1
