# OpenShift Deployment

This directory deploys PlayBookStudio into OpenShift namespace `pbs-ocpops`.

`PBS-OCPOps` is used as a display label only because Kubernetes namespace names
must be lowercase DNS labels.

## Server Setup

From the OCP-connected server:

```bash
mkdir -p ~/playbookstudio-ocp
cd ~/playbookstudio-ocp
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/core.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/app.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/job-db-migrate.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/job-official-corpus-seed.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/job-kmsc-corpus-seed.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/job-course-runtime-seed.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/job-qdrant-seed.yaml
curl -L -O https://raw.githubusercontent.com/JungyuOO/OCPOps-PlaybookStudio/dev/deploy/openshift/apply-playbookstudio.sh
chmod +x apply-playbookstudio.sh
```

Login and deploy:

```bash
oc login https://api.ocp.cywell.local:6443 \
  -u admin \
  -p admin123 \
  --insecure-skip-tls-verify=true

export OCP_API_TOKEN="$(oc whoami -t)"
export POSTGRES_PASSWORD="admin123"

./apply-playbookstudio.sh
```

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
```

Open the `playbookstudio` Route host in a browser.
