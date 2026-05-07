#!/usr/bin/env bash
set +e

export KUBECONFIG="${KUBECONFIG:-/tmp/playbookstudio-kubeconfig}"

if command -v oc >/dev/null 2>&1 && [ -n "${OCP_API_BASE_URL:-}" ] && [ -n "${OCP_API_TOKEN:-}" ]; then
  tls_flag=""
  case "${OCP_INSECURE_SKIP_TLS_VERIFY:-true}" in
    1|true|TRUE|yes|YES|on|ON)
      tls_flag="--insecure-skip-tls-verify=true"
      ;;
  esac

  oc login \
    --server="${OCP_API_BASE_URL}" \
    --token="${OCP_API_TOKEN}" \
    ${tls_flag} \
    >/tmp/playbookstudio-oc-login.log 2>&1

  if [ $? -eq 0 ]; then
    echo "OpenShift CLI login ready: ${OCP_API_BASE_URL}"
    if [ -n "${OCP_DEFAULT_NAMESPACE:-}" ]; then
      oc project "${OCP_DEFAULT_NAMESPACE}" >/tmp/playbookstudio-oc-project.log 2>&1 || true
    fi
  else
    echo "OpenShift CLI login failed. See /tmp/playbookstudio-oc-login.log"
  fi
else
  echo "OpenShift CLI auto-login skipped. oc, OCP_API_BASE_URL, or OCP_API_TOKEN is missing."
fi

exec /bin/bash -i
