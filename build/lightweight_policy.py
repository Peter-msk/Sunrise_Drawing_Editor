"""Conservative PyInstaller TOC filtering for the Windows candidate only."""
from __future__ import annotations

import re
from pathlib import Path

PROFILES = ('safe', 'compact', 'lean')
OPTIONAL_IMAGES = frozenset({'qgif.dll', 'qicns.dll', 'qtga.dll', 'qtiff.dll',
                             'qwbmp.dll', 'qwebp.dll'})
TRANSLATION = re.compile(r'qt(?:base|declarative|multimedia|networkauth|quickcontrols2|serialport|webengine)?_([a-z]{2,3})(?:_[a-z0-9]+)*\.qm$')


def removal_reason(entry, profile):
    if profile not in PROFILES:
        raise ValueError('Unknown lightweight profile')
    dest, source, kind = entry
    parts = dest.replace('\\', '/').lower().split('/')
    src_parts = str(source).replace('\\', '/').lower().split('/')
    leaf = parts[-1]
    qt_owned = parts[0] == 'pyside6' and 'pyside6' in src_parts
    if qt_owned and kind == 'DATA' and 'translations' in parts:
        match = TRANSLATION.fullmatch(leaf)
        if match and match.group(1) not in ('ko', 'en'):
            return 'Qt translation outside Korean/English'
    if profile in ('compact', 'lean') and kind == 'BINARY' and 'pyside6' in src_parts:
        if qt_owned and 'imageformats' in parts and leaf in OPTIONAL_IMAGES:
            return 'Optional Qt image plugin; manual format/preview QA required'
        if leaf == 'opengl32sw.dll' and (qt_owned or len(parts) == 1):
            return 'Software OpenGL fallback; low-GPU/RDP QA required'
    return ''


def filter_toc(entries, profile):
    if profile not in PROFILES:
        raise ValueError('Unknown lightweight profile')
    kept, removed = [], []
    for entry in entries:
        reason = removal_reason(entry, profile)
        if not reason:
            kept.append(entry)
            continue
        dest, source, kind = entry
        removed.append({'name': dest, 'kind': kind, 'reason': reason,
                        'source_bytes': Path(source).stat().st_size})
    return kept, removed
