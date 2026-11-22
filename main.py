from __future__ import annotations
import sys
from pathlib import Path


def main():
    # Candidate update version handshake must never initialize Qt or contact servers.
    if len(sys.argv) > 1 and sys.argv[1] == '--verify-update-version':
        from drawing_editor.release_feed import APP_VERSION
        from drawing_editor.version_gate import version_probe_exit
        return version_probe_exit(sys.argv, APP_VERSION)
    # Frozen onefile worker must bypass QApplication / QWidget construction.
    # The child retains its own MuPDF/ezdxf state and can be terminated safely.
    if len(sys.argv) > 1 and sys.argv[1] == '--apply-onefile-update':
        from drawing_editor.onefile_update import helper_main
        return helper_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == '--cad-worker':
        from drawing_editor.cad_worker import worker_main
        return worker_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == '--batch-worker':
        from drawing_editor.batch_worker import worker_main
        return worker_main(sys.argv[2:])

    cleanup = None
    if len(sys.argv) > 1 and sys.argv[1] == '--update-completed':
        if len(sys.argv) != 5 or not getattr(sys, 'frozen', False):
            return 2
        cleanup = tuple(sys.argv[2:])
        sys.argv = sys.argv[:1]
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon

    # Deterministic onefile smoke gate: initialize the packaged Qt / image/CAD
    # dependencies without starting the GUI event loop or contacting a server.
    if '--self-test' in sys.argv:
        from drawing_editor.window import DrawingWindow
        import fitz, ezdxf
        from PIL import Image
        app = QApplication([sys.argv[0]])
        assert (Path(__file__).parent / 'assets' / 'app.ico').is_file()
        window = DrawingWindow()
        from drawing_editor.release_ui import ReleaseFeedController
        window.release_feed = ReleaseFeedController(window, auto_check=False)
        window.close()
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName('Sunrise Drawing Editor')
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / 'app.ico')))
    from drawing_editor.control import check_policy
    policy = check_policy()
    if policy.blocks_entry or policy.requires_update:
        from drawing_editor.control_ui import startup_gate
        if not startup_gate(app, policy):
            return 0
    from drawing_editor.window import DrawingWindow
    window = DrawingWindow(sys.argv[1:])
    from drawing_editor.release_ui import ReleaseFeedController
    window.release_feed = ReleaseFeedController(window, auto_check=True)
    window.show()
    if cleanup is not None:
        from PySide6.QtCore import QTimer
        from threading import Thread
        from drawing_editor.update_policy import acknowledge_start, cleanup_after_start
        def cleanup_worker():
            if not (acknowledge_start(sys.executable, *cleanup) and
                    cleanup_after_start(sys.executable, *cleanup)):
                from drawing_editor.onefile_update import report_update_error, UpdateError
                report_update_error(UpdateError('이전 EXE 정리 미완료; 검증 가능한 롤백 파일 보존'),
                                    '업데이트 후 정리')

        def cleanup_started_update():
            if window.isVisible():
                Thread(target=cleanup_worker, daemon=True,
                       name='sunrise-update-cleanup').start()
        QTimer.singleShot(0, cleanup_started_update)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
