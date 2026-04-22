from __future__ import annotations

# 운영 절차/트러블슈팅 성격의 질의 확장 façade다.

from .query_terms_operations_rbac import append_operation_rbac_terms
from .query_terms_operations_project_node_deployment import (
    append_operation_project_node_deployment_terms,
)
from .query_terms_operations_pod_cert_login import append_operation_pod_cert_login_terms


def append_operation_query_terms(normalized: str, terms: list[str]) -> None:
    append_operation_rbac_terms(normalized, terms)
    append_operation_project_node_deployment_terms(normalized, terms)
    append_operation_pod_cert_login_terms(normalized, terms)
