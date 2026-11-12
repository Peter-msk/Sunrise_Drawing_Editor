"""Publish only signed and smoke-tested staging EXE. No PowerShell."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

try:
    from build.sign_release import embedded_signer_certificates, signer_cn
except ModuleNotFoundError:
    from sign_release import embedded_signer_certificates, signer_cn


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def publish(exe: Path, destination: Path) -> None:
    if not exe.is_file():
        raise RuntimeError('Staged EXE missing.')
    report_path = exe.parent / 'SIGNATURE_STATUS.json'
    if not report_path.is_file():
        raise RuntimeError('Signing report missing; unsigned output is forbidden.')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    sha256 = digest(exe)
    if sha256 != report['sha256']:
        raise RuntimeError('EXE changed after signing; aborting release.')
    smoke_path = exe.parent / 'SMOKE_STATUS.json'
    if not smoke_path.is_file():
        raise RuntimeError('Signed EXE smoke attestation is missing.')
    smoke = json.loads(smoke_path.read_text(encoding='utf-8'))
    if smoke.get('passed') is not True or smoke.get('sha256') != sha256:
        raise RuntimeError('Post-sign EXE smoke test did not match signed EXE hash.')
    from cryptography.hazmat.primitives import hashes
    thumbprint = report.get('certificate_thumbprint_sha1')
    if not any(signer_cn(cert) == 'Sunrise Group' and
               (not thumbprint or cert.fingerprint(hashes.SHA1()).hex().upper() == thumbprint)
               for cert in embedded_signer_certificates(exe)):
        raise RuntimeError('Sunrise Group embedded signing certificate does not match report.')
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / exe.name
    tmp = destination / (exe.name + '.tmp')
    try:
        shutil.copyfile(exe, tmp)
        if digest(tmp) != sha256:
            raise RuntimeError('Staged EXE / publish EXE hash mismatch.')
        os.replace(tmp, final)
        (destination / 'SHA256.txt').write_text(f'{sha256}  {exe.name}\n', encoding='utf-8')
        report['windows_exe_smoke_pass'] = True  # Only called after both smoke gates.
        (destination / 'SIGNATURE_STATUS.json').write_text(
            json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='ascii')
        print('[PASS] Published signed onefile:', final)
        print('[PASS] SHA256:', sha256)
        print('[INFO] Signer trust:', report['trust'])
    finally:
        if tmp.exists():
            tmp.unlink()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('exe', type=Path)
    p.add_argument('destination', type=Path)
    args = p.parse_args()
    try:
        publish(args.exe, args.destination)
    except Exception as exc:
        print('[ERROR]', str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
