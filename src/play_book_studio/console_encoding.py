"""Console encoding helpers for local and container CLI entrypoints."""

from __future__ import annotations

import os
import sys


def force_utf8_stdio() -> None:
    """Keep Python console output UTF-8 even when Windows code pages differ."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
