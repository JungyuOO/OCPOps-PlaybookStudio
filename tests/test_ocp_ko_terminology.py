from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.canonical.ocp_ko_terminology import (
    normalize_ocp_ko_terminology,
    ocp_ko_terminology_prompt,
)


class OcpKoTerminologyTests(unittest.TestCase):
    def test_prompt_contains_core_official_translation_terms(self) -> None:
        prompt = ocp_ko_terminology_prompt()

        self.assertIn("BuildConfig -> BuildConfig", prompt)
        self.assertIn("Pipeline build strategy -> 파이프라인 빌드 전략", prompt)
        self.assertIn("Kubernetes -> 쿠버네티스(Kubernetes)", prompt)
        self.assertIn("Service Mesh -> 서비스 메시", prompt)

    def test_normalization_repairs_common_product_name_variants(self) -> None:
        normalized = normalize_ocp_ko_terminology(
            "오픈시프트 컨테이너 플랫폼의 호스팅 제어 평면은 쿠버네티스 Kubernetes와 연동됩니다."
        )

        self.assertIn("OpenShift Container Platform", normalized)
        self.assertIn("호스팅된 컨트롤 플레인", normalized)
        self.assertIn("쿠버네티스(Kubernetes)", normalized)

    def test_normalization_repairs_official_book_title_terms(self) -> None:
        normalized = normalize_ocp_ko_terminology(
            "Service Mesh / Virtualization / Machine configuration / "
            "Migration Toolkit for Containers"
        )

        self.assertIn("서비스 메시", normalized)
        self.assertIn("가상화", normalized)
        self.assertIn("머신 구성", normalized)
        self.assertIn("컨테이너용 Migration Toolkit", normalized)

    def test_normalization_repairs_cyrillic_translation_contamination(self) -> None:
        normalized = normalize_ocp_ko_terminology(
            "S2I는 이전에 빌드된 артефакt를 재사용하고 다мп된 데이터를 처리합니다."
        )

        self.assertIn("아티팩트", normalized)
        self.assertIn("덤프", normalized)


if __name__ == "__main__":
    unittest.main()
