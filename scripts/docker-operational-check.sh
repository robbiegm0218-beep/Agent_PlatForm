#!/usr/bin/env bash
# Read-only daily health check for the Docker-hosted personal instance.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
docker_bin="$(command -v docker)"
container_id="$($docker_bin ps -q --filter 'label=com.docker.compose.project=agent' --filter 'label=com.docker.compose.service=agent-platform')"

if [[ -z "$container_id" ]]; then
  echo "CRITICAL: Agent_Platform Docker container is not running."
  exit 2
fi

exec "$docker_bin" exec "$container_id" \
  python -m server.operational_monitor \
  --database /data/agent_platform.db \
  --data-dir /data \
  --backup-root /data/upgrade-backups
