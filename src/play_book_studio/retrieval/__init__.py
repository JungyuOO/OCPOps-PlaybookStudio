from __future__ import annotations

from .models import SessionContext

__all__ = ["ChatRetriever", "SessionContext"]


def __getattr__(name: str):
    if name == "ChatRetriever":
        from .retriever import ChatRetriever

        return ChatRetriever
    raise AttributeError(name)
