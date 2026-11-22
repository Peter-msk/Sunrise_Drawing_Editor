"""Publish only signed and smoke-tested staging EXE. No PowerShell."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

try:
    from build.sign_release import embedded_signer_certificates, signer_cn
    from build.release_metadata import publish_bundle
    from build.pe_version import expected_version
    from build.functional_gate import read_functional_qa
except ModuleNotFoundError:
    from sign_release import embedded_signer_certificates, signer_cn
    from release_metadata import publish_bundle
    from pe_version import expected_version
    from functional_gate import read_functional_qa


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
    if smoke.get('version_resource') != expected_version():
        raise RuntimeError('Post-sign Windows version resource attestation missing or mismatched.')
    functional_qa = read_functional_qa(exe.parent / 'FUNCTIONAL_QA.json', sha256, version=expected_version()['strings']['ProductVersion'], extraction_only=True)
    from cryptography.hazmat.primitives import hashes
    thumbprint = report.get('certificate_thumbprint_sha1')
    if not any(signer_cn(cert) == 'Sunrise Group' and
               (not thumbprint or cert.fingerprint(hashes.SHA1()).hex().upper() == thumbprint)
               for cert in embedded_signer_certificates(exe)):
        raise RuntimeError('Sunrise Group embedded signing certificate does not match report.')
    publish_bundle(exe, destination, sha256, report, digest, functional_qa=functional_qa)
    print('[PASS] Published signed onefile:', destination / exe.name)
    print('[PASS] SHA256:', sha256)
    print('[INFO] Signer trust:', report['trust'])
    print('[PASS] Product release metadata:', destination / 'release-metadata')


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
