from __future__ import annotations

import zipfile
from pathlib import Path

from play_book_studio.ingestion.document_parsing import (
    build_document_chunks,
    detect_document_format,
    parse_upload_document,
)

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
                "# Incident response",
                "",
                "Check the cluster status.",
                "",
                "## Check command",
                "",
                "```bash",
                "oc get co",
                "```",
                "",
                "| item | value |",
                "| --- | --- |",
                "| status | Ready |",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_upload_document(source)

    assert parsed.document_format == "md"
    assert parsed.status == "parsed"
    assert parsed.markdown.startswith("# Incident response")
    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "code",
        "table",
    ]
    assert parsed.blocks[2].section_path == ("Incident response", "Check command")
    assert parsed.blocks[-1].text.startswith("| item")


def test_markdown_blocks_build_section_aware_chunks():
    source = _case_dir("document_chunks") / "runbook.md"
    source.write_text(
        "# Operations\n\nOverview text.\n\n## Install\n\nStep one.\n\n## Verify\n\n`oc get co`",
        encoding="utf-8",
    )

    parsed = parse_upload_document(source)
    chunks = build_document_chunks(parsed, max_chars=80, overlap_blocks=0)

    assert [chunk.section_path for chunk in chunks] == [
        ("Operations",),
        ("Operations", "Install"),
        ("Operations", "Verify"),
    ]
    assert all(chunk.embedding_text for chunk in chunks)


def test_parse_image_document_keeps_asset_and_description():
    image_path = _case_dir("image_asset") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def describe(path, asset):
        assert path == image_path.resolve()
        assert asset.mime_type == "image/png"
        return "OpenShift topology image"

    parsed = parse_upload_document(image_path, image_describer=describe)

    assert parsed.document_format == "image"
    assert len(parsed.assets) == 1
    assert parsed.assets[0].description == "OpenShift topology image"
    assert parsed.blocks[0].block_type == "image"
    assert parsed.blocks[0].asset_ids == (parsed.assets[0].asset_id,)
    assert "OpenShift topology image" in parsed.markdown


def test_converter_formats_use_injected_markdown_adapter():
    pdf_path = _case_dir("converter") / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nfake")

    def convert(path, document_format):
        assert path == pdf_path.resolve()
        assert document_format == "pdf"
        return "# PDF title\n\nBody"

    parsed = parse_upload_document(pdf_path, markdown_converter=convert)

    assert parsed.document_format == "pdf"
    assert parsed.blocks[0].block_type == "heading"
    assert parsed.blocks[1].text == "Body"


def test_docx_default_pipeline_extracts_markdown_blocks_and_chunks():
    docx_path = _case_dir("docx_default") / "guide.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Install guide</w:t></w:r></w:p>
        <w:p><w:r><w:t>Run the installer.</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Check</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Command</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>Cluster</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>oc get co</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>
      </w:body>
    </w:document>
    """
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document_xml)

    parsed = parse_upload_document(docx_path)
    chunks = build_document_chunks(parsed, max_chars=120, overlap_blocks=0)

    assert parsed.document_format == "docx"
    assert "Install guide" in parsed.markdown
    assert "| Check | Command |" in parsed.markdown
    assert any(block.block_type == "table" for block in parsed.blocks)
    assert chunks[0].embedding_text.startswith("guide")


def test_pptx_default_pipeline_extracts_slide_text_and_image_assets():
    pptx_path = _case_dir("pptx_default") / "deck.pptx"
    slide_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
           xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree>
        <p:sp><p:txBody><a:p><a:r><a:t>Architecture</a:t></a:r></a:p></p:txBody></p:sp>
        <p:sp><p:txBody><a:p><a:r><a:t>Router sends traffic to services.</a:t></a:r></a:p></p:txBody></p:sp>
      </p:spTree></p:cSld>
    </p:sld>
    """
    with zipfile.ZipFile(pptx_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("ppt/presentation.xml", "<p:presentation />")
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
        archive.writestr("ppt/media/image1.png", b"\x89PNG\r\n\x1a\nfake")

    parsed = parse_upload_document(
        pptx_path,
        image_describer=lambda _path, asset: f"Visual asset: {asset.filename}",
    )
    chunks = build_document_chunks(parsed, max_chars=140, overlap_blocks=0)

    assert parsed.document_format == "pptx"
    assert "## Slide 1" in parsed.markdown
    assert "Router sends traffic to services." in parsed.markdown
    assert len(parsed.assets) == 1
    assert parsed.assets[0].description == "Visual asset: image1.png"
    assert any(block.block_type == "image" for block in parsed.blocks)
    assert any(parsed.assets[0].asset_id in chunk.asset_ids for chunk in chunks)
