from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.customer_master_book import (
    validate_customer_master_book,
    write_customer_master_book,
)
from play_book_studio.app.customer_pack_read_boundary import (
    LOCAL_CUSTOMER_PACK_TENANT_ID,
    LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
    load_customer_pack_read_boundary,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.models import (
    CanonicalBookDraft,
    CustomerPackDraftRecord,
    DocSourceRequest,
)
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.service import evaluate_canonical_book_quality


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_section(draft_id: str, ordinal: int, heading: str, text: str) -> dict[str, object]:
    anchor = heading.lower().replace(" ", "-")
    return {
        "ordinal": ordinal,
        "section_key": f"{draft_id}:{anchor}",
        "heading": heading,
        "section_level": 1,
        "section_path": [heading],
        "section_path_label": heading,
        "anchor": anchor,
        "viewer_path": f"/playbooks/customer-packs/{draft_id}/index.html#{anchor}",
        "source_url": f"C:/private/{draft_id}.pptx",
        "text": text,
        "block_kinds": ["paragraph"],
        "semantic_role": "concept",
        "source_unit_kind": "slide",
        "source_unit_id": str(ordinal),
    }


def _write_source_book(
    root: Path,
    *,
    draft_id: str,
    title: str,
    fingerprint: str,
    sections: list[dict[str, object]],
) -> None:
    settings = load_settings(root)
    now = _utc_now()
    source_uri = f"C:/private/{title}.pptx"
    request = DocSourceRequest(
        source_type="pptx",
        uri=source_uri,
        title=title,
        language_hint="ko",
    )
    plan = CanonicalBookDraft(
        book_slug=title.lower().replace(" ", "-"),
        title=title,
        source_type="pptx",
        source_uri=source_uri,
        source_collection="uploaded",
        pack_id="custom-uploaded-custom",
        pack_label="User Custom Pack",
        inferred_product="openshift",
        inferred_version="customer",
        acquisition_uri=source_uri,
        capture_strategy="pptx_native",
        acquisition_step="test",
        normalization_step="test",
        derivation_step="test",
    )
    corpus_manifest_path = settings.customer_pack_corpus_dir / draft_id / "manifest.json"
    book_path = settings.customer_pack_books_dir / f"{draft_id}.json"
    record = CustomerPackDraftRecord(
        draft_id=draft_id,
        status="normalized",
        created_at=now,
        updated_at=now,
        request=request,
        plan=plan,
        source_fingerprint=fingerprint,
        parser_route="pptx_customer_pack_normalize_v1",
        parser_backend="pptx_native_slide_extract",
        tenant_id=LOCAL_CUSTOMER_PACK_TENANT_ID,
        workspace_id=LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
        access_groups=(LOCAL_CUSTOMER_PACK_WORKSPACE_ID, LOCAL_CUSTOMER_PACK_TENANT_ID),
        approval_state="approved",
        publication_state="active",
        canonical_book_path=str(book_path),
        normalized_section_count=len(sections),
        private_corpus_manifest_path=str(corpus_manifest_path),
        private_corpus_status="ready",
        private_corpus_chunk_count=len(sections),
        private_corpus_vector_status="skipped",
    )
    CustomerPackDraftStore(root).save(record)
    book = {
        "canonical_model": "canonical_book_v1",
        "book_slug": plan.book_slug,
        "asset_slug": draft_id,
        "asset_kind": "customer_pack_manual_book",
        "title": title,
        "source_type": "pptx",
        "source_uri": source_uri,
        "source_collection": "uploaded",
        "pack_id": "custom-uploaded-custom",
        "pack_label": "User Custom Pack",
        "inferred_product": "openshift",
        "inferred_version": "customer",
        "language_hint": "ko",
        "surface_kind": "slide_deck",
        "source_unit_kind": "slide",
        "source_unit_count": len(sections),
        "approval_state": "approved",
        "publication_state": "active",
        "sections": sections,
    }
    preliminary_manifest = {
        "tenant_id": LOCAL_CUSTOMER_PACK_TENANT_ID,
        "workspace_id": LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
        "pack_id": "custom-uploaded-custom",
        "pack_version": draft_id,
        "classification": "private",
        "access_groups": [LOCAL_CUSTOMER_PACK_WORKSPACE_ID, LOCAL_CUSTOMER_PACK_TENANT_ID],
        "provider_egress_policy": "local_only",
        "approval_state": "approved",
        "publication_state": "active",
        "redaction_state": "raw",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
        "chunk_count": len(sections),
        "bm25_ready": True,
        "vector_status": "skipped",
        "anchor_lineage_count": len(sections),
    }
    quality = evaluate_canonical_book_quality(book, corpus_manifest=preliminary_manifest)
    grade_gate = dict(quality["grade_gate"])
    corpus_manifest = {
        **preliminary_manifest,
        **quality,
        "artifact_version": "customer_private_corpus_v1",
        "truth_owner": "canonical_json_bundle",
        "draft_id": draft_id,
        "manifest_path": str(corpus_manifest_path),
        "read_ready": bool(grade_gate["promotion_gate"]["read_ready"]),
        "publish_ready": bool(grade_gate["promotion_gate"]["publish_ready"]),
        "citation_landing_status": str(grade_gate["citation_gate"]["status"]),
        "retrieval_ready": bool(grade_gate["retrieval_gate"]["ready"]),
    }
    boundary = summarize_private_runtime_boundary(corpus_manifest)
    corpus_manifest["runtime_eligible"] = bool(boundary["runtime_eligible"])
    corpus_manifest["boundary_fail_reasons"] = list(boundary["fail_reasons"])
    manifest = {
        "artifact_version": "customer_pack_artifact_bundle_v1",
        "truth_owner": "canonical_json_bundle",
        "draft_id": draft_id,
        "asset_slug": draft_id,
        "asset_kind": "customer_pack_manual_book",
        "book_slug": plan.book_slug,
        "title": title,
        "source_type": "pptx",
        "source_collection": "uploaded",
        "surface_kind": "slide_deck",
        "source_unit_kind": "slide",
        "source_unit_count": len(sections),
        "rendered_slide_asset_count": len(sections),
        "approval_state": "approved",
        "publication_state": "active",
        "read_ready": True,
        "publish_ready": True,
        "retrieval_ready": True,
        "shared_grade": quality["shared_grade"],
        "updated_at": now,
    }
    _write_json(book_path, book)
    _write_json(settings.customer_pack_books_dir / f"{draft_id}.manifest.json", manifest)
    _write_json(corpus_manifest_path, corpus_manifest)


class CustomerMasterBookTests(unittest.TestCase):
    def test_master_book_composes_context_toc_and_preserves_source_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_source_book(
                root,
                draft_id="dtb-arch",
                title="KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL",
                fingerprint="fingerprint-arch",
                sections=[
                    _source_section("dtb-arch", 1, "OCP 네트워크 구성도", "아키텍처 네트워크 클러스터 구성도"),
                    _source_section("dtb-arch", 2, "CICD 프로세스", "Tekton ArgoCD GitLab Quay ITSM 배포 파이프라인"),
                ],
            )
            _write_source_book(
                root,
                draft_id="dtb-test",
                title="KMSC-COCP-RTER-002-OCP 통합테스트 결과서_20251126",
                fingerprint="fingerprint-test",
                sections=[
                    _source_section("dtb-test", 1, "통합 테스트 계획", "테스트 계획 시나리오 범위"),
                    _source_section("dtb-test", 2, "통합 테스트 결과", "테스트 결과 결함 조치 통과 품질"),
                ],
            )

            book_path, report = write_customer_master_book(
                root,
                master_slug="customer-master-test",
                title="고객 OCP 운영 플레이북",
            )

            self.assertEqual("ready", report["status"])
            self.assertTrue(book_path.exists())
            self.assertEqual(2, report["source_count"])
            self.assertEqual(1.0, report["validation"]["source_coverage_ratio"])
            self.assertTrue(report["publish_ready"])
            self.assertTrue(report["runtime_eligible"])

            payload = json.loads(book_path.read_text(encoding="utf-8"))
            self.assertEqual("고객 OCP 운영 플레이북", payload["title"])
            self.assertFalse(report["validation"]["raw_filename_title"])
            self.assertTrue(validate_customer_master_book(payload)["ok"])

            headings = [section["heading"] for section in payload["sections"]]
            self.assertIn("목표 아키텍처와 OCP 구성", headings)
            self.assertIn("CI/CD 운영 구조", headings)
            self.assertIn("테스트 결과와 품질 판정", headings)
            self.assertEqual("원본 문서와 슬라이드 근거", headings[-1])
            visible_text = "\n".join(str(section.get("text") or "") for section in payload["sections"])
            self.assertIn("CI/CD 아키텍처 설계서", visible_text)
            self.assertIn("OCP 통합 테스트 결과", visible_text)
            self.assertNotIn("KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL", visible_text)
            self.assertNotIn("KMSC-COCP-RTER-002-OCP 통합테스트 결과서_20251126", visible_text)

            source_ids = set()
            for section in payload["sections"]:
                citations = section.get("source_citations") or []
                self.assertTrue(citations)
                for citation in citations:
                    source_ids.add(citation["source_draft_id"])
                    self.assertTrue(citation["source_title"])
                    self.assertTrue(citation["source_viewer_path"].startswith("/playbooks/customer-packs/"))
                    self.assertTrue(citation["source_anchor"])
            self.assertEqual({"dtb-arch", "dtb-test"}, source_ids)

            boundary = load_customer_pack_read_boundary(root, "customer-master-test")
            self.assertTrue(boundary["read_allowed"])
            self.assertEqual("gold", boundary["shared_grade"])


if __name__ == "__main__":
    unittest.main()
