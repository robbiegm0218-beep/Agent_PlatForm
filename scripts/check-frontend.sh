#!/bin/sh
set -eu
NODE_BIN="${NODE_BIN:-node}"
"$NODE_BIN" --check web/static/app.js
find web/static/core web/static/chat -type f -name '*.js' -exec "$NODE_BIN" --check {} \;
"$NODE_BIN" scripts/test-frontend-core.mjs
