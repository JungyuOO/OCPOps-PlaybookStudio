from __future__ import annotations

# retrieval 질문 의도 판별과 관련 regex/heuristic 모음.

import re

OCP_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])", re.IGNORECASE)
OPENSHIFT_RE = re.compile(r"(오픈\s*시프트|오픈시프트|openshift)", re.IGNORECASE)
KUBERNETES_RE = re.compile(r"(쿠버네티스|kubernetes)", re.IGNORECASE)
COMPARE_RE = re.compile(r"(차이|다른 점|비교|vs|versus|유사점|달라|다를까|다름|구분)", re.IGNORECASE)
ROUTE_RE = re.compile(r"(route|routes|루트)", re.IGNORECASE)
INGRESS_RE = re.compile(r"(ingress|ingresses|인그레스)", re.IGNORECASE)
ARCHITECTURE_RE = re.compile(r"(아키텍처|architecture)", re.IGNORECASE)
LOGGING_RE = re.compile(r"(로그|로깅|logging)", re.IGNORECASE)
AUDIT_RE = re.compile(r"(감사|audit)", re.IGNORECASE)
EVENT_RE = re.compile(r"(이벤트|event)", re.IGNORECASE)
APP_RE = re.compile(r"(애플리케이션|application|pod|컨테이너|container)", re.IGNORECASE)
POD_PENDING_RE = re.compile(r"(pod|파드).*(pending|펜딩)|(pending|펜딩)", re.IGNORECASE)
CRASH_LOOP_RE = re.compile(r"(crashloopbackoff|crash loop backoff|크래시루프백오프)", re.IGNORECASE)
POD_LIFECYCLE_RE = re.compile(
    r"(pod lifecycle|pod 라이프사이클|파드 라이프사이클|pod 생명주기|파드 생명주기|lifecycle)",
    re.IGNORECASE,
)
OC_LOGIN_RE = re.compile(r"\boc\s+login\b|(로그인).*(\boc\b)", re.IGNORECASE)
INFRA_RE = re.compile(r"(인프라|infra|노드|node|컨트롤 플레인|control plane)", re.IGNORECASE)
MONITORING_RE = re.compile(r"(모니터링|monitoring)", re.IGNORECASE)
OBSERVABILITY_RE = re.compile(r"(observability|관찰 기능|관측|옵저버빌리티)", re.IGNORECASE)
SECURITY_RE = re.compile(r"(보안|security)", re.IGNORECASE)
AUTH_RE = re.compile(r"(인증|authentication)", re.IGNORECASE)
AUTHZ_RE = re.compile(r"(권한|authorization)", re.IGNORECASE)
UPDATE_RE = re.compile(r"(업데이트|upgrade|update|업그레이드)", re.IGNORECASE)
CERT_RE = re.compile(r"(인증서|certificate|certificates|cert)", re.IGNORECASE)
EXPIRY_RE = re.compile(r"(만료|만료일|만료 상태|expire|expiry|expiration|남았)", re.IGNORECASE)
DEPLOYMENT_RE = re.compile(r"(deployment(?!config)|deployments|디플로이먼트|배포)", re.IGNORECASE)
DEPLOYMENTCONFIG_RE = re.compile(r"(deploymentconfig|\bdc\b|디플로이먼트컨피그)", re.IGNORECASE)
SCALE_RE = re.compile(r"(스케일|scale|늘리|줄이|변경|조정)", re.IGNORECASE)
REPLICA_RE = re.compile(r"(복제본|replica|replicas)", re.IGNORECASE)
RBAC_RE = re.compile(
    r"(\brbac\b|역할 기반 액세스 제어|rolebinding|clusterrolebinding|clusterrole|역할 바인딩|role binding)",
    re.IGNORECASE,
)
PROJECT_SCOPE_RE = re.compile(r"(프로젝트|project|네임스페이스|namespace|이름공간)", re.IGNORECASE)
ROLE_ASSIGN_RE = re.compile(
    r"(주고 싶|주려|부여|할당|추가|설정|바인딩|묶|grant|assign|bind)",
    re.IGNORECASE,
)
ROLE_API_STYLE_RE = re.compile(r"(api|yaml|manifest|json|spec|필드|curl)", re.IGNORECASE)
USER_SUBJECT_RE = re.compile(r"(사용자|유저|작업자|계정|그룹|serviceaccount|서비스 계정)", re.IGNORECASE)
ADMIN_ROLE_RE = re.compile(r"(관리자|어드민|\badmin\b)", re.IGNORECASE)
EDIT_ROLE_RE = re.compile(r"(편집|\bedit\b)", re.IGNORECASE)
VIEW_ROLE_RE = re.compile(r"(읽기 전용|보기|\bview\b)", re.IGNORECASE)
CLUSTER_ADMIN_RE = re.compile(r"\bcluster-admin\b", re.IGNORECASE)
MCO_RE = re.compile(
    r"(machine config operator|mco(?:가|는|를|란|와|과)?|머신\s*컨피그\s*오퍼레이터|머신\s*구성\s*오퍼레이터)",
    re.IGNORECASE,
)
DISCONNECTED_RE = re.compile(r"(연결이 없는 환경|분리망|disconnect)", re.IGNORECASE)
ETCD_RE = re.compile(r"etcd", re.IGNORECASE)
BACKUP_RE = re.compile(r"(백업|backup)", re.IGNORECASE)
RESTORE_RE = re.compile(r"(복구|복원|restore)", re.IGNORECASE)
NODE_RE = re.compile(r"(노드|node|worker)", re.IGNORECASE)
DRAIN_RE = re.compile(r"(drain|비워|비우|evacuate|점검 때문에 비워)", re.IGNORECASE)
TOP_RE = re.compile(r"(\btop\b|사용량|cpu|메모리|memory)", re.IGNORECASE)
HOSTED_CONTROL_PLANE_RE = re.compile(
    r"(hosted control plane|hosted cluster|호스팅된 컨트롤 플레인|호스트된 컨트롤 플레인|호스팅 제어 평면|제어 평면|hypershift|oadp|velero)",
    re.IGNORECASE,
)
PROJECT_TERMINATING_RE = re.compile(
    r"(프로젝트|project|namespace|네임스페이스).*(삭제|지웠|지우|terminating|종료 중|안 없어|안 없어지|안 지워|안 지워지)",
    re.IGNORECASE,
)
FINALIZER_RE = re.compile(
    r"(finalizer|finalizers|metadata\.finalizers|강제 제거|강제로 제거|finalizer 제거)",
    re.IGNORECASE,
)
REMAINING_RESOURCE_RE = re.compile(
    r"(걸려 있는 리소스|남아 있는 리소스|remaining resource|resource resolving|error resolving resource|crd|custom resource|리소스 에러)",
    re.IGNORECASE,
)
OPERATOR_RE = re.compile(
    r"(오퍼레이터|operator(?:가|는|를|란|와|과)?|\boperator\b)",
    re.IGNORECASE,
)
DOC_LOCATOR_RE = re.compile(
    r"(문서|가이드|어디서|어디 있어|어디를|찾아|찾을|봐야|보려면|보고 싶|참고할)|"
    r"((위키|wiki).*(이동|순서|경로|들어가|찾아가|따라가))",
    re.IGNORECASE,
)
FIRST_STEP_RE = re.compile(
    r"(가장\s*먼저|맨\s*먼저|처음(?:에는|엔)?|첫\s*(?:단계|번째|순서|행동|확인|명령)|"
    r"어디부터|뭐부터|무엇부터|먼저\s*(?:뭘|무엇|어떤\s*명령|확인|시작)|"
    r"first\s+(?:step|command)|start\s+with)",
    re.IGNORECASE,
)
SECURITY_SCOPE_RE = re.compile(
    r"(컴플라이언스|compliance|감사|audit|인증|authentication|권한|authorization|rbac|네트워크|network|tls|certificate|cert|암호화|egress|ingress)",
    re.IGNORECASE,
)
EXPLAINER_RE = re.compile(
    r"(설명해줘|설명해 줘|처음 설명|처음부터 설명|개념 설명|뭐야\??|무엇인가\??|무슨 역할|왜 중요|차이가 뭐야\??|역할이 뭐야\??|뭘 해\??|무엇을 해\??|what does .* do|요약해줘|요약해 줘|요약해봐|요약해 봐|정리해줘|정리해 줘|세줄|3줄|한줄|짧게)",
    re.IGNORECASE,
)
GENERIC_INTRO_RE = re.compile(
    r"(오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9])).*(뭐야|무엇|소개|개요|아키텍처|architecture|실무에서|어디에\s*쓰|어떤\s*곳에\s*쓰|무슨\s*용도|사용\s*예시|언제\s*쓰|왜\s*써)|"
    r"(오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9])).*(요약|정리|세줄|3줄|한줄|짧게)|"
    r"(쿠버네티스|kubernetes).*(오픈\s*시프트|오픈시프트|openshift).*(차이|다른 점)",
    re.IGNORECASE,
)
COMPARE_DECOMPOSE_RE = re.compile(
    r"(?P<left>.+?)(?:\s*(?:vs\.?|versus|와|과|랑)\s*)(?P<right>.+?)(?:\s*(?:의)?\s*(?:차이|차이점|비교|다른 점).*)$",
    re.IGNORECASE,
)
ROUTE_TIMEOUT_RE = re.compile(r"(route|루트).*(시간|timeout|타임아웃|늘리|줄이|변경|조정)", re.IGNORECASE)
NODE_NOTREADY_RE = re.compile(r"(node|노드|worker|워커).*(notready|안돼|왜그래|상태|죽었|끊겼)", re.IGNORECASE)
CONJUNCTION_SPLIT_RE = re.compile(r"\s*(?:그리고|또한|및|and then|and also|and)\s*", re.IGNORECASE)
GENERIC_CONTEXT_TOPIC_RE = re.compile(
    r"(운영 설정 변경|복구 절차 검토|설정 변경|설정 검토|운영 설정|복구 절차|절차 검토|일반 설정)",
    re.IGNORECASE,
)
MACHINE_CONFIG_REBOOT_RE = re.compile(
    r"((machine\s*config(?:uration)?|머신\s*(?:구성|설정)|mco).*(재부팅|reboot|롤링 재부팅))|((재부팅|reboot).*(machine\s*config(?:uration)?|머신\s*(?:구성|설정)|mco))",
    re.IGNORECASE,
)
REGISTRY_RE = re.compile(r"(레지스트리|registry|openshift-image-registry)", re.IGNORECASE)
IMAGE_RE = re.compile(r"(이미지|image)", re.IGNORECASE)
STORAGE_RE = re.compile(r"(저장소|스토리지|storage|미러링|mirror|pvc|s3|ceph|nfs|emptydir)", re.IGNORECASE)

# 의도 판별기는 retrieval shaping 여러 곳에서 재사용되므로 파일 상단에 모아 둔다.
# retriever 가중치를 건드리기 전에 이 파일을 위에서 아래로 한 번 읽는 게 좋다.

__all__ = [
    "OCP_RE",
    "OPENSHIFT_RE",
    "KUBERNETES_RE",
    "COMPARE_RE",
    "ROUTE_RE",
    "INGRESS_RE",
    "ARCHITECTURE_RE",
    "LOGGING_RE",
    "AUDIT_RE",
    "EVENT_RE",
    "APP_RE",
    "POD_PENDING_RE",
    "CRASH_LOOP_RE",
    "POD_LIFECYCLE_RE",
    "OC_LOGIN_RE",
    "INFRA_RE",
    "MONITORING_RE",
    "OBSERVABILITY_RE",
    "SECURITY_RE",
    "AUTH_RE",
    "AUTHZ_RE",
    "UPDATE_RE",
    "CERT_RE",
    "EXPIRY_RE",
    "DEPLOYMENT_RE",
    "DEPLOYMENTCONFIG_RE",
    "SCALE_RE",
    "REPLICA_RE",
    "RBAC_RE",
    "PROJECT_SCOPE_RE",
    "ROLE_ASSIGN_RE",
    "ROLE_API_STYLE_RE",
    "USER_SUBJECT_RE",
    "ADMIN_ROLE_RE",
    "EDIT_ROLE_RE",
    "VIEW_ROLE_RE",
    "CLUSTER_ADMIN_RE",
    "MCO_RE",
    "DISCONNECTED_RE",
    "ETCD_RE",
    "BACKUP_RE",
    "RESTORE_RE",
    "NODE_RE",
    "DRAIN_RE",
    "TOP_RE",
    "HOSTED_CONTROL_PLANE_RE",
    "PROJECT_TERMINATING_RE",
    "FINALIZER_RE",
    "REMAINING_RESOURCE_RE",
    "OPERATOR_RE",
    "DOC_LOCATOR_RE",
    "FIRST_STEP_RE",
    "SECURITY_SCOPE_RE",
    "EXPLAINER_RE",
    "GENERIC_INTRO_RE",
    "COMPARE_DECOMPOSE_RE",
    "ROUTE_TIMEOUT_RE",
    "NODE_NOTREADY_RE",
    "CONJUNCTION_SPLIT_RE",
    "GENERIC_CONTEXT_TOPIC_RE",
    "MACHINE_CONFIG_REBOOT_RE",
    "REGISTRY_RE",
    "IMAGE_RE",
    "STORAGE_RE",
]
