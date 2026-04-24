from __future__ import annotations

import sys
from pathlib import Path


def _prepend_local_src() -> None:
    root = Path(__file__).resolve().parent
    src_dir = root / "src"
    if not src_dir.is_dir():
        return
    src_path = str(src_dir)
    if src_path in sys.path:
        sys.path.remove(src_path)
    sys.path.insert(0, src_path)


_prepend_local_src()
