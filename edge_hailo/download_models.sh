#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCESS_DIR="${ROOT_DIR}/models/access_control"
SURVEILLANCE_DIR="${ROOT_DIR}/models/surveillance"

mkdir -p "${ACCESS_DIR}" "${SURVEILLANCE_DIR}"

copy_if_available() {
  local filename="$1"
  local destination="$2"
  if [[ -n "${HAILO_HEF_SOURCE_DIR:-}" && -f "${HAILO_HEF_SOURCE_DIR}/${filename}" ]]; then
    cp "${HAILO_HEF_SOURCE_DIR}/${filename}" "${destination}/${filename}"
    echo "Copied ${filename} from HAILO_HEF_SOURCE_DIR"
    return 0
  fi
  return 1
}

download_if_url_set() {
  local env_name="$1"
  local filename="$2"
  local destination="$3"
  local url="${!env_name:-}"
  if [[ -n "${url}" ]]; then
    curl -L --fail "${url}" -o "${destination}/${filename}"
    echo "Downloaded ${filename} from ${env_name}"
    return 0
  fi
  return 1
}

ensure_model() {
  local filename="$1"
  local destination="$2"
  local url_env="$3"
  if [[ -f "${destination}/${filename}" ]]; then
    echo "Already present: ${destination}/${filename}"
    return
  fi
  copy_if_available "${filename}" "${destination}" && return
  download_if_url_set "${url_env}" "${filename}" "${destination}" && return

  echo "Missing ${destination}/${filename}"
}

ensure_model "arcface_mobilefacenet.hef" "${ACCESS_DIR}" "ARCFACE_MOBILEFACENET_HEF_URL"
ensure_model "scrfd_10g.hef" "${SURVEILLANCE_DIR}" "SCRFD_10G_HEF_URL"
ensure_model "arcface_r50.hef" "${SURVEILLANCE_DIR}" "ARCFACE_R50_HEF_URL"

cat <<'EOF'

Model placement required:
  edge_hailo/models/access_control/arcface_mobilefacenet.hef
  edge_hailo/models/surveillance/scrfd_10g.hef  # shared detector for access control and surveillance
  edge_hailo/models/surveillance/arcface_r50.hef

If your Hailo Model Zoo package provides precompiled HEFs, set:
  HAILO_HEF_SOURCE_DIR=/path/to/hef/files

If your organization has authenticated download URLs, set:
  ARCFACE_MOBILEFACENET_HEF_URL=...
  SCRFD_10G_HEF_URL=...
  ARCFACE_R50_HEF_URL=...

Otherwise download or compile these HEFs with the official Hailo Model Zoo tools
for the target hardware, then place each file at the path shown above.
EOF
