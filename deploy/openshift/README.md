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

## Verify BGE Reranker

The reranker runs on the Ubuntu host as Docker container `bge-reranker` and is
published to OpenShift through Service `bge-reranker` plus EndpointSlice
`bge-reranker-external`. This keeps the large model out of the single-node
OpenShift resource pool.

Host-side container:

```bash
docker run -d \
  --name bge-reranker \
  --restart no \
  --memory=6g \
  --memory-swap=8g \
  --cpus=2 \
  -p 8082:80 \
  -v ~/bge-reranker-cache:/data \
  ghcr.io/huggingface/text-embeddings-inference:cpu-latest \
  --model-id BAAI/bge-reranker-v2-m3 \
  --max-client-batch-size 1 \
  --max-batch-tokens 4096
```

Check host health before applying the OpenShift app:

```bash
curl -v --max-time 5 http://127.0.0.1:8082/health
docker inspect bge-reranker --format 'Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}} Restart={{.HostConfig.RestartPolicy.Name}}'
docker stats --no-stream bge-reranker
```

Then verify from inside the namespace:

```bash
oc -n pbs-ocpops run reranker-smoke --rm -it --restart=Never \
  --image=curlimages/curl:latest \
  -- curl -sS -X POST http://bge-reranker/rerank \
    -H 'Content-Type: application/json' \
    --data '{"query":"Route timeout 어디서 확인해?","texts":["OpenShift Route timeout is configured on HAProxy router annotations.","HSTS policy configures strict transport security for routes."],"raw_scores":true,"return_text":false,"truncate":true}'
```

## Local RAG Quality Eval Through OCP Reranker

Local CLI eval can use the in-cluster reranker after the service is deployed.
Keep one terminal on the OCP-connected Ubuntu server:

```bash
oc -n pbs-ocpops port-forward svc/bge-reranker 8081:80 --address 127.0.0.1
```

From Windows, open an SSH tunnel to that server-side port:

```powershell
ssh -L 8081:127.0.0.1:8081 cywell@192.168.119.23
```

Then run the local smoke and answer-quality eval:

```powershell
.\deploy\local-reranker-quality-eval.ps1
```

Use a wider case set when the quick v0.1.2 beginner set is clean:

```powershell
.\deploy\local-reranker-quality-eval.ps1 `
  -Cases corpus/manifests/eval/pbs_chat_quality_extended_cases.jsonl `
  -TopK 5 `
  -CandidateK 24 `
  -MaxContextChunks 8
```

This verifies local RAG quality with the same `/rerank` API shape. It does not
replace in-cluster performance testing because local eval still uses the local
runtime, local database/Qdrant settings, and SSH/port-forward networking.
