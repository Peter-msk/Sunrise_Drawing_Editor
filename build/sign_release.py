"""Sunrise Group signing by SignTool and Windows certificate store; no PowerShell.

- Reuse a code-signing certificate in the current user's My store.
- Otherwise create one LOCAL/TEST self-signed code-signing certificate and
  import it with certutil -user. No private key is put in the source ZIP.
- Optionally sign with a company-issued PFX supplied via environment variables.
- Do not claim a local self-signed identity is a publicly trusted publisher.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SUBJECT = 'Sunrise Group'


class SignError(RuntimeError):
    pass


def signer_cn(cert: x509.Certificate) -> str:
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return names[0].value if len(names) == 1 else ''


def is_code_signing(cert: x509.Certificate) -> bool:
    if signer_cn(cert) != SUBJECT:
        return False
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        return ExtendedKeyUsageOID.CODE_SIGNING in eku
    except x509.ExtensionNotFound:
        return False


def cert_current(cert: x509.Certificate) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    return not_before <= now < not_after


def find_signtool() -> Path:
    explicit = os.environ.get('SUNRISE_SIGNTOOL_PATH', '').strip('"')
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
        raise SignError(f'SUNRISE_SIGNTOOL_PATH is invalid: {candidate}')
    on_path = shutil.which('signtool.exe')
    if on_path:
        return Path(on_path)
    roots = [os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')]
    found = []
    for root in roots:
        if not root:
            continue
        for kits in ('10', '11', '8.1'):
            pattern = str(Path(root) / 'Windows Kits' / kits / 'bin' / '**' / 'x64' / 'signtool.exe')
            found.extend(Path(p) for p in glob.glob(pattern, recursive=True))
    if found:
        return sorted(found, key=lambda p: str(p).lower(), reverse=True)[0]
    raise SignError('SignTool not found. Install the Windows SDK Signing Tools (x64), '
                    'or set SUNRISE_SIGNTOOL_PATH. Unsigned EXE will NOT be published.')


def call(args: list[str], *, sensitive: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors='replace', check=False)
    if result.returncode != 0:
        name = Path(args[0]).name
        # Never log /p, PFX password, or subprocess command arguments.
        message = result.stdout.strip() if not sensitive else '(secret-bearing command failed; output hidden)'
        raise SignError(f'{name} failed (exit {result.returncode}): {message[-3000:]}')
    return result


def generate_local_certificate() -> tuple[bytes, bytes, x509.Certificate]:
    """Generate a one-time PFX for Windows user-store import; never bundle it."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SUBJECT)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=730))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    password = secrets.token_urlsafe(32).encode('ascii')
    pfx = pkcs12.serialize_key_and_certificates(
        name=b'Sunrise Group LOCAL TEST', key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password))
    return pfx, password, cert


def store_certificates() -> list[x509.Certificate]:
    if not hasattr(ssl, 'enum_certificates'):
        raise SignError('Windows certificate store API is unavailable.')
    result = []
    for data, encoding, _trust in ssl.enum_certificates('MY'):
        if encoding != 'x509_asn':
            continue
        try:
            cert = x509.load_der_x509_certificate(data)
            if is_code_signing(cert) and cert_current(cert):
                result.append(cert)
        except (ValueError, TypeError):
            continue
    result.sort(key=lambda c: c.not_valid_after_utc, reverse=True)
    return result


def make_cert_in_user_store() -> x509.Certificate:
    pfx, password, cert = generate_local_certificate()
    with tempfile.TemporaryDirectory(prefix='SunriseGroupSigning_') as temp:
        pfx_path = Path(temp) / 'sunrise_group_internal_test.pfx'
        pfx_path.write_bytes(pfx)
        # certutil is a native Windows CMD tool; no PowerShell and no root trust modification.
        call(['certutil.exe', '-user', '-p', password.decode('ascii'),
              '-importPFX', 'My', str(pfx_path), 'NoExport'], sensitive=True)
    print('[WARN] Created a user-store LOCAL/TEST code-signing certificate: CN=Sunrise Group')
    print('[WARN] This certificate is NOT a trusted public publisher; do NOT add to Trusted Root automatically.')
    return cert


def load_pfx_certificate(path: Path, password: str) -> x509.Certificate:
    if not path.is_file():
        raise SignError(f'External PFX does not exist: {path}')
    try:
        _key, cert, _chain = pkcs12.load_key_and_certificates(path.read_bytes(), password.encode('utf-8'))
    except Exception as exc:
        raise SignError('Could not open external PFX; check password and key.') from exc
    if cert is None or not is_code_signing(cert) or not cert_current(cert):
        raise SignError('PFX signer must have an unexpired CN=Sunrise Group CODE SIGNING certificate.')
    return cert


def embedded_signer_certificates(executable: Path) -> list[x509.Certificate]:
    """Read the embedded PE WIN_CERTIFICATE PKCS#7, not the Windows trust chain."""
    data = executable.read_bytes()
    if len(data) < 256 or data[:2] != b'MZ':
        raise SignError('Not a valid PE file (MZ header missing).')
    pe_off = struct.unpack_from('<I', data, 0x3c)[0]
    if pe_off + 256 >= len(data) or data[pe_off:pe_off + 4] != b'PE\0\0':
        raise SignError('Malformed PE header.')
    opt = pe_off + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    if magic not in (0x10b, 0x20b):
        raise SignError('Unsupported PE optional header.')
    directory = opt + (112 if magic == 0x20b else 96) + 8 * 4
    offset, size = struct.unpack_from('<II', data, directory)
    if offset == 0 or size < 16 or offset + size > len(data):
        raise SignError('PE has no embedded Authenticode certificate table.')
    certs = []
    end = offset + size
    while offset + 8 <= end:
        entry_size, _rev, cert_type = struct.unpack_from('<IHH', data, offset)
        if entry_size < 8 or offset + entry_size > end:
            raise SignError('Malformed WIN_CERTIFICATE entry.')
        if cert_type == 2:
            pkcs7_blob = data[offset + 8: offset + entry_size].rstrip(b'\0')
            try:
                certs.extend(pkcs7.load_der_pkcs7_certificates(pkcs7_blob))
            except ValueError as exc:
                raise SignError('Could not decode embedded Authenticode PKCS#7.') from exc
        offset += (entry_size + 7) & ~7
    if not certs:
        raise SignError('Embedded Authenticode certificate data was not found.')
    return certs


def sign_and_verify(exe: Path) -> dict:
    if os.name != 'nt':
        raise SignError('Signing requires Windows CMD with Windows SDK SignTool.')
    if not exe.is_file():
        raise SignError(f'EXE not found: {exe}')
    signtool = find_signtool()
    pfx_path = os.environ.get('SUNRISE_SIGN_PFX_PATH', '').strip('"')
    timestamp_url = os.environ.get('SUNRISE_TIMESTAMP_URL', '').strip()
    if pfx_path:
        password = os.environ.get('SUNRISE_SIGN_PFX_PASSWORD')
        if password is None:
            raise SignError('SUNRISE_SIGN_PFX_PASSWORD must be set for external PFX signing.')
        cert = load_pfx_certificate(Path(pfx_path), password)
        sign_args = [str(signtool), 'sign', '/fd', 'SHA256', '/f', pfx_path,
                     '/p', password, '/d', 'Sunrise Drawing Editor']
        mode = 'EXTERNAL_PFX'
    else:
        existing = store_certificates()
        cert = existing[0] if existing else make_cert_in_user_store()
        sign_args = [str(signtool), 'sign', '/fd', 'SHA256', '/s', 'My', '/sha1',
                     cert.fingerprint(hashes.SHA1()).hex().upper(),
                     '/d', 'Sunrise Drawing Editor']
        mode = 'WINDOWS_USER_CERT_STORE'
    if timestamp_url:
        sign_args.extend(['/tr', timestamp_url, '/td', 'SHA256'])
    sign_args.append(str(exe.resolve()))
    call(sign_args, sensitive=bool(pfx_path))
    expected = cert.fingerprint(hashes.SHA256())
    if not any(x.fingerprint(hashes.SHA256()) == expected
               for x in embedded_signer_certificates(exe)):
        raise SignError('Embedded EXE signer does not match the Sunrise Group certificate.')

    verify = subprocess.run([str(signtool), 'verify', '/pa', '/v', str(exe.resolve())],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors='replace', check=False)
    self_signed = cert.subject == cert.issuer
    if verify.returncode == 0:
        trust = 'TRUSTED_BY_WINDOWS_POLICY'
    elif self_signed:
        output = verify.stdout.lower()
        expected_untrusted = (
            '0x800b0109' in output or 'not trusted' in output or
            'untrusted root' in output or '신뢰할 수 없' in output or
            'trusted by the trust provider' in output
        )
        if not expected_untrusted:
            raise SignError('Self-signed signature verification failed for an unexpected reason: '
                            + verify.stdout[-1000:])
        trust = 'SELF_SIGNED_UNTRUSTED_TEST_ONLY'
    else:
        raise SignError('Authenticode verification FAILED: ' + verify.stdout[-1000:])
    if trust != 'TRUSTED_BY_WINDOWS_POLICY':
        print('[WARN] Signed EXE has a LOCAL/TEST untrusted certificate; Windows may display warnings.')
    result = {
        'file': exe.name,
        'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'subject': 'CN=Sunrise Group',
        'certificate_thumbprint_sha1': cert.fingerprint(hashes.SHA1()).hex().upper(),
        'mode': mode,
        'trust': trust,
        'timestamp_configured': bool(timestamp_url),
        'signtool_verify_returncode': verify.returncode,
        'embedded_certificate_match': True,
        'windows_exe_smoke_pass': False,
    }
    (exe.parent / 'SIGNATURE_STATUS.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='ascii')
    print(f'[PASS] Embedded Authenticode signer: CN=Sunrise Group; trust={trust}')
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', nargs='?', type=Path)
    parser.add_argument('--check-tools', action='store_true')
    args = parser.parse_args()
    try:
        if args.check_tools:
            if os.name != 'nt':
                raise SignError('SignTool is only available for Windows builds.')
            tool = find_signtool()
            if shutil.which('certutil.exe') is None and not os.environ.get('SUNRISE_SIGN_PFX_PATH'):
                raise SignError('Native Windows certutil.exe is not available.')
            print(f'[PASS] SignTool found: {tool}')
            return 0
        if args.exe is None:
            parser.error('EXE path required unless --check-tools is provided.')
        sign_and_verify(args.exe)
    except (OSError, SignError) as exc:
        print('[ERROR]', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
