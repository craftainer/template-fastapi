#!/usr/bin/env bash
# PYTHON_VERSION and DEBIAN_VERSION are declared in both the base-owned
# Dockerfile (develop stage) and app.Dockerfile (builder/runner stages);
# the runtime image must match the interpreter/OS the devcontainer tests
# against. Exits 1 if either differs.
set -euo pipefail

status=0
for arg in PYTHON_VERSION DEBIAN_VERSION; do
    dev="$(grep -m1 "^ARG ${arg}=" Dockerfile | cut -d= -f2-)"
    app="$(grep -m1 "^ARG ${arg}=" app.Dockerfile | cut -d= -f2-)"
    if [[ "$dev" != "$app" ]]; then
        echo "${arg} mismatch: Dockerfile has '${dev}', app.Dockerfile has '${app}'" >&2
        status=1
    fi
done
exit "$status"
