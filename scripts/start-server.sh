#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON_BINARY:-python3}" -m server
