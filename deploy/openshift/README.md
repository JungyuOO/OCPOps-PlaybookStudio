# OpenShift Deployment

This directory deploys PlayBookStudio into OpenShift namespace `pbs-ocpops`.

`PBS-OCPOps` is used as a display label only because Kubernetes namespace names
must be lowercase DNS labels.

## Git-Sourced Deployment

This deployment directory is Kustomize-compatible. Do not download each YAML
file manually for normal operations. Apply the Git source directly from the
OCP-connected server after the `dev` branch and GHCR `:dev` images are updated.

Login:

```bash
oc login https://api.ocp.cywell.local:6443 \
  -u admin \
  -p admin123 \
  --insecure-skip-tls-verify=true
```

Create or update the runtime secret. Keep these values out of Git:

```bash
oc create namespace pbs-ocpops --dry-run=client -o yaml | oc apply -f -

export POSTGRES_PASSWORD="admin123"

oc create secret generic playbookstudio-secret \
  -n pbs-ocpops \
  --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  --from-literal=DATABASE_URL="postgresql://admin:${POSTGRES_PASSWORD}@postgres:5432/playbookstudio" \
  --from-literal=OCP_API_TOKEN="$(oc whoami -t)" \
  --dry-run=client -o yaml | oc apply -f -
```

Apply the Git source:

```bash
oc apply -k "https://github.com/JungyuOO/OCPOps-PlaybookStudio//deploy/openshift?ref=dev"
```

For one-shot seed Jobs, delete completed Jobs before re-applying if the seed
must run again:

```bash
oc delete job db-migrate official-corpus-seed kmsc-corpus-seed learning-seed course-runtime-seed qdrant-seed \
  -n pbs-ocpops \
  --ignore-not-found=true

oc apply -k "https://github.com/JungyuOO/OCPOps-PlaybookStudio//deploy/openshift?ref=dev"
```

## Scripted Local Checkout Deployment

Use this only when remote Kustomize is unavailable in the installed `oc`
client. Keep a checkout or artifact directory on the OCP-connected server, then
run `./apply-playbookstudio.sh`.

## Stop Previous Ubuntu Docker Deployment

```bash
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/cleanup-ubuntu-compose.sh
chmod +x cleanup-ubuntu-compose.sh
./cleanup-ubuntu-compose.sh
```

The cleanup script stops containers but preserves Docker volumes.

## Verify

```bash
oc get pods -n pbs-ocpops
oc get route -n pbs-ocpops
oc logs job/official-corpus-seed -n pbs-ocpops --tail=80
oc logs job/kmsc-corpus-seed -n pbs-ocpops --tail=80
oc logs job/learning-seed -n pbs-ocpops --tail=80
```

Open the `playbookstudio` Route host in a browser.
