#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCESS_DIR="${ROOT_DIR}/models/access_control"

mkdir -p "${ACCESS_DIR}"

YUNET_URL="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar_int8bq.onnx"
SFACE_URL="https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

download_if_missing() {
  local filename="$1"
  local url="$2"
  local dest="${ACCESS_DIR}/${filename}"

  if [[ -f "${dest}" ]]; then
    echo "Already present: ${dest}"
  else
    echo "Downloading ${filename}..."
    curl -L --fail "${url}" -o "${dest}"
    echo "Downloaded ${filename} successfully."
  fi
}

download_if_missing "face_detection_yunet_2023mar_int8bq.onnx" "${YUNET_URL}"
download_if_missing "face_recognition_sface_2021dec.onnx" "${SFACE_URL}"
