#!/usr/bin/env bash
set -euo pipefail

# One-command local run for MetaGate
# Requires Docker Desktop + docker compose.

docker compose up --build
