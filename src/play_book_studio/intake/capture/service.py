from __future__ import annotations

# intake source를 실제 artifact로 확보하는 capture service 구현.

import mimetypes
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.collector import fetch_html_text

from ..books.store import CustomerPackDraftStore
from ..models import DocSourceRequest, CustomerPackDraftRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CustomerPackCaptureService:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.settings = load_settings(self.root_dir)
        self.store = CustomerPackDraftStore(self.root_dir)

    def capture(
        self,
        *,
        draft_id: str = "",
        request: DocSourceRequest | None = None,
    ) -> CustomerPackDraftRecord:
        record = self._load_or_create(draft_id=draft_id, request=request)
        try:
            if record.request.source_type == "web":
                artifact_path, content_type, byte_size = self._capture_web(record)
            elif record.request.source_type == "pdf":
                artifact_path, content_type, byte_size = self._capture_pdf(record)
            elif record.request.source_type in {"docx", "pptx", "xlsx", "image"}:
                artifact_path, content_type, byte_size = self._capture_binary_source(record)
            else:
                artifact_path, content_type, byte_size = self._capture_text_source(record)
            record.status = "captured"
            record.capture_artifact_path = str(artifact_path)
            record.capture_content_type = content_type
            record.capture_byte_size = byte_size
            record.source_fingerprint = self._capture_fingerprint(artifact_path)
            record.capture_error = ""
        except Exception as exc:  # noqa: BLE001
            record.status = "capture_failed"
            record.capture_error = str(exc)
            record.updated_at = _utc_now()
            self.store.save(record)
            raise

        record.updated_at = _utc_now()
        self.store.save(record)
        return record

    def _capture_fingerprint(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _load_or_create(
        self,
        *,
        draft_id: str,
        request: DocSourceRequest | None,
    ) -> CustomerPackDraftRecord:
        if draft_id.strip():
            existing = self.store.get(draft_id.strip())
            if existing is None:
                raise ValueError("업로드 플레이북 초안을 찾을 수 없습니다.")
            return existing
        if request is None:
            raise ValueError("capture할 draft_id 또는 request가 필요합니다.")
        return self.store.create(request)

    def _capture_web(self, record: CustomerPackDraftRecord) -> tuple[Path, str, int]:
        acquisition_uri = record.plan.acquisition_uri
        local_source = Path(acquisition_uri).expanduser()
        if local_source.exists() and local_source.is_file():
            guessed_type, _ = mimetypes.guess_type(str(local_source))
            suffix = local_source.suffix.lower()
            if guessed_type == "application/pdf" or suffix == ".pdf":
                raise ValueError(
                    "현재 draft는 web으로 저장됐지만 선택한 파일은 PDF입니다. "
                    "source type을 pdf로 선택하거나 파일 업로드로 다시 추가해 주세요."
                )
            if guessed_type and not guessed_type.startswith("text/") and guessed_type not in {
                "application/json",
                "application/xml",
            }:
                raise ValueError(
                    f"web capture로 읽기 어려운 파일 형식입니다: {guessed_type}. "
                    "HTML/Markdown/Text 파일이거나 실제 웹 URL이어야 합니다."
                )
            try:
                html = local_source.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "web source는 UTF-8 텍스트로 읽을 수 있는 HTML/Markdown/Text 파일이어야 합니다."
                ) from exc
            content_type = guessed_type or "text/html"
        else:
            html = fetch_html_text(acquisition_uri, self.settings)
            content_type = "text/html; charset=utf-8"
        target_dir = self.settings.customer_pack_capture_dir / record.draft_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "source.html"
        target.write_text(html, encoding="utf-8")
        return target, content_type, len(html.encode("utf-8"))

    def _capture_pdf(self, record: CustomerPackDraftRecord) -> tuple[Path, str, int]:
        source = Path(record.plan.acquisition_uri).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {source}")
        suffix = source.suffix or ".pdf"
        target_dir = self.settings.customer_pack_capture_dir / record.draft_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"source{suffix}"
        shutil.copy2(source, target)
        return target, "application/pdf", target.stat().st_size

    def _capture_binary_source(self, record: CustomerPackDraftRecord) -> tuple[Path, str, int]:
        acquisition_uri = record.plan.acquisition_uri
        local_source = Path(acquisition_uri).expanduser()
        default_suffix = {
            "docx": ".docx",
            "pptx": ".pptx",
            "xlsx": ".xlsx",
            "image": ".png",
        }[record.request.source_type]
        default_content_type = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "image": "image/png",
        }[record.request.source_type]

        target_dir = self.settings.customer_pack_capture_dir / record.draft_id
        target_dir.mkdir(parents=True, exist_ok=True)

        if local_source.exists() and local_source.is_file():
            suffix = local_source.suffix or default_suffix
            guessed_type, _ = mimetypes.guess_type(str(local_source))
            target = target_dir / f"source{suffix}"
            shutil.copy2(local_source, target)
            return target, guessed_type or default_content_type, target.stat().st_size

        parsed = urlparse(acquisition_uri)
        if parsed.scheme not in {"http", "https"}:
            raise FileNotFoundError(f"바이너리 소스를 찾을 수 없습니다: {acquisition_uri}")
        response = requests.get(
            acquisition_uri,
            timeout=self.settings.request_timeout_seconds,
            headers={"User-Agent": self.settings.user_agent},
        )
        response.raise_for_status()
        suffix = Path(parsed.path).suffix or default_suffix
        target = target_dir / f"source{suffix}"
        target.write_bytes(response.content)
        return (
            target,
            response.headers.get("content-type", default_content_type),
            len(response.content),
        )

    def _capture_text_source(self, record: CustomerPackDraftRecord) -> tuple[Path, str, int]:
        acquisition_uri = record.plan.acquisition_uri
        local_source = Path(acquisition_uri).expanduser()
        if local_source.exists() and local_source.is_file():
            guessed_type, _ = mimetypes.guess_type(str(local_source))
            if guessed_type and not guessed_type.startswith("text/") and guessed_type not in {
                "application/json",
                "application/xml",
            }:
                raise ValueError(
                    "text source는 UTF-8 텍스트로 읽을 수 있는 Markdown/AsciiDoc/Text 파일이어야 합니다."
                )
            try:
                text = local_source.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "text source는 UTF-8 텍스트로 읽을 수 있는 Markdown/AsciiDoc/Text 파일이어야 합니다."
                ) from exc
            content_type = guessed_type or "text/plain; charset=utf-8"
            suffix = local_source.suffix or {
                "md": ".md",
                "asciidoc": ".adoc",
                "txt": ".txt",
            }.get(record.request.source_type, ".txt")
        else:
            parsed = urlparse(acquisition_uri)
            if parsed.scheme not in {"http", "https"}:
                raise FileNotFoundError(f"텍스트 소스를 찾을 수 없습니다: {acquisition_uri}")
            response = requests.get(
                acquisition_uri,
                timeout=self.settings.request_timeout_seconds,
                headers={"User-Agent": self.settings.user_agent},
            )
            response.raise_for_status()
            response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            text = response.text
            content_type = response.headers.get("content-type", "text/plain; charset=utf-8")
            suffix = {
                "md": ".md",
                "asciidoc": ".adoc",
                "txt": ".txt",
            }.get(record.request.source_type, ".txt")

        target_dir = self.settings.customer_pack_capture_dir / record.draft_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"source{suffix}"
        target.write_text(text, encoding="utf-8")
        return target, content_type, len(text.encode("utf-8"))


__all__ = ["CustomerPackCaptureService"]
