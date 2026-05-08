from pathlib import Path

from play_book_studio.http import server_routes_viewer


class DummyHandler:
    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=200):
        self.payload = payload
        self.status = status


def test_runtime_figures_uses_wiki_relation_loader(monkeypatch):
    monkeypatch.setattr(
        server_routes_viewer,
        "_figure_assets",
        lambda: {
            "overview": [
                {
                    "caption": "OCP stack",
                    "asset_url": "https://docs.example/oke-about-ocp-stack-image.png",
                    "asset_kind": "figure",
                    "diagram_type": "architecture",
                }
            ]
        },
    )

    handler = DummyHandler()
    server_routes_viewer.handle_runtime_figures(
        handler,
        "book_slug=overview&limit=1",
        root_dir=Path.cwd(),
    )

    assert handler.status == 200
    assert handler.payload["count"] == 1
    assert handler.payload["items"][0]["caption"] == "OCP stack"
    assert handler.payload["items"][0]["viewer_path"] == "/wiki/figures/overview/oke-about-ocp-stack-image.png/index.html"
