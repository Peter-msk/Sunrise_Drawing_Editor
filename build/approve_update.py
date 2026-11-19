"""Windows release approval: produce a separate active feed, never edit live GitHub."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import os
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from drawing_editor.release_feed import (APP_VERSION, APP_ID, ASSET_NAME, RELEASES,
    _NoRedirect, release_download_urls, parse_release, version_tuple)
from drawing_editor.onefile_update import digest, verified_signer, _independent_env
from build.pe_version import read_version_resource, verify_version_resource


def release_record(version):
    version_tuple(version)
    url = 'https://api.github.com/repos/Peter-msk/Sunrise_Drawing_Editor/releases/tags/v' + version
    req = Request(url, headers={'User-Agent': 'Sunrise-Drawing-Editor-release-approval',
                               'Accept': 'application/vnd.github+json'})
    with build_opener(_NoRedirect()).open(req, timeout=20) as response:
        raw = response.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('Release response exceeds limit')
    return json.loads(raw)


def approved_metadata(data, release, *, version, old_version, sha, size):
    if version_tuple(old_version) >= version_tuple(version):
        raise ValueError('Previous version must be lower than target version')
    if (data.get('app_id') != APP_ID or data.get('latest_version') != version
            or data.get('sha256') != sha or data.get('file_size_bytes') != size
            or data.get('download_file_name') != ASSET_NAME
            or data.get('download_url') != release_download_urls(version)[0]):
        raise ValueError('Build metadata does not match the local signed EXE')
    if (release.get('tag_name') != 'v'+version or release.get('draft') is not False
            or release.get('prerelease') is not False):
        raise ValueError('Release is not a published stable version')
    assets = [a for a in release.get('assets', []) if a.get('name') == ASSET_NAME]
    if len(assets) != 1:
        raise ValueError('Expected exactly one canonical release asset')
    asset = assets[0]
    if (asset.get('state') != 'uploaded' or asset.get('size') != size
            or asset.get('digest') != 'sha256:'+sha
            or asset.get('browser_download_url') != release_download_urls(version)[0]):
        raise ValueError('Uploaded asset bytes/URL do not match local signed EXE')
    result = dict(data, update_endpoint_configured=True, official_release=True,
                  automatic_update_available=True, authenticode_required=True,
                  signature_trust='TRUSTED_BY_WINDOWS_POLICY')
    parsed = parse_release(json.dumps(result), current=old_version)
    if not parsed or not parsed.automatic or parsed.sha256 != sha:
        raise ValueError('Updater contract rejected approved release')
    return result


def approve(old, new, metadata, output):
    if sys.platform != 'win32':
        raise OSError('Approval requires actual Windows Authenticode validation')
    if output.resolve() == (ROOT / 'latest.json').resolve() or output.resolve() == metadata.resolve():
        raise ValueError('Write a separate approval output, not the live/build feed')
    old = old.resolve(strict=True); new = new.resolve(strict=True)
    if old == new:
        raise ValueError('Previous and target EXEs must be different')
    old_version = read_version_resource(old)['strings']['ProductVersion']
    verify_version_resource(new)
    if verified_signer(old) != verified_signer(new):
        raise ValueError('Previous and target EXEs do not have the same trusted leaf signer')
    old_sha, sha = digest(old), digest(new)
    for exe in (old, new):
        run = subprocess.run([str(exe), '--self-test'], env=_independent_env(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=120,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            raise ValueError('Signed EXE self-test failed')
    result = approved_metadata(json.loads(metadata.read_text(encoding='utf-8-sig')),
                               release_record(APP_VERSION), version=APP_VERSION,
                               old_version=old_version, sha=sha, size=new.stat().st_size)
    if digest(old) != old_sha or digest(new) != sha:
        raise ValueError('EXE changed during approval')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as f:
            temp = Path(f.name); json.dump(result, f, indent=2, ensure_ascii=False); f.write('\n')
        os.replace(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    print('[PASS] Active metadata generated:', output)
    print('[INFO] Before publishing feed, perform isolated Windows v1.0.0 -> v1.1.0 update/restart test.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('old', type=Path); p.add_argument('new', type=Path)
    p.add_argument('metadata', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args()
    try:
        approve(a.old, a.new, a.metadata, a.output)
    except Exception as exc:
        print('[ERROR]', str(exc), file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
