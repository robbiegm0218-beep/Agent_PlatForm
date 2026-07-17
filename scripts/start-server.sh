#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m server
