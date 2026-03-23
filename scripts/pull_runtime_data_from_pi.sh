#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PI_HOST="${PI_HOST:-sunzhuofan.local}"
PI_USER="${PI_USER:-sunzhuofan}"
PI_PORT="${PI_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/home/sunzhuofan/Desktop/ParcelBox}"

LOCAL_DB_PATH="${PROJECT_ROOT}/iot_locker.db"
LOCAL_SNAPSHOT_DIR="${PROJECT_ROOT}/data/snapshots"
REMOTE_DB_PATH="${REMOTE_DIR}/iot_locker.db"
REMOTE_SNAPSHOT_DIR="${REMOTE_DIR}/data/snapshots/"

mkdir -p "${PROJECT_ROOT}/data"
mkdir -p "${LOCAL_SNAPSHOT_DIR}"

echo "Pulling runtime data from ${PI_USER}@${PI_HOST}:${REMOTE_DIR}"

rsync \
  -az \
  --human-readable \
  --progress \
  -e "ssh -p ${PI_PORT}" \
  "${PI_USER}@${PI_HOST}:${REMOTE_DB_PATH}" \
  "${LOCAL_DB_PATH}"

rsync \
  -az \
  --delete \
  --human-readable \
  --progress \
  -e "ssh -p ${PI_PORT}" \
  "${PI_USER}@${PI_HOST}:${REMOTE_SNAPSHOT_DIR}" \
  "${LOCAL_SNAPSHOT_DIR}/"

echo "Pull complete."
