from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.models import SourceManifestEntry
from play_book_studio.ingestion.source_first import source_mirror_root
from play_book_studio.ingestion.source_repo_hydration import hydrate_source_repo_artifacts


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class SourceRepoHydrationTests(unittest.TestCase):
    def test_hydrate_source_repo_artifacts_fetches_root_and_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            entry = SourceManifestEntry(
                book_slug="hosted_control_planes",
                title="Hosted Control Planes",
                source_kind="source-first",
                source_url="https://github.com/openshift/openshift-docs/blob/enterprise-4.20/hosted_control_planes/index.adoc",
            )
            payloads = {
                "https://raw.githubusercontent.com/openshift/openshift-docs/enterprise-4.20/hosted_control_planes/index.adoc": (
                    "include::_attributes/common-attributes.adoc[]\n"
                    "include::modules/hosted-control-planes-overview.adoc[leveloffset=+1]\n"
                    "= Hosted Control Planes\n"
                ),
                "https://raw.githubusercontent.com/openshift/openshift-docs/enterprise-4.20/_attributes/common-attributes.adoc": (
                    ":product-title: OpenShift Container Platform\n"
                ),
                "https://raw.githubusercontent.com/openshift/openshift-docs/enterprise-4.20/hosted_control_planes/modules/hosted-control-planes-overview.adoc": (
                    "== Overview\n본문\n"
                ),
            }

            def fake_get(url: str, **_: object) -> _FakeResponse:
                if url not in payloads:
                    raise requests.HTTPError(f"unexpected url: {url}")
                return _FakeResponse(payloads[url])

            with patch(
                "play_book_studio.ingestion.source_repo_hydration.requests.get",
                side_effect=fake_get,
            ):
                paths = hydrate_source_repo_artifacts(settings, entry)

            mirror_root = source_mirror_root(settings.root_dir)
            self.assertEqual(
                [(mirror_root / "hosted_control_planes/index.adoc").resolve()],
                paths,
            )
            self.assertTrue((mirror_root / "hosted_control_planes/index.adoc").exists())
            self.assertTrue((mirror_root / "_attributes/common-attributes.adoc").exists())
            self.assertTrue(
                (mirror_root / "hosted_control_planes/modules/hosted-control-planes-overview.adoc").exists()
            )


if __name__ == "__main__":
    unittest.main()
