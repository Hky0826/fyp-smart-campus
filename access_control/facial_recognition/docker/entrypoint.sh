#!/usr/bin/env sh
set -eu

if [ "${EDGE_REQUIRE_HAILORT:-1}" != "0" ]; then
    python -m edge.facial_recognition.src.hailo.diagnostics
fi

exec "$@"
