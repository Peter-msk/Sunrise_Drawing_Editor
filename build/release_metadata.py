"""Build-only, product-owned release metadata. Never change the live feed."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/Peter-msk/Sunrise_Drawing_Editor'
NAME = 'Sunrise Drawing Editor.exe'
ASSET_NAME = 'Sunrise.Drawing.Editor.exe'


def build_metadata(exe, sha256, signature, *, root=ROOT):
    # Read the single product version constant without importing the GUI.
    source = (root / 'drawing_editor' / 'release_feed.py').read_text(encoding='utf-8')
    match = re.search(r"^APP_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'$", source, re.M)
    if not match:
        raise ValueError('Missing product version')
    version = match.group(1)
    live = json.loads((root / 'latest.json').read_text(encoding='utf-8-sig'))
    notice = (root / 'notice.txt').read_text(encoding='utf-8-sig').strip()
    if (live.get('schema_version') != 1 or live.get('app_id') != 'sunrise_drawing_editor'
            or live.get('latest_version') != version or not notice
            or exe.name != NAME or not re.fullmatch(r'[0-9a-f]{64}', sha256)
            or signature.get('sha256') != sha256 or exe.stat().st_size <= 0):
        raise ValueError('Release metadata input mismatch')
    data = dict(live)
    data.update(latest_version=version, source_version=version,
                download_file_name=ASSET_NAME, sha256=sha256, file_size_bytes=exe.stat().st_size,
                release_url=f'{REPO}/releases/tag/v{version}',
                download_url=f'{REPO}/releases/download/v{version}/{ASSET_NAME}',
                notice_url=f'https://raw.githubusercontent.com/Peter-msk/Sunrise_Drawing_Editor/main/notice.txt',
                publisher='Sunrise Group', authenticode_required=True,
                signature_trust=signature.get('trust', 'UNKNOWN'),
                signature_policy=live.get('signature_policy') if live.get('signature_policy') == 'GROUP_PINNED_INTERNAL_QA_PUBLIC_FEED_DISABLED' else 'GROUP_SIGNED_AT_BUILD_FEED_SHA256',
                group_certificate_pin_verified=signature.get('group_certificate_pin_verified') is True,
                group_certificate_sha256=signature.get('certificate_thumbprint_sha256') if signature.get('group_certificate_pin_verified') is True else None,
                official_release=False, update_endpoint_configured=False,
                automatic_update_available=False,
                release_notes=live.get('release_notes', ''))
    return {'latest.json': (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
            'notice.txt': (notice + '\n').encode('utf-8')}


def publish_bundle(exe, destination, sha256, signature, digest, *, functional_qa, smoke, root=ROOT):
    """Prepare every output first; replace EXE last, roll back sidecars on error."""
    import os
    import shutil
    import tempfile

    if smoke.get('sha256') != sha256 or smoke.get('passed') is not True:
        raise ValueError('Smoke evidence does not match the signed EXE')
    files = {'release-metadata/' + name: value for name, value in
             build_metadata(exe, sha256, signature, root=root).items()}
    files['SHA256.txt'] = f'{sha256}  {exe.name}\n'.encode('utf-8')
    files['SIGNATURE_STATUS.json'] = (json.dumps(dict(signature, windows_exe_smoke_pass=True),
                                                indent=2, ensure_ascii=True) + '\n').encode('ascii')
    files['SMOKE_STATUS.json'] = (json.dumps(smoke, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    files['FUNCTIONAL_QA.json'] = (json.dumps(functional_qa, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'release-metadata').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.publish-', dir=destination) as tmp:
        work = Path(tmp)
        staged_exe = work / exe.name
        shutil.copyfile(exe, staged_exe)
        if digest(staged_exe) != sha256:
            raise RuntimeError('Staged EXE / publish EXE hash mismatch.')
        for name, value in files.items():
            staged = work / 'new' / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(value)
            old = destination / name
            if old.exists():
                backup = work / 'old' / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, backup)
        # A previous final QA belongs to the previous EXE, not the new candidate.
        # Move it into the same transaction before replacing any sidecar.
        final_qa_name = 'V150_LOCAL_QA.json'
        final_qa = destination / final_qa_name
        replaced = []
        try:
            if final_qa.exists():
                backup = work / 'old' / final_qa_name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final_qa, backup)
                replaced.append(final_qa_name)
            for name in files:
                os.replace(work / 'new' / name, destination / name)
                replaced.append(name)
            os.replace(staged_exe, destination / exe.name)
        except OSError:
            for name in reversed(replaced):
                backup = work / 'old' / name
                if backup.exists():
                    os.replace(backup, destination / name)
                else:
                    (destination / name).unlink(missing_ok=True)
            raise
