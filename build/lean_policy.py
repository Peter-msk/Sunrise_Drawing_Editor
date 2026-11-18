"""R22 optional Qt plugin families; native import guard before removing DLLs."""
from pathlib import Path, PureWindowsPath

LEAN_EXCLUDES = ('pandas', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
                 'PySide6.QtQuickControls2', 'PySide6.QtQml', 'PySide6.QtPdf',
                 'PySide6.QtPdfWidgets', 'PySide6.QtVirtualKeyboard')
QT_OPTIONAL = frozenset({'qt6quick.dll', 'qt6qml.dll', 'qt6qmlmodels.dll',
                         'qt6qmlmeta.dll', 'qt6qmlworkerscript.dll', 'qt6pdf.dll',
                         'qt6virtualkeyboard.dll'})
QT_PLUGINS = frozenset({'plugins/imageformats/qpdf.dll',
                        'plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll'})


def normalized(value):
    return str(value).replace('\\', '/').lower()


def optional_qt(entry):
    dest, src, kind = entry
    path = normalized(dest)
    parts = path.split('/')
    source = PureWindowsPath(str(src))
    if (kind != 'BINARY' or parts[0] != 'pyside6' or
            'pyside6' not in [p.lower() for p in source.parts] or
            source.name.lower() != parts[-1]):
        return False
    rel = '/'.join(parts[1:])
    return rel in QT_OPTIONAL or rel in QT_PLUGINS


def pe_imports(path):
    import pefile  # Windows PyInstaller dependency, build-time only.
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[0, 1, 13])
        names = set()
        for attr in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT'):
            for item in getattr(pe, attr, ()):
                names.add(item.dll.decode('ascii').lower())
        for item in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', ()):
            if item.forwarder:
                module = item.forwarder.decode('ascii').rsplit('.', 1)[0].lower()
                names.add(module if module.endswith('.dll') else module + '.dll')
        return names
    finally:
        pe.close()


def prune_qt(entries, imports=pe_imports):
    entries = list(entries)
    proposed = {i for i, entry in enumerate(entries) if optional_qt(entry)}
    pending = set(proposed)
    if not pending:
        return entries, [], []
    dependencies = {}
    # Keep unknown files, and fail the experimental build if a native import
    # table cannot be read. No guessing on missing dependency information.
    for i, (dest, src, kind) in enumerate(entries):
        if kind in ('BINARY', 'EXTENSION') and normalized(dest).endswith(('.dll', '.pyd', '.exe')):
            dependencies[i] = {normalized(n).rsplit('/', 1)[-1] for n in imports(src)}
    while pending:
        required = set().union(*(deps for i, deps in dependencies.items() if i not in pending))
        blocked = {i for i in pending if normalized(entries[i][0]).rsplit('/', 1)[-1] in required}
        if not blocked:
            break
        pending -= blocked
    kept = [entry for i, entry in enumerate(entries) if i not in pending]
    removed = [{'name': entries[i][0], 'kind': entries[i][2],
                'reason': 'Optional Qt family; no retained static PE import',
                'source_bytes': Path(entries[i][1]).stat().st_size} for i in sorted(pending)]
    blocked = [entries[i][0] for i in sorted(proposed - pending)]
    return kept, removed, blocked
