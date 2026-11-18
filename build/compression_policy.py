"""Opt-in UPX candidate policy, not an automatic compatibility claim."""
from pathlib import PureWindowsPath
import re


def upx_selection(binaries):
    """Only existing NumPy-owned BLAS DLLs are eligible; names shared by any
    noneligible file are excluded too. All other binaries stay uncompressed.
    """
    selected, blocked = set(), set()
    for dest, source, kind in binaries:
        path = PureWindowsPath(str(source))
        name = path.name.casefold()
        owned = any(p.casefold() == 'numpy.libs' for p in path.parts)
        if kind == 'BINARY' and owned and re.fullmatch(r'lib(?:scipy_)?openblas[^\\/]*\.dll', name):
            selected.add(name)
        else:
            blocked.add(name)
    selected -= blocked
    return sorted(selected), sorted(blocked)
