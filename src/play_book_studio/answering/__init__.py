from __future__ import annotations

__all__ = ["ChatAnswerer"]


def __getattr__(name: str):  # noqa: ANN201
    if name == "ChatAnswerer":
        from .answerer import ChatAnswerer

        return ChatAnswerer
    raise AttributeError(name)
