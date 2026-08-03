#!/usr/bin/env bash
set -euo pipefail

python3 -m server.evaluate_auto_knowledge_routing --policy v2-strong
python3 -m server.evaluate_knowledge_retrieval
python3 -m server.evaluate_knowledge_hybrid
python3 -m server.evaluate_knowledge_configuration
python3 -m unittest discover -s server -p 'test_*.py'
node scripts/test-frontend-core.mjs
node --check web/static/app.js
node --check web/static/views/knowledge-configuration.js
node --check web/static/views/audit.js
python3 -m compileall -q server
git diff --check
