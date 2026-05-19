# User Upload RAG Eval

- generated_at: 2026-05-19T22:55:28+09:00
- base_url: http://127.0.0.1:5173
- repository: My Uploads (1e53febb-d212-4327-80e5-71a4828fbad0)
- document_count: 12

## Summary

- total: 50
- ok: 50
- pass: 42
- review: 8
- pass_rate: 0.84

## Review Reasons

- expected_source_not_cited: 7
- missing_required_answer_terms: 5
- no_user_upload_citation: 4
- not_enough_citations: 4
- answer_too_short: 3
- bad_response_kind:no_answer: 3
- bad_response_kind:clarification: 1

## Cases

- `yaml-001` pass (10556.7 ms): YAML에서 key-value를 작성할 때 콜론 뒤 공백이 왜 중요한지 예시로 설명해줘.
- `yaml-002` pass (9653.4 ms): YAML 들여쓰기 규칙에서 Tab을 쓰면 안 되는 이유와 권장 방식은 뭐야?
- `yaml-003` pass (22706.3 ms): YAML 리스트를 하이픈 방식과 대괄호 방식으로 쓰는 방법을 비교해줘.
- `yaml-004` pass (12981.9 ms): 쿠버네티스 spec 안에서 딕셔너리 내부 리스트를 쓸 때 어떤 모양이 되는지 설명해줘.
- `storage-001` pass (32224.3 ms): PV와 PVC의 차이를 초보자 기준으로 설명해줘.
- `storage-002` pass (13092.3 ms): StorageClass는 PV/PVC 흐름에서 어떤 역할을 해?
- `storage-003` pass (27621.1 ms): 동적 프로비저닝과 정적 프로비저닝의 차이를 설명해줘.
- `storage-004` pass (12468.2 ms): PVC가 Pending 상태일 때 먼저 확인해야 할 항목은 뭐야?
- `storage-005` pass (13340.4 ms): PV와 PVC 상태를 확인하는 oc 명령어를 알려줘.
- `network-001` pass (14416.2 ms): Service가 Pod 앞에서 하는 역할을 설명해줘.
- `network-002` pass (10804.6 ms): ClusterIP, NodePort, LoadBalancer 타입의 차이를 비교해줘.
- `network-003` pass (11278.0 ms): Route와 Ingress는 외부 접근 관점에서 어떻게 다른지 알려줘.
- `network-004` pass (14298.9 ms): Pod 간 통신과 외부 트래픽 유입 흐름을 한 번에 설명해줘.
- `network-005` pass (11772.1 ms): 네트워크 문제를 볼 때 Service와 Endpoint 중 무엇을 먼저 확인해야 해?
- `rbac-001` pass (15093.7 ms): RBAC에서 Role과 RoleBinding의 관계를 설명해줘.
- `rbac-002` pass (12321.1 ms): ClusterRole과 Role은 적용 범위가 어떻게 달라?
- `rbac-003` review (12248.1 ms): SCC는 OpenShift에서 어떤 보안 제어를 담당해?
  - reasons: answer_too_short, bad_response_kind:no_answer, not_enough_citations, no_user_upload_citation, missing_required_answer_terms, expected_source_not_cited
- `rbac-004` review (14198.6 ms): Pod가 권한 문제로 실행되지 않을 때 SCC 관점에서 무엇을 확인해야 해?
  - reasons: answer_too_short, bad_response_kind:no_answer, not_enough_citations, no_user_upload_citation, missing_required_answer_terms, expected_source_not_cited
- `rbac-005` pass (17482.3 ms): ServiceAccount에 권한을 붙이는 흐름을 RBAC 기준으로 설명해줘.
- `imagestream-001` pass (14565.6 ms): ImageStream은 일반 컨테이너 이미지와 무엇이 달라?
- `imagestream-002` pass (11261.2 ms): ImageStreamTag는 이미지 배포 흐름에서 어떤 의미야?
- `imagestream-003` pass (12434.5 ms): 외부 이미지 레지스트리 이미지를 OpenShift에서 가져오는 절차를 설명해줘.
- `imagestream-004` review (41146.5 ms): 이미지 변경이 배포로 이어지는 흐름을 ImageStream 기준으로 설명해줘.
  - reasons: expected_source_not_cited
- `variables-001` pass (12497.0 ms): OpenShift에서 환경변수를 설정하는 대표적인 방법을 설명해줘.
- `variables-002` pass (13480.9 ms): ConfigMap과 Secret은 변수 관리 관점에서 어떻게 구분해야 해?
- `variables-003` pass (10305.2 ms): Pod에 ConfigMap 값을 주입하는 방식들을 정리해줘.
- `variables-004` pass (26133.4 ms): Secret을 사용할 때 평문 환경변수와 비교해서 주의할 점은 뭐야?
- `variables-005` review (7825.2 ms): 환경변수 설정이 제대로 들어갔는지 확인하는 방법을 알려줘.
  - reasons: bad_response_kind:clarification, not_enough_citations, no_user_upload_citation, missing_required_answer_terms, expected_source_not_cited
- `questions-001` pass (7281.5 ms): 09번 질문 문서에서 좋은 질문을 만들기 위해 강조하는 핵심을 요약해줘.
- `questions-002` review (15028.6 ms): 운영자가 문제 상황을 질문할 때 어떤 정보를 같이 줘야 답변 품질이 좋아져?
  - reasons: expected_source_not_cited
- `questions-003` pass (21268.2 ms): 모호한 질문과 구체적인 질문의 차이를 예시 중심으로 설명해줘.
- `github-001` pass (10337.2 ms): 폐쇄망 외부에서 GitHub webhook을 받기 위해 Smee.io를 쓰는 흐름을 설명해줘.
- `github-002` review (9328.5 ms): smee-client를 설치하고 실행하는 명령어 흐름을 알려줘.
  - reasons: expected_source_not_cited
- `github-003` pass (9341.0 ms): GitHub Webhook URL을 Smee URL로 바꾸는 이유가 뭐야?
- `github-004` pass (12642.4 ms): webhook secret을 만들 때 oc patch secret 예시는 어떤 용도야?
- `argocd-001` pass (14106.0 ms): ArgoCD 기반 CD 흐름에서 base와 overlays 폴더를 나누는 이유를 설명해줘.
- `argocd-002` pass (13229.6 ms): kustomization.yaml에서 resources, namePrefix, images 항목이 각각 하는 일을 설명해줘.
- `argocd-003` pass (16671.1 ms): 개발 환경과 운영 환경을 overlays/dev, overlays/prod로 나누면 어떤 장점이 있어?
- `argocd-004` pass (15877.1 ms): 애플리케이션 별 관리방 구조에서 서비스별 base와 overlays를 어떻게 배치해?
- `argocd-005` pass (14655.6 ms): ArgoCD 문서 기준으로 GitOps repo 구조를 초보자에게 설명해줘.
- `ci-001` pass (10421.8 ms): CI 순서 문서에서 전체 파이프라인 흐름을 단계별로 요약해줘.
- `ci-002` pass (9192.6 ms): CI 과정에서 소스 체크아웃 이후 어떤 작업들이 이어지는지 설명해줘.
- `ci-003` pass (11004.2 ms): 빌드와 이미지 생성이 CI 흐름에서 어떤 순서로 연결되는지 설명해줘.
- `ci-004` pass (14186.9 ms): CI 결과물을 CD나 ArgoCD 흐름과 연결하려면 어떤 정보가 필요해?
- `cross-001` pass (13077.3 ms): 스토리지 문제와 네트워크 문제를 구분해서 초동 점검 순서를 정리해줘.
- `cross-002` review (14624.2 ms): Pod가 뜨지 않을 때 RBAC 문제인지 SCC 문제인지 어떻게 구분해서 봐야 해?
  - reasons: answer_too_short, bad_response_kind:no_answer, not_enough_citations, no_user_upload_citation, missing_required_answer_terms, expected_source_not_cited
- `cross-003` pass (12588.1 ms): CI 순서와 ArgoCD CD 흐름을 연결해서 전체 배포 흐름을 설명해줘.
- `cross-004` pass (18600.3 ms): 폐쇄망에서 GitHub webhook을 받아 CI로 이어지게 하려면 어떤 흐름으로 구성해야 해?
- `cross-005` pass (14487.2 ms): YAML 작성 규칙을 모르면 ArgoCD kustomization.yaml에서 어떤 문제가 생길 수 있어?
- `cross-006` review (16799.0 ms): ConfigMap, Secret, kustomization.yaml을 함께 써서 환경별 설정을 관리하는 흐름을 설명해줘.
  - reasons: missing_required_answer_terms
