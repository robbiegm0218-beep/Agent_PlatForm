#!/bin/sh
set -eu
NODE_BIN="${NODE_BIN:-node}"
"$NODE_BIN" --check web/static/app.js
find web/static/core web/static/chat web/static/knowledge web/static/space web/static/views -type f -name '*.js' -exec "$NODE_BIN" --check {} \;
"$NODE_BIN" scripts/test-frontend-core.mjs

# Keep the stylesheet entrypoint and its ordered layers intact.  CSS has no
# built-in parser in this zero-build frontend, so verify the layer files that
# the entrypoint imports are present and non-empty.
for stylesheet in \
  web/static/styles/tokens-base.css \
  web/static/styles/layout.css \
  web/static/styles/space.css \
  web/static/styles/chat.css \
  web/static/styles/knowledge.css \
  web/static/styles/components.css \
  web/static/styles/responsive.css
do
  test -s "$stylesheet"
done
