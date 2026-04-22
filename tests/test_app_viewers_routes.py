from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from _support_app_viewers import AppViewersTestSupport


def _bind_surface_tests(*prefixes: str):
    def _matches(name: str) -> bool:
        return any(name.startswith(prefix) for prefix in prefixes)

    return {
        name: value
        for name, value in vars(AppViewersTestSupport).items()
        if not name.startswith("__") and (not name.startswith("test_") or _matches(name))
    }


class TestAppViewerRoutes(unittest.TestCase):
    pass


for _name, _value in _bind_surface_tests(
    "test_viewer_document_",
    "test_viewer_source_meta_",
    "test_canonicalize_viewer_path",
    "test_viewer_path_local_raw_html_fallback",
).items():
    setattr(TestAppViewerRoutes, _name, _value)
