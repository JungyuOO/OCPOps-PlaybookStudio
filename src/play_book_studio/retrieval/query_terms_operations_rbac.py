from __future__ import annotations

import re

from .intents import (
    ADMIN_ROLE_RE,
    CLUSTER_ADMIN_RE,
    EDIT_ROLE_RE,
    PROJECT_SCOPE_RE,
    ROLE_ASSIGN_RE,
    USER_SUBJECT_RE,
    VIEW_ROLE_RE,
    has_rbac_assignment_intent,
    has_rbac_intent,
    has_project_scoped_rbac_intent,
)

RBAC_YAML_RE = re.compile(r"(rolebinding|clusterrolebinding|yaml|manifest|예시|api|spec)", re.IGNORECASE)
RBAC_VERIFY_RE = re.compile(r"(확인|검증|잘 들어갔|반영|적용|검사|check|verify|can-i)", re.IGNORECASE)
RBAC_REVOKE_RE = re.compile(r"(회수|제거|삭제|해제|취소|remove|revoke|unbind)", re.IGNORECASE)
RBAC_DIFF_RE = re.compile(r"(cluster-admin).*(차이|다르|비교)|(?:차이|다르|비교).*(cluster-admin)", re.IGNORECASE)


def append_operation_rbac_terms(normalized: str, terms: list[str]) -> None:
    rbac_follow_up = bool(
        RBAC_YAML_RE.search(normalized)
        or RBAC_VERIFY_RE.search(normalized)
        or RBAC_REVOKE_RE.search(normalized)
        or RBAC_DIFF_RE.search(normalized)
    )
    rbac_intent = has_rbac_intent(normalized) or (
        rbac_follow_up and ("권한" in normalized or "admin" in normalized.lower() or "role" in normalized.lower())
    )
    project_scoped_rbac = has_project_scoped_rbac_intent(normalized) or (
        rbac_intent and bool(PROJECT_SCOPE_RE.search(normalized))
    )
    rbac_assignment = has_rbac_assignment_intent(normalized) or (
        rbac_intent and bool(ROLE_ASSIGN_RE.search(normalized) or ADMIN_ROLE_RE.search(normalized))
    )

    if rbac_intent:
        terms.extend(["RBAC", "role", "binding", "rolebinding"])
        if project_scoped_rbac:
            terms.extend(["project", "namespace", "local", "binding"])
        if rbac_assignment:
            terms.extend(["grant", "assign", "policy", "oc", "adm", "add-role-to-user"])
        if USER_SUBJECT_RE.search(normalized):
            terms.extend(["user", "group", "serviceaccount"])
        if ADMIN_ROLE_RE.search(normalized):
            terms.append("admin")
        if EDIT_ROLE_RE.search(normalized):
            terms.append("edit")
        if VIEW_ROLE_RE.search(normalized):
            terms.append("view")
        if CLUSTER_ADMIN_RE.search(normalized):
            terms.append("cluster-admin")
        if project_scoped_rbac:
            terms.extend(
                [
                    "local role binding",
                    "project administrator",
                    "rolebindings.rbac.authorization.k8s.io",
                    "oc describe rolebinding.rbac -n <project>",
                ]
            )
        if RBAC_YAML_RE.search(normalized):
            terms.extend(
                [
                    "RoleBinding",
                    "ClusterRoleBinding",
                    "apiVersion: rbac.authorization.k8s.io/v1",
                    "kind: RoleBinding",
                    "metadata",
                    "subjects",
                    "roleRef",
                    "oc apply -f <filename>.yaml",
                ]
            )
        if RBAC_VERIFY_RE.search(normalized):
            terms.extend(
                [
                    "verify permission",
                    "check access",
                    "oc describe rolebinding.rbac -n <project>",
                    "LocalSubjectAccessReview",
                    "SelfSubjectAccessReview",
                    "SelfSubjectRulesReview",
                    "SubjectAccessReview",
                    "SubjectRulesReview",
                ]
            )
        if RBAC_REVOKE_RE.search(normalized):
            terms.extend(
                [
                    "remove-role-from-user",
                    "delete rolebinding",
                    "revoke role",
                    "unbind",
                    "oc adm policy remove-role-from-user",
                    "rolebinding.rbac.authorization.k8s.io",
                    "clusterrolebinding.rbac.authorization.k8s.io",
                ]
            )
        if RBAC_DIFF_RE.search(normalized):
            terms.extend(
                [
                    "cluster-admin",
                    "admin",
                    "local binding",
                    "cluster binding",
                    "rolebinding.rbac.authorization.k8s.io",
                    "clusterrolebinding.rbac.authorization.k8s.io",
                    "namespace scope",
                    "cluster scope",
                    "차이",
                    "비교",
                    "로컬 바인딩과 클러스터 바인딩의 차이점",
                ]
            )
