# CRC / OpenShift Check

- Status: `reference`
- Scope: PBS to local CRC resource lookup only
- Not included in current RAG foundation go/no-go

## Previous Check

- Connection ID: `env_ocp`
- Cluster URL: `https://host.docker.internal:6443`
- Namespace: `openshift-console`
- Pod count: `2`
- Route count: `2`
- Overview counts: `pods=2`, `deployments=2`, `services=2`, `routes=2`, `events=0`

## Evidence

| target | status | evidence |
|---|---|---|
| app health | `pass` | `/api/health` ok |
| OCP profile | `pass` | `/api/v1/auth/ocp/profiles` returned `env_ocp`, status `connected` |
| pods | `pass` | `/api/v1/ocp/resources/env_ocp?resource=pods&namespace=openshift-console` returned 2 items |
| routes | `pass` | `/api/v1/ocp/resources/env_ocp?resource=routes&namespace=openshift-console` returned 2 items |

## Current Handling

- PBS RAG foundation validation is complete without requiring CRC.
- OpenShift Lightspeed installation on CRC requires a separate resource check.
- If CRC monitoring requires 14GB memory, stop PBS containers first and test Lightspeed separately.
- Do not treat this page as proof that OpenShift Lightspeed is installed or ready.
