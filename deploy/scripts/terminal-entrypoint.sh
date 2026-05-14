#!/usr/bin/env bash
set +e

if [ -n "${KUBECONFIG:-}" ]; then
  export KUBECONFIG
else
  export KUBECONFIG="$(mktemp /tmp/playbookstudio-kubeconfig.XXXXXX)"
fi
login_log=/tmp/playbookstudio-oc-login.log
version_log=/tmp/playbookstudio-oc-version.log

print_login_log_tail() {
  if [ -f "${login_log}" ]; then
    echo "Last oc login log lines:"
    sed -E 's/(--token=|token=|Authorization: Bearer )[A-Za-z0-9._~:-]+/\1<redacted>/g' "${login_log}" | tail -n 20
  fi
}

fail_cluster_terminal() {
  echo "Cluster terminal connection is not ready."
  echo "Refresh the OpenShift API URL and token, then reconnect the Terminal Session."
  echo "Local shell fallback is disabled. This terminal opens only after a successful OpenShift CLI login."
  exit 1
}

classify_login_failure() {
  if [ ! -f "${login_log}" ]; then
    echo "OpenShift CLI login failure type: unknown (login log missing)"
    return
  fi
  if grep -Eqi 'unauthorized|forbidden|invalid.*token|token.*invalid|authentication required' "${login_log}"; then
    echo "OpenShift CLI login failure type: auth/token"
  elif grep -Eqi 'x509|certificate|certificate signed by unknown authority|tls' "${login_log}"; then
    echo "OpenShift CLI login failure type: tls/certificate"
  elif grep -Eqi 'no route to host|connection refused|timed out|timeout|could not resolve|name or service not known|network is unreachable' "${login_log}"; then
    echo "OpenShift CLI login failure type: network/dns"
  elif grep -Eqi 'error loading config file|mapping values are not allowed|yaml:' "${login_log}"; then
    echo "OpenShift CLI login failure type: kubeconfig"
  else
    echo "OpenShift CLI login failure type: unknown"
  fi
}

if command -v oc >/dev/null 2>&1 && [ -n "${OCP_API_BASE_URL:-}" ] && [ -n "${OCP_API_TOKEN:-}" ]; then
  echo "OpenShift API target: ${OCP_API_BASE_URL}"
  echo "OpenShift token: configured"
  tls_flag=""
  case "${OCP_INSECURE_SKIP_TLS_VERIFY:-true}" in
    1|true|TRUE|yes|YES|on|ON)
      tls_flag="--insecure-skip-tls-verify=true"
      ;;
  esac

  if command -v curl >/dev/null 2>&1; then
    curl_tls_flag=""
    if [ -n "${tls_flag}" ]; then
      curl_tls_flag="-k"
    fi
    if curl ${curl_tls_flag} -fsS --connect-timeout 5 --max-time 10 "${OCP_API_BASE_URL%/}/version" >"${version_log}" 2>&1; then
      echo "OpenShift API /version reachable."
    else
      echo "OpenShift API /version check failed; continuing to oc login."
      sed -E 's/(--token=|token=|Authorization: Bearer )[A-Za-z0-9._~:-]+/\1<redacted>/g' "${version_log}" | tail -n 5
    fi
  fi

  oc login \
    --server="${OCP_API_BASE_URL}" \
    --token="${OCP_API_TOKEN}" \
    ${tls_flag} \
    >"${login_log}" 2>&1

  if [ $? -eq 0 ]; then
    echo "OpenShift CLI login ready: ${OCP_API_BASE_URL}"
    if [ -n "${OCP_DEFAULT_NAMESPACE:-}" ]; then
      oc project "${OCP_DEFAULT_NAMESPACE}" >/tmp/playbookstudio-oc-project.log 2>&1 || true
    fi
    exec /bin/bash -i
  else
    echo "OpenShift CLI login failed for ${OCP_API_BASE_URL}."
    classify_login_failure
    print_login_log_tail
    fail_cluster_terminal
  fi
else
  echo "OpenShift CLI auto-login skipped. oc, OCP_API_BASE_URL, or OCP_API_TOKEN is missing."
  command -v oc >/dev/null 2>&1 || echo "Missing: oc CLI"
  [ -n "${OCP_API_BASE_URL:-}" ] || echo "Missing: OCP_API_BASE_URL"
  [ -n "${OCP_API_TOKEN:-}" ] || echo "Missing: OCP_API_TOKEN"
  fail_cluster_terminal
fi
