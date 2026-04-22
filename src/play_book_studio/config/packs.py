"""제품 정체성과 pack 정체성을 정의하는 곳.

Play Book Studio는 앱 자체이고, "OpenShift 4.20 core"는 현재 선택된
지식 pack이다. 이 분리가 나중의 multi-pack 확장의 기준이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass


APP_ID = "play-book-studio"
APP_LABEL = "Play Book Studio"
DEFAULT_PRODUCT_KEY = "openshift"
DEFAULT_PRODUCT_LABEL = "OpenShift"
DEFAULT_DOCS_PRODUCT_SLUG = "openshift_container_platform"
DEFAULT_DOCS_LANGUAGE = "ko"
DEFAULT_OCP_VERSION = "4.20"
DEFAULT_QDRANT_COLLECTION = "openshift_docs"
DEFAULT_SOURCE_KIND = "source-first"
GLOBAL_SOURCE_CATALOG_NAME = "ocp_multiversion_html_single_catalog.json"
SUPPORTED_OCP_CORE_VERSIONS = ("4.20", "4.18", "4.16")
SUPPORTED_SOURCE_CRAWLER_VERSIONS = ("4.16", "4.17", "4.18", "4.19", "4.20", "4.21")
SUPPORTED_SOURCE_CRAWLER_LANGUAGES = ("ko", "en")
SUPPORTED_SOURCE_CRAWLER_KINDS = (DEFAULT_SOURCE_KIND, "html-single")


@dataclass(frozen=True, slots=True)
class PackConfig:
    """런타임이 사용하는 게시 문서 pack 하나를 설명한다."""

    app_id: str
    app_label: str
    product_key: str
    product_label: str
    docs_product_slug: str
    pack_id: str
    pack_label: str
    version: str
    language: str
    source_collection: str
    docs_index_url_template: str
    book_url_template: str
    viewer_path_template: str
    qdrant_collection: str

    @property
    def viewer_path_prefix(self) -> str:
        return f"/docs/ocp/{self.version}/{self.language}/"

    @property
    def manifest_prefix(self) -> str:
        return f"ocp_{self.language}_{self.version.replace('.', '_')}"

    @property
    def source_catalog_name(self) -> str:
        return f"{self.manifest_prefix}_html_single.json"

    @property
    def approved_manifest_name(self) -> str:
        return f"{self.manifest_prefix}_approved_ko.json"

    @property
    def translated_manifest_name(self) -> str:
        return f"{self.manifest_prefix}_translated_ko_draft.json"

    @property
    def corpus_working_manifest_name(self) -> str:
        return f"{self.manifest_prefix}_corpus_working_set.json"

    def payload(self) -> dict[str, str]:
        return {
            "source_collection": self.source_collection,
            "pack_id": self.pack_id,
            "pack_label": self.pack_label,
            "inferred_product": self.product_key,
            "inferred_version": self.version,
        }


def resolve_ocp_core_pack(
    *,
    version: str = DEFAULT_OCP_VERSION,
    language: str = DEFAULT_DOCS_LANGUAGE,
) -> PackConfig:
    # 아직은 의도적으로 OCP 우선 구조지만, 나머지 코드는 버전/경로 literal을
    # 직접 박지 말고 여기서 pack 메타데이터를 읽어야 한다.
    version = (version or DEFAULT_OCP_VERSION).strip()
    language = (language or DEFAULT_DOCS_LANGUAGE).strip()
    version_token = version.replace(".", "-")
    docs_index_url_template = (
        "https://docs.redhat.com/{lang}/documentation/"
        f"{DEFAULT_DOCS_PRODUCT_SLUG}/{{version}}/"
    )
    book_url_template = (
        "https://docs.redhat.com/{lang}/documentation/"
        f"{DEFAULT_DOCS_PRODUCT_SLUG}/{{version}}/html-single/{{slug}}/index"
    )
    viewer_path_template = "/docs/ocp/{version}/{lang}/{slug}/index.html"
    return PackConfig(
        app_id=APP_ID,
        app_label=APP_LABEL,
        product_key=DEFAULT_PRODUCT_KEY,
        product_label=DEFAULT_PRODUCT_LABEL,
        docs_product_slug=DEFAULT_DOCS_PRODUCT_SLUG,
        pack_id=f"openshift-{version_token}-core",
        pack_label=f"OpenShift {version}",
        version=version,
        language=language,
        source_collection="core",
        docs_index_url_template=docs_index_url_template,
        book_url_template=book_url_template,
        viewer_path_template=viewer_path_template,
        qdrant_collection=DEFAULT_QDRANT_COLLECTION,
    )


def default_core_pack() -> PackConfig:
    return resolve_ocp_core_pack()


def supported_core_packs(*, language: str = DEFAULT_DOCS_LANGUAGE) -> tuple[PackConfig, ...]:
    return tuple(
        resolve_ocp_core_pack(version=version, language=language)
        for version in SUPPORTED_OCP_CORE_VERSIONS
    )


def source_crawler_packs(
    *,
    versions: tuple[str, ...] = SUPPORTED_SOURCE_CRAWLER_VERSIONS,
    languages: tuple[str, ...] = SUPPORTED_SOURCE_CRAWLER_LANGUAGES,
) -> tuple[PackConfig, ...]:
    """수집 파이프라인이 미리 계획할 OCP version/language scope를 반환한다.

    runtime UI는 현재 선택 pack만 다루지만, crawler는 제품보다 더 넓은 버전 범위를
    준비해야 하므로 별도 helper로 분리한다.
    """

    ordered: list[PackConfig] = []
    for version in versions:
        for language in languages:
            ordered.append(resolve_ocp_core_pack(version=version, language=language))
    return tuple(ordered)
