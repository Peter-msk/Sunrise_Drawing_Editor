"""Experimental Nuitka Onefile entry; not an official updater target."""
import sys
from drawing_editor.runtime_packaging import configure_nuitka_candidate

if __name__ == '__main__':
    try:
        __compiled__
    except NameError:
        raise SystemExit('This entry requires Nuitka Onefile compilation')
    configure_nuitka_candidate(sys.argv[0])
    if sys.argv[1:2] == ['--apply-onefile-update']:
        raise SystemExit(2)
    from main import main
    raise SystemExit(main())
