#!/usr/bin/env bash
# Install or replace per-user launchd jobs for Docker maintenance.
set -euo pipefail
root_dir="$(cd "$(dirname "$0")/.." && pwd)"
agent_dir="$HOME/Library/LaunchAgents"
maintenance_dir="$HOME/Library/Application Support/Agent_Platform"
log_dir="$HOME/Library/Logs/Agent_Platform"
mkdir -p "$agent_dir" "$maintenance_dir" "$log_dir"
cp "$root_dir/scripts/docker-operational-check.sh" "$maintenance_dir/"
cp "$root_dir/scripts/docker-upgrade-snapshot.sh" "$maintenance_dir/"
chmod 755 "$maintenance_dir"/docker-*.sh

for job in daily-check daily-snapshot; do
  template="$root_dir/scripts/com.agent-platform.${job}.plist.template"
  target="$agent_dir/com.agent-platform.${job}.plist"
  sed -e "s|__MAINTENANCE_DIR__|$maintenance_dir|g" -e "s|__LOG_DIR__|$log_dir|g" "$template" > "$target"
  launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$target"
done

echo "已安装：每日 02:00 Docker 数据快照、每日 09:00 运维检查。"
echo "维护脚本：$maintenance_dir"
echo "日志目录：$log_dir"
