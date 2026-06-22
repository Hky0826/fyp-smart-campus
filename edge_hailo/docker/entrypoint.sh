#!/usr/bin/env sh
set -eu

if [ "${EDGE_HAILO_REQUIRE_HAILORT:-1}" != "0" ]; then
    python -m edge_hailo.src.hailo.diagnostics
fi

exec "$@"
