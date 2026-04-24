from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    src_dir = root / "src"
    sys.path.insert(0, str(src_dir))

    from play_book_studio.cli import main as cli_main

    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(main())
