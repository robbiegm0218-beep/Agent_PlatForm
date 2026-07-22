#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
git check-ignore -q .env
git check-ignore -q .env.local
python3 -m pip check
python3 -m compileall -q server
scripts/check-frontend.sh
echo "security baseline checks passed"
