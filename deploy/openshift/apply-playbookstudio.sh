#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-pbs-ocpops}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-admin123}"
OCP_API_TOKEN="${OCP_API_TOKEN:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${OCP_API_TOKEN}" ]]; then
  echo "OCP_API_TOKEN is required. Export it before running this script." >&2
  exit 1
fi

oc apply -f "${SCRIPT_DIR}/core.yaml"

# The upstream postgres/qdrant/nginx images are not fully arbitrary-UID clean.
# This keeps the first in-cluster test deployment moving; harden later if needed.
oc adm policy add-scc-to-user anyuid -z playbookstudio -n "${NAMESPACE}" >/dev/null || true
oc adm policy add-scc-to-user anyuid -z terminal-broker -n "${NAMESPACE}" >/dev/null || true

oc create secret generic playbookstudio-secret \
  -n "${NAMESPACE}" \
  --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  --from-literal=OCP_API_TOKEN="${OCP_API_TOKEN}" \
  --dry-run=client -o yaml | oc apply -f -

oc rollout status deployment/postgres -n "${NAMESPACE}" --timeout=300s
oc rollout status deployment/qdrant -n "${NAMESPACE}" --timeout=300s

run_job() {
  local name="$1"
  local file="$2"
  oc delete job "${name}" -n "${NAMESPACE}" --ignore-not-found=true
  oc apply -f "${SCRIPT_DIR}/${file}"
  oc wait --for=condition=complete "job/${name}" -n "${NAMESPACE}" --timeout=1800s
  oc logs "job/${name}" -n "${NAMESPACE}" --tail=80
}

run_job db-migrate job-db-migrate.yaml
run_job official-corpus-seed job-official-corpus-seed.yaml
run_job kmsc-corpus-seed job-kmsc-corpus-seed.yaml
run_job learning-seed job-learning-seed.yaml
run_job course-runtime-seed job-course-runtime-seed.yaml
run_job qdrant-seed job-qdrant-seed.yaml

oc apply -f "${SCRIPT_DIR}/app.yaml"
oc rollout status deployment/app -n "${NAMESPACE}" --timeout=600s
oc rollout status deployment/web -n "${NAMESPACE}" --timeout=300s

echo
echo "Routes:"
oc get route -n "${NAMESPACE}"
echo
echo "Pods:"
oc get pods -n "${NAMESPACE}" -o wide
