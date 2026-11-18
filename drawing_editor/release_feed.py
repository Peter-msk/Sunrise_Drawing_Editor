"""Product-owned public metadata; no execution or replacement of remote files."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

APP_VERSION = '1.0.0'
APP_ID = 'sunrise_drawing_editor'
ROOT = 'https://raw.githubusercontent.com/Peter-msk/Sunrise_Drawing_Editor/main/'
RELEASES = 'https://github.com/Peter-msk/Sunrise_Drawing_Editor/releases'
_LIMIT = 65536


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected metadata redirect')


def fetch_text(name):
    if name not in ('latest.json', 'notice.txt'):
        raise ValueError('Unknown metadata')
    request = Request(ROOT + name, headers={'User-Agent': 'Sunrise-Drawing-Editor/' + APP_VERSION})
    with build_opener(_NoRedirect()).open(request, timeout=5) as response:
        body = response.read(_LIMIT + 1)
    if len(body) > _LIMIT:
        raise ValueError('Metadata too large')
    return body.decode('utf-8-sig')


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})', value):
        raise ValueError('Invalid numeric version')
    return tuple(map(int, value.split('.')))


@dataclass(frozen=True)
class Release:
    version: str
    page: str
    sha256: str
    size: int


def parse_release(text, current=APP_VERSION):
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('app_id') != APP_ID:
        raise ValueError('Unexpected product metadata')
    if data.get('platform') != 'windows-x64' or data.get('package_kind') != 'onefile_exe':
        raise ValueError('Unexpected distribution')
    version = data.get('latest_version')
    newer = version_tuple(version) > version_tuple(current)
    enabled = data.get('update_endpoint_configured')
    if type(enabled) is not bool:
        raise ValueError('Invalid update flag')
    if not newer or not enabled:
        return None
    page = RELEASES + '/tag/v' + version
    expected_download = RELEASES + '/download/v' + version + '/Sunrise%20Drawing%20Editor.exe'
    digest = data.get('sha256')
    size = data.get('file_size_bytes')
    if (data.get('official_release') is not True or data.get('authenticode_required') is not True
            or data.get('release_url') != page or data.get('download_url') != expected_download
            or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or type(size) is not int or not 1 <= size <= 2_000_000_000):
        raise ValueError('Invalid release metadata')
    return Release(version, page, digest, size)


def notice_id(text):
    return hashlib.sha256(text.strip().encode('utf-8')).hexdigest()
