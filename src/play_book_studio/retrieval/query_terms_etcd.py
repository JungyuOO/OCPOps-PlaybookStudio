from __future__ import annotations

# etcd처럼 질문 의도에 따라 설명/절차 용어가 크게 달라지는 특수 규칙을 따로 모은 helper다.

from .intents import BACKUP_RE, ETCD_RE, RESTORE_RE, has_backup_restore_intent, is_explainer_query


def append_etcd_query_terms(normalized: str, terms: list[str]) -> None:
    if ETCD_RE.search(normalized):
        terms.append("etcd")
        if has_backup_restore_intent(normalized):
            backup_signal = bool(BACKUP_RE.search(normalized))
            restore_signal = bool(RESTORE_RE.search(normalized))
            if backup_signal and not restore_signal:
                terms.extend(
                    [
                        "backup",
                        "snapshot",
                        "cluster-backup.sh",
                        "/usr/local/bin/cluster-backup.sh",
                        "static_kuberesources",
                        "정적 pod 리소스",
                        "설치 후 클러스터 작업",
                        "etcd 작업",
                    ]
                )
            elif restore_signal and not backup_signal:
                terms.extend(
                    [
                        "restore",
                        "recovery",
                        "cluster-restore.sh",
                        "/usr/local/bin/cluster-restore.sh",
                        "이전 클러스터 상태",
                        "복원 절차",
                        "설치 후 클러스터 작업",
                        "etcd 작업",
                    ]
                )
            else:
                terms.extend(
                    [
                        "backup",
                        "restore",
                        "disaster",
                        "recovery",
                        "snapshot",
                        "cluster-backup.sh",
                        "cluster-restore.sh",
                    ]
                )
        elif is_explainer_query(normalized) or "중요" in normalized or "역할" in normalized:
            terms.extend(["quorum", "control", "plane", "cluster", "state", "key-value", "store"])
