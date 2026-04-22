from __future__ import annotations

# customer-pack draft 레코드를 저장하고 읽는 draft store 구현.

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from play_book_studio.config.settings import load_settings

from ..models import DocSourceRequest, CustomerPackDraftRecord
from ..planner import CustomerPackPlanner


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CustomerPackDraftStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.settings = load_settings(self.root_dir)

    @property
    def drafts_dir(self) -> Path:
        return self.settings.customer_pack_drafts_dir

    def create(self, request: DocSourceRequest) -> CustomerPackDraftRecord:
        timestamp = _utc_now()
        draft_id = f"dtb-{uuid.uuid4().hex[:12]}"
        record = CustomerPackDraftRecord(
            draft_id=draft_id,
            status="planned",
            created_at=timestamp,
            updated_at=timestamp,
            request=request,
            plan=CustomerPackPlanner().plan(request),
        )
        self._write(record)
        return record

    def get(self, draft_id: str) -> CustomerPackDraftRecord | None:
        path = self._draft_path(draft_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CustomerPackDraftRecord.from_dict(payload)

    def list(self) -> list[CustomerPackDraftRecord]:
        records: list[CustomerPackDraftRecord] = []
        for path in sorted(self.drafts_dir.glob("*.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(CustomerPackDraftRecord.from_dict(payload))
        records.sort(key=lambda record: (record.created_at, record.draft_id), reverse=True)
        return records

    def delete(self, draft_id: str) -> bool:
        path = self._draft_path(draft_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def save(self, record: CustomerPackDraftRecord) -> CustomerPackDraftRecord:
        self._write(record)
        return record

    def _write(self, record: CustomerPackDraftRecord) -> None:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self._draft_path(record.draft_id).write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _draft_path(self, draft_id: str) -> Path:
        return self.drafts_dir / f"{draft_id}.json"


__all__ = ["CustomerPackDraftStore"]

