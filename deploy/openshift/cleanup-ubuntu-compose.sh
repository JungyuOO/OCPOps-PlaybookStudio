#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-${HOME}/playbookstudio-image}"

if [[ ! -f "${DEPLOY_DIR}/docker-compose.image.yml" ]]; then
  echo "Compose file not found: ${DEPLOY_DIR}/docker-compose.image.yml"
  exit 0
fi

cd "${DEPLOY_DIR}"
sudo docker compose -f docker-compose.image.yml --env-file .env down --remove-orphans

echo
echo "Stopped Ubuntu Docker Compose deployment."
echo "Volumes were preserved. To remove unused image layers later, run:"
echo "  sudo docker image prune"
