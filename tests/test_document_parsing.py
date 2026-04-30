from __future__ import annotations

import zipfile
from pathlib import Path

from play_book_studio.ingestion.document_parsing import detect_document_format, parse_upload_document

TEST_TMP = Path(__file__).resolve().parents[1] / "tmp" / "document_parsing_tests"


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_detect_document_format_uses_magic_bytes():
    pdf_path = _case_dir("magic_bytes") / "report.bin"
    pdf_path.write_bytes(b"%PDF-1.7\n% test")

    assert detect_document_format(pdf_path) == "pdf"


def test_detect_document_format_identifies_office_zip_packages():
    case_dir = _case_dir("office_zip")
    docx_path = case_dir / "sample.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<w:document />")

    pptx_path = case_dir / "sample.pptx"
    with zipfile.ZipFile(pptx_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("ppt/presentation.xml", "<p:presentation />")

    hwpx_path = case_dir / "sample.hwpx"
    with zipfile.ZipFile(hwpx_path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/content.hpf", "<package />")

    assert detect_document_format(docx_path) == "docx"
    assert detect_document_format(pptx_path) == "pptx"
    assert detect_document_format(hwpx_path) == "hwpx"


def test_parse_markdown_document_builds_structured_blocks():
    source = _case_dir("markdown_blocks") / "runbook.md"
    source.write_text(
        "\n".join(
            [
                "# 장애 대응",
                "",
                "클러스터 상태를 확인합니다.",
                "",
                "## 확인 명령",
                "",
                "```bash",
                "oc get co",
                "```",
                "",
                "| 항목 | 값 |",
                "| --- | --- |",
                "| status | Ready |",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_upload_document(source)

    assert parsed.document_format == "md"
    assert parsed.status == "parsed"
    assert parsed.markdown.startswith("# 장애 대응")
    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "code",
        "table",
    ]
    assert parsed.blocks[2].section_path == ("장애 대응", "확인 명령")
    assert parsed.blocks[-1].text.startswith("| 항목")


def test_parse_image_document_keeps_asset_and_description():
    image_path = _case_dir("image_asset") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def describe(path, asset):
        assert path == image_path.resolve()
        assert asset.mime_type == "image/png"
        return "OpenShift 구성도 이미지"

    parsed = parse_upload_document(image_path, image_describer=describe)

    assert parsed.document_format == "image"
    assert len(parsed.assets) == 1
    assert parsed.assets[0].description == "OpenShift 구성도 이미지"
    assert parsed.blocks[0].block_type == "image"
    assert parsed.blocks[0].asset_ids == (parsed.assets[0].asset_id,)
    assert "OpenShift 구성도 이미지" in parsed.markdown


def test_converter_formats_use_injected_markdown_adapter():
    pdf_path = _case_dir("converter") / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nfake")

    def convert(path, document_format):
        assert path == pdf_path.resolve()
        assert document_format == "pdf"
        return "# PDF 제목\n\n본문"

    parsed = parse_upload_document(pdf_path, markdown_converter=convert)

    assert parsed.document_format == "pdf"
    assert parsed.blocks[0].block_type == "heading"
    assert parsed.blocks[1].text == "본문"
