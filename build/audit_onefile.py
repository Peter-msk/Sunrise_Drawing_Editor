"""Read-only top-level PyInstaller Onefile inventory (build-time tool only)."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys


MIB = 1024 * 1024


def classify(name, typecode):
    path = name.replace('\\', '/').lower()
    leaf = path.rsplit('/', 1)[-1]
    parts = path.split('/')
    if typecode == 'z' or leaf.endswith('.pyz'):
        return 'Python PYZ', ''
    if leaf == 'opengl32sw.dll':
        return 'Qt / PySide6', 'Software OpenGL fallback; test remote/low-GPU PCs'
    if (any(p in parts for p in ('pyside6', 'shiboken6')) or
            leaf.startswith(('qt6', 'pyside6', 'shiboken6'))):
        if 'translations' in parts and leaf.endswith('.qm'):
            return 'Qt / PySide6', 'Unused-language translation review'
        if 'imageformats' in parts and leaf not in ('qjpeg.dll', 'qsvg.dll', 'qico.dll'):
            return 'Qt / PySide6', 'Image format plugin; test supported image/DXF inputs'
        if leaf.startswith(('qt6webengine', 'qt6pdf', 'qt6multimedia', 'qt6sql')):
            return 'Qt / PySide6', 'Optional Qt module; verify dependency graph'
        return 'Qt / PySide6', ''
    if any(p in parts for p in ('fitz', 'pymupdf', 'pymupdf.libs')) or 'mupdf' in leaf:
        return 'MuPDF / PyMuPDF', ''
    if any(p in parts for p in ('numpy', 'numpy.libs')) or leaf.startswith(('libopenblas', 'libscipy_openblas')):
        return 'NumPy / BLAS', ''
    if any(p in parts for p in ('ezdxf', 'fonttools', 'pyparsing')):
        return 'CAD / fonts', ''
    if any(p in parts for p in ('pil', 'pillow.libs')):
        return 'Pillow', ''
    if leaf.startswith(('python3', 'vcruntime', 'msvcp', 'ucrtbase', 'api-ms-win-')) or leaf == 'base_library.zip':
        return 'Python / runtime', ''
    if leaf.startswith(('libssl', 'libcrypto', '_ssl', '_hashlib')):
        return 'TLS / crypto', ''
    if parts[0] == 'assets':
        return 'App assets', ''
    return 'Other / unassigned', ''


def inventory(toc, file_size):
    rows = []
    groups = defaultdict(lambda: {'packed_bytes': 0, 'unpacked_bytes': 0, 'entries': 0})
    ranges = []
    for name, (offset, packed, unpacked, compressed, typecode) in toc.items():
        if (min(offset, packed, unpacked) < 0 or offset + packed > file_size
                or compressed not in (0, 1)):
            raise ValueError('Invalid archive entry: ' + name)
        if packed:
            ranges.append((offset, offset + packed))
        group, candidate = classify(name, typecode)
        row = dict(name=name, group=group, packed_bytes=packed, unpacked_bytes=unpacked,
                   typecode=typecode, compressed=bool(compressed), review_candidate=candidate)
        rows.append(row)
        tally = groups[group]
        tally['packed_bytes'] += packed
        tally['unpacked_bytes'] += unpacked
        tally['entries'] += 1
    end = 0
    for start, stop in sorted(ranges):
        if start < end:
            raise ValueError('Overlapping archive entries')
        end = stop
    if not rows:
        raise ValueError('Empty archive')
    rows.sort(key=lambda r: (-r['packed_bytes'], r['name']))
    total = sum(r['packed_bytes'] for r in rows)
    if total > file_size:
        raise ValueError('Archive payload exceeds file size')
    candidates = [r for r in rows if r['review_candidate']]
    return dict(schema_version=1, exe_bytes=file_size, packed_payload_bytes=total,
                other_bytes=file_size-total,
                groups=dict(sorted(groups.items(), key=lambda kv: (-kv[1]['packed_bytes'], kv[0]))),
                entries=rows, review_candidate_bytes=sum(r['packed_bytes'] for r in candidates),
                review_candidates=[r['name'] for r in candidates],
                limitations=['Top-level CArchive only; PYZ is counted once, not split by module.',
                             'Other bytes include bootloader, TOC, signing data and padding.',
                             'Unpacked bytes describe archive entries, not peak RAM or exact disk use.',
                             'Candidate bytes are NOT verified removable bytes or guaranteed savings.'])


def audit(exe):
    from PyInstaller import __version__ as reader_version
    from PyInstaller.archive.readers import CArchiveReader
    before = exe.stat()
    with exe.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Expected a Windows PE executable')
        stream.seek(0)
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    reader = CArchiveReader(str(exe))
    result = inventory(reader.toc, before.st_size)
    if __package__:
        from .pyz_policy import audit_pyz
    else:
        from pyz_policy import audit_pyz
    try:
        result['pyz'] = audit_pyz(reader)
    except Exception as exc:
        result['pyz'] = {'status': 'ERROR', 'reason': str(exc)}
    result['limitations'][0] = 'PYZ detail is nested; do not add it to top-level totals.'
    after = exe.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Executable changed during audit')
    result.update(exe_name=exe.name, sha256=sha, reader_version=reader_version)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        exe = args.exe.resolve(strict=True)
        report = args.report.resolve()
        if report.suffix.lower() != '.json' or report == exe or (report.exists() and report.samefile(exe)):
            raise ValueError('Report must be a separate JSON file')
        result = audit(exe)
        report.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidentally replacing earlier evidence.
        with report.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        print(f"EXE: {result['exe_bytes']/MIB:.2f} MiB | SHA-256: {result['sha256']}")
        for group, data in result['groups'].items():
            print(f"{data['packed_bytes']/MIB:8.2f} MiB  {group}")
        print(f"{result['other_bytes']/MIB:8.2f} MiB  non-entry bytes")
        print('\nTop 30 packed entries:')
        for row in result['entries'][:30]:
            print(f"{row['packed_bytes']/MIB:8.2f} MiB  {row['name']}")
        print(f"Review candidate total (not savings): {result['review_candidate_bytes']/MIB:.2f} MiB")
        print('Report:', report)
        return 0
    except Exception as exc:
        print('[ERROR]', str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
