#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_USER="${PI_USER:-sunzhuofan}"
PI_PORT="${PI_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/home/sunzhuofan/Desktop/ParcelBox}"

echo "Syncing ${PROJECT_ROOT} -> ${PI_USER}@${PI_HOST}:${REMOTE_DIR}"

rsync \
  -az \
  --delete \
  --human-readable \
  --info=progress2 \
  --exclude ".git/" \
  --exclude ".idea/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude ".DS_Store" \
  --exclude "data/" \
  --exclude "drivers/camera_test.jpg" \
  -e "ssh -p ${PI_PORT}" \
  "${PROJECT_ROOT}/" \
  "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

echo "Sync complete."
