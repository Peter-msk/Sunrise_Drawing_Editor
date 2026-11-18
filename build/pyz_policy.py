"""R23: read-only nested archive accounting and explicit graph exclusions."""
from collections import defaultdict

PYZ_EXCLUDES = ('IPython', 'pytest', 'tkinter', 'PIL.ImageTk',
                'ezdxf.addons.drawing.pyqt', 'ezdxf.addons.drawing.qtviewer',
                'ezdxf.addons.drawing.matplotlib', 'ezdxf.addons.xqt')


def excluded(name):
    return any(name == root or name.startswith(root + '.') for root in PYZ_EXCLUDES)


def inventory_pyz(toc, size):
    if type(size) is not int or size <= 0 or not toc:
        raise ValueError('Invalid or empty PYZ')
    groups = defaultdict(lambda: {'packed_bytes': 0, 'entries': 0})
    rows, ranges = [], []
    for name, (kind, offset, length) in toc.items():
        if (not isinstance(name, str) or not name or type(kind) is not int or
                type(offset) is not int or type(length) is not int or
                offset < 0 or length < 0 or offset + length > size):
            raise ValueError('Invalid PYZ entry')
        if length:
            ranges.append((offset, offset + length))
        group = name.split('.')[0]
        rows.append({'name': name, 'kind': kind, 'packed_bytes': length,
                     'group': group, 'review_candidate': excluded(name)})
        groups[group]['packed_bytes'] += length
        groups[group]['entries'] += 1
    end = 0
    for start, stop in sorted(ranges):
        if start < end:
            raise ValueError('Overlapping PYZ entries')
        end = stop
    rows.sort(key=lambda r: (-r['packed_bytes'], r['name']))
    total = sum(r['packed_bytes'] for r in rows)
    return {'archive_bytes': size, 'module_packed_bytes': total,
            'overhead_bytes': size - total, 'module_count': len(rows),
            'groups': dict(sorted(groups.items(), key=lambda p: (-p[1]['packed_bytes'], p[0]))),
            'entries': rows}


def audit_pyz(reader):
    archives = [(name, entry) for name, entry in reader.toc.items() if entry[-1] == 'z']
    if len(archives) != 1:
        raise ValueError('Expected one embedded PYZ')
    name, (_, packed, unpacked, compressed, _) = archives[0]
    if compressed or packed != unpacked:
        raise ValueError('Unsupported compressed outer PYZ')
    result = inventory_pyz(reader.open_embedded_archive(name).toc, packed)
    return {'status': 'OK', 'name': name, **result}


def compare_pyz(before, after):
    if not before or not after or before.get('status') != 'OK' or after.get('status') != 'OK':
        return {'status': 'NOT AVAILABLE'}
    a = {r['name']: r['packed_bytes'] for r in before['entries']}
    b = {r['name']: r['packed_bytes'] for r in after['entries']}
    return {'status': 'OK', 'saved_archive_bytes': before['archive_bytes'] - after['archive_bytes'],
            'removed_modules': sorted(set(a) - set(b)), 'added_modules': sorted(set(b) - set(a)),
            'retained_exclusion_targets': sorted(n for n in b if excluded(n)),
            'removed_module_bytes': sum(a[n] for n in set(a) - set(b))}
