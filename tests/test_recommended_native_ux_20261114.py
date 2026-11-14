"""Desktop Qt UX contracts derived from repository recommendation review.

GitHub lists of web UI frameworks are inspiration, NOT runtime dependencies.
These source contracts require no Qt installation; real Windows visual/a11y
inspection remains a separate release gate.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT / "drawing_editor" / "window.py").read_text(encoding="utf-8")
TREE = ast.parse(WINDOW)
DRAWING_WINDOW = next(
    obj for obj in TREE.body if isinstance(obj, ast.ClassDef) and
    obj.name == "DrawingWindow"
)


def method_text(name: str) -> str:
    node = next(obj for obj in DRAWING_WINDOW.body
                if isinstance(obj, ast.FunctionDef) and obj.name == name)
    return ast.get_source_segment(WINDOW, node)


class RecommendedNativeUXContracts(unittest.TestCase):
    def test_all_shorthand_sensitive_actions_keep_meaningful_accessible_names(self):
        source = method_text("_build_ui")
        labels = (
            "도면 목록 전체 선택", "도면 선택 모두 해제",
            "현재 도면 전체 레이어 켜기", "현재 도면 전체 레이어 끄기",
            "저장된 레이어 규칙 선택", "현재 레이어 규칙 저장",
            "선택 도면에 레이어 규칙 적용", "선택한 레이어 규칙 삭제",
        )
        for label in labels:
            with self.subTest(label=label):
                self.assertIn(repr(label), source)
        self.assertIn("control.setAccessibleName(name)", source)
        self.assertIn("control.setAccessibleDescription(explanation)", source)

    def test_shorthand_layout_preserves_full_accessibility(self):
        ui = method_text("_apply_responsive_layout")
        for short in ("'전체'", "'해제'", "'켜기'", "'끄기'", "'적용'"):
            self.assertIn(short, ui)
        self.assertNotIn("setAccessibleName(", ui)
        build = method_text("_build_ui")
        self.assertLess(
            build.index("control.setAccessibleName(name)"),
            build.index("self._apply_responsive_layout(self.width())"),
        )

    def test_elided_drawing_label_keeps_full_accessible_text(self):
        label = next(obj for obj in TREE.body if isinstance(obj, ast.ClassDef)
                     and obj.name == "ElidedLabel")
        method = next(obj for obj in label.body if isinstance(obj, ast.FunctionDef)
                      and obj.name == "setText")
        source = ast.get_source_segment(WINDOW, method)
        self.assertIn("self.setToolTip(self._complete_text)", source)
        self.assertIn("self.setAccessibleName(self._complete_text)", source)
        self.assertIn("self._update_elision()", source)

    def test_progress_meter_has_accessible_purpose_and_real_values(self):
        source = method_text("_build_ui")
        self.assertIn("self.progress.setAccessibleName('이미지 추출 진행률')", source)
        self.assertIn("self.progress.setAccessibleDescription(", source)
        self.assertIn("self.progress.setTextVisible(False)", source)
        self.assertIn("self.progress.setValue(", method_text("_batch_progress"))
        self.assertIn("self.progress.setValue(", method_text("_progress"))

    def test_recommendations_do_not_add_web_backend_or_webview_runtime(self):
        # Ignore comments: the existing requirements file documents that Qt\n        # WebEngine must NOT be installed, so a substring search is misleading.\n        requirements = "\\n".join(\n            line for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().splitlines()\n            if line.strip() and not line.lstrip().startswith("#")\n        )
        for web_only in ("react", "tailwind", "bootstrap", "supabase",
                         "strapi", "pocketbase", "electron", "webengine"):
            self.assertNotIn(web_only, requirements)
        self.assertIn("pyside6-essentials", requirements)
        # Preserve Qt-native keyboard navigation and existing local drop path.
        self.assertIn("QWidget.setTabOrder(before, after)", WINDOW)
        self.assertIn("url.isLocalFile()", WINDOW)
        self.assertIn("self.file_list.filesDropped.connect(self.add_files)", WINDOW)


if __name__ == "__main__":
    unittest.main()
