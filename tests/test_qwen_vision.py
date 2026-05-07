from __future__ import annotations

import json
from urllib import error
import zipfile
from pathlib import Path

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.document_parsing import DocumentAsset, build_document_chunks, parse_upload_document
from play_book_studio.ingestion import vision
from play_book_studio.ingestion.vision import QwenVisionClient, build_qwen_image_describer, load_asset_image_bytes

TEST_TMP = Path(__file__).resolve().parents[1] / "tmp" / "qwen_vision_tests"


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "OpenShift console topology diagram.",
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_qwen_vision_client_sends_openai_compatible_image_payload(monkeypatch):
    image_path = _case_dir("client") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="diagram.png",
        mime_type="image/png",
        sha256="sha",
    )
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(vision.request, "urlopen", fake_urlopen)

    client = QwenVisionClient(
        endpoint="http://qwen.internal:8000/v1",
        model="qwen2.5-vl",
        timeout_seconds=7,
    )

    description = client.describe_asset(image_path, asset)

    assert description == "OpenShift console topology diagram."
    assert captured["url"] == "http://qwen.internal:8000/v1/chat/completions"
    assert captured["timeout"] == 7
    assert "Authorization" not in captured["headers"]
    assert captured["body"]["model"] == "qwen2.5-vl"
    image_url = captured["body"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


def test_qwen_describer_factory_is_disabled_until_endpoint_and_model_exist():
    settings = Settings(root_dir=Path.cwd())

    assert build_qwen_image_describer(settings) is None


def test_qwen_describer_factory_uses_existing_llm_settings_by_default():
    settings = Settings(
        root_dir=Path.cwd(),
        llm_endpoint="http://cllm.cywell.co.kr/v1",
        llm_model="Qwen/Qwen3.5-9B",
        request_timeout_seconds=11,
        request_retries=4,
        request_backoff_seconds=3,
    )

    describer = build_qwen_image_describer(settings)

    assert describer is not None
    assert getattr(describer, "qwen_model") == "Qwen/Qwen3.5-9B"
    assert getattr(describer, "qwen_timeout_seconds") == 11
    assert getattr(describer, "qwen_max_attempts") == 4
    assert getattr(describer, "qwen_backoff_seconds") == 3


def test_qwen_vision_client_retries_transient_url_errors(monkeypatch):
    image_path = _case_dir("client_retry") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="diagram.png",
        mime_type="image/png",
        sha256="sha",
    )
    calls = {"count": 0, "sleeps": []}

    def fake_urlopen(_req, timeout):
        assert timeout == 7
        calls["count"] += 1
        if calls["count"] == 1:
            raise error.URLError("temporary connection reset")
        return FakeResponse()

    def fake_sleep(seconds):
        calls["sleeps"].append(seconds)

    monkeypatch.setattr(vision.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(vision.time, "sleep", fake_sleep)

    client = QwenVisionClient(
        endpoint="http://qwen.internal:8000/v1",
        model="qwen2.5-vl",
        timeout_seconds=7,
        max_attempts=2,
        backoff_seconds=0.5,
    )

    description = client.describe_asset(image_path, asset)

    assert description == "OpenShift console topology diagram."
    assert calls == {"count": 2, "sleeps": [0.5]}


def test_parse_image_document_injects_qwen_description_into_chunk_text():
    image_path = _case_dir("parser") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def describe(_path, _asset):
        return "OpenShift router and service diagram"

    setattr(describe, "qwen_model", "Qwen/Qwen3.5-9B")

    parsed = parse_upload_document(image_path, image_describer=describe)
    chunks = build_document_chunks(parsed)

    assert parsed.assets[0].description == "OpenShift router and service diagram"
    assert parsed.assets[0].metadata["qwen_model"] == "Qwen/Qwen3.5-9B"
    assert parsed.assets[0].metadata["qwen_status"] == "described"
    assert "OpenShift router and service diagram" in chunks[0].embedding_text


def test_parse_image_document_preserves_qwen_failure_status():
    image_path = _case_dir("parser_failure") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def describe(_path, _asset):
        raise RuntimeError("vision backend unavailable")

    setattr(describe, "qwen_model", "Qwen/Qwen3.5-9B")

    parsed = parse_upload_document(image_path, image_describer=describe)
    chunks = build_document_chunks(parsed)

    assert parsed.assets[0].description == ""
    assert parsed.assets[0].metadata["qwen_status"] == "failed"
    assert parsed.assets[0].metadata["qwen_model"] == "Qwen/Qwen3.5-9B"
    assert "vision backend unavailable" in parsed.assets[0].metadata["qwen_error"]
    assert "vision backend unavailable" not in chunks[0].embedding_text


def test_parse_image_document_preserves_qwen_empty_status():
    image_path = _case_dir("parser_empty") / "diagram.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def describe(_path, _asset):
        return "   "

    setattr(describe, "qwen_model", "Qwen/Qwen3.5-9B")

    parsed = parse_upload_document(image_path, image_describer=describe)

    assert parsed.assets[0].description == ""
    assert parsed.assets[0].metadata["qwen_status"] == "empty"
    assert parsed.assets[0].metadata["qwen_model"] == "Qwen/Qwen3.5-9B"


def test_load_asset_image_bytes_reads_embedded_pptx_member():
    pptx_path = _case_dir("embedded") / "deck.pptx"
    with zipfile.ZipFile(pptx_path, "w") as archive:
        archive.writestr("ppt/media/image1.png", b"image-bytes")
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="image1.png",
        mime_type="image/png",
        sha256="sha",
        metadata={"source_member": "ppt/media/image1.png"},
    )

    assert load_asset_image_bytes(pptx_path, asset) == b"image-bytes"
