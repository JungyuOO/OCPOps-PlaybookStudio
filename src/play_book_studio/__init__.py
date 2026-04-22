"""Play Book Studio 루트 패키지."""

import os

# Third-party imports may call python-dotenv during module import and mutate the
# process environment from the repo root .env. Disable that implicit behavior so
# settings stay driven by the harness/test environment only.
os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
