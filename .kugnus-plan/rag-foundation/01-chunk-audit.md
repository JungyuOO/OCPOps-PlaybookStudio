# Chunk Audit

## official_source_audit

- Chunks: `27907`
- Token p50/p90/p95/max: `181` / `219` / `229` / `363`
- Decision: `audit_before_rechunking`

| issue | count | rate |
|---|---:|---:|
| `code_plus_navigation` | 358 | 0.0128 |
| `command_dense_chunk` | 7932 | 0.2842 |
| `high_latin_ratio_ko_chunk` | 8406 | 0.3012 |
| `mixed_procedure_navigation` | 150 | 0.0054 |
| `oversized_chunk` | 313 | 0.0112 |
| `raw_code_markup` | 14508 | 0.5199 |
| `undersized_chunk` | 1 | 0.0 |

## kmsc_source_audit

- Chunks: `523`
- Token p50/p90/p95/max: `25` / `62` / `72` / `125`
- Decision: `keep_chunking_stable`

| issue | count | rate |
|---|---:|---:|
| `command_dense_chunk` | 13 | 0.0249 |
| `undersized_chunk` | 160 | 0.3059 |

## DB Large/Empty Samples

```json
[
  {
    "id": "fbb63378-5eee-5c1d-9078-72adf1e9ae00",
    "chunk_role": "leaf",
    "chunk_type": "integration_scenario_summary",
    "token_count": 3074,
    "heading_title": "기본 CI/CD 파이프라인 기능 테스트 1.1. 파이프라인 시작(Trigger) 1.2. 소스 코드 Clone 1.3. S2I/빌드 성공 1.4. Deployment 롤아웃 1.5. 서비스 접근 확인",
    "source_anchor": "slide:2",
    "preview": "1 기본 CI/CD 파이프라인 기능 테스트 1.1. 파이프라인 시작(Trigger) 1.2. 소스 코드 Clone 1.3. S2I/빌드 성공 1.4. Deployment 롤아웃 1.5. 서비스 접근 확인.\nintegration_test 단계의 integration_scenario_summary 청크.\n목차 1.\n주요 기술: GitLab, Quay.\n네트워크/영역: 내부.\n목차 1.\n파이프라인 실행 모듈의 현재 상태가 'Runn"
  },
  {
    "id": "d9aef8bd-cd99-58d5-9278-0acf14a0e32e",
    "chunk_role": "leaf",
    "chunk_type": "integration_scenario_summary",
    "token_count": 3041,
    "heading_title": "실패 및 롤백 테스트",
    "source_anchor": "slide:6",
    "preview": "3 실패 및 롤백 테스트.\nintegration_test 단계의 integration_scenario_summary 청크.\n주요 기술: GitOps, GitLab, Quay, NFS.\n파이프라인 실행 상태가 'Failed'로 표시된 상태바와 관련 텍스트가 보입니다. Java 컴파일 오류 로그 화면으로, 'cannot find symbol' 오류와 'Build failed with an exception' 실패 상태가 표시됨. "
  },
  {
    "id": "7952be9c-bb7b-51ed-a3f3-ff2bdc9f5a83",
    "chunk_role": "leaf",
    "chunk_type": "perf_section_summary",
    "token_count": 2164,
    "heading_title": "성능 테스트 결과",
    "source_anchor": "slide:23",
    "preview": "4 성능 테스트 결과.\nperf_test 단계의 perf_section_summary 청크.\n최대 부하 유저수 : 60,000 초기 부하 유저수 : 300 Ramp-up 시간 : 30초 단계별 증가 유저수 : 300 단계별 유지시간 : 30초 최대 부하 유저 유지 시간 : 5분 서비스 처리에 대한 병목 발생 DB SQL 응답시간이 느려 지면서 전체적인 응답시간에 지연이 발생 HPA 지표 수집 HPA는 설정된 시간 간격(defa"
  },
  {
    "id": "9b890d9b-25ae-5063-a3df-774955977043",
    "chunk_role": "leaf",
    "chunk_type": "integration_scenario_summary",
    "token_count": 1962,
    "heading_title": "고급 CI/CD 및 운영 통합 테스트",
    "source_anchor": "slide:5",
    "preview": "2 고급 CI/CD 및 운영 통합 테스트.\nintegration_test 단계의 integration_scenario_summary 청크.\n주요 기술: Logging, Oracle, Vertica, Redis.\n네트워크/영역: 외부, DB.\n이 이미지는 Kubernetes ConfigMap 파일인 'configmap.yaml'의 일부로, Oracle 데이터베이스 연결 설정과 HikariCP 커넥션 풀 설정을 보여줍니다. Kub"
  },
  {
    "id": "279f1ec6-1342-5a4e-bcee-f40a73c42667",
    "chunk_role": "leaf",
    "chunk_type": "chapter_summary",
    "token_count": 938,
    "heading_title": "테스트 개요 단위 테스트 결과 통합/성능 테스트 결과",
    "source_anchor": "slide:60",
    "preview": "CH-05 테스트 개요 단위 테스트 결과 통합/성능 테스트 결과.\ncompletion 단계의 chapter_summary 청크.\nⅤ.\n주요 기술: IngressController, ArgoCD, GitLab, Oracle, Vertica, HAProxy, Istio, HPA.\n네트워크/영역: 내부, DB.\nⅤ.\nOpenShift 단위 테스트 결과서 표의 일부로, OCP 구성 확인을 위한 테스트명, 테스트 케이스, 레벨, ID,"
  }
]
```
