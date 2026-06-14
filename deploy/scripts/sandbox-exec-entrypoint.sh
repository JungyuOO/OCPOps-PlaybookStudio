#!/usr/bin/env bash
set +e

namespace="${PBS_SANDBOX_NAMESPACE:-}"
pod="${PBS_SANDBOX_POD:-}"
shell_path="${PBS_SANDBOX_SHELL:-/bin/bash}"
service_account_dir="/var/run/secrets/kubernetes.io/serviceaccount"
token_path="${service_account_dir}/token"
ca_path="${service_account_dir}/ca.crt"
server="${KUBERNETES_SERVICE_HOST:-kubernetes.default.svc}"
port="${KUBERNETES_SERVICE_PORT:-443}"

fail_sandbox_terminal() {
  echo "Sandbox terminal connection is not ready."
  echo "The learner sandbox Pod is not ready. Reconnect the Terminal Session after a moment."
  exit 1
}

if [ -z "${namespace}" ] || [ -z "${pod}" ]; then
  echo "Missing PBS_SANDBOX_NAMESPACE or PBS_SANDBOX_POD."
  fail_sandbox_terminal
fi

if ! command -v oc >/dev/null 2>&1; then
  echo "Missing oc CLI."
  fail_sandbox_terminal
fi

if [ ! -f "${token_path}" ]; then
  echo "Missing in-cluster service account token."
  fail_sandbox_terminal
fi

token="$(cat "${token_path}")"
tls_flags=()
if [ -f "${ca_path}" ]; then
  tls_flags=(--certificate-authority="${ca_path}")
else
  tls_flags=(--insecure-skip-tls-verify=true)
fi

echo "Learning workspace namespace: ${namespace}"
echo "Connecting to sandbox Pod: ${pod}"

exec oc \
  --server="https://${server}:${port}" \
  --token="${token}" \
  "${tls_flags[@]}" \
  exec -it -n "${namespace}" "${pod}" -- "${shell_path}" -i
