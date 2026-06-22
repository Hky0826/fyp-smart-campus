#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO_CMD=()
else
  SUDO_CMD=("${SUDO:-sudo}")
fi

cd "${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

log() {
  echo "[edge_hailo][hailort] $*"
}

run_diagnostics() {
  "${PYTHON_BIN}" -m edge_hailo.src.hailo.diagnostics || true
}

hailort_importable() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("hailo_platform")
PY
}

finish_if_ready() {
  if hailort_importable; then
    log "hailo_platform is importable. HailoRT Python bindings are ready."
    run_diagnostics
    if [[ ! -e /dev/hailo0 ]]; then
      log "Warning: /dev/hailo0 was not found. If this is the EdgeMind device, install/load the Hailo PCIe driver or reboot after installing HailoRT."
    fi
    if command -v hailortcli >/dev/null 2>&1; then
      log "Running hailortcli scan..."
      hailortcli scan || true
    fi
    exit 0
  fi
}

install_wheel() {
  local wheel="${HAILORT_WHEEL:-${HAILORT_WHEEL_PATH:-}}"
  if [[ -z "${wheel}" ]]; then
    local old_nullglob
    old_nullglob="$(shopt -p nullglob || true)"
    shopt -s nullglob
    local wheels=("${ROOT_DIR}"/vendor/hailort*.whl "${ROOT_DIR}"/vendor/pyhailort*.whl)
    eval "${old_nullglob}"
    if [[ ${#wheels[@]} -eq 1 && -f "${wheels[0]}" ]]; then
      wheel="${wheels[0]}"
    fi
  fi

  if [[ -z "${wheel}" ]]; then
    return 1
  fi
  if [[ ! -f "${wheel}" ]]; then
    log "HAILORT_WHEEL is set, but the file does not exist: ${wheel}"
    return 1
  fi

  log "Installing HailoRT Python wheel with ${PYTHON_BIN}: ${wheel}"
  "${PYTHON_BIN}" -m pip install "${wheel}"
}

install_debs() {
  local deb_dir="${HAILORT_DEB_DIR:-}"
  if [[ -z "${deb_dir}" && -d "${ROOT_DIR}/vendor/debs" ]]; then
    deb_dir="${ROOT_DIR}/vendor/debs"
  fi
  if [[ -z "${deb_dir}" ]]; then
    return 1
  fi
  if [[ ! -d "${deb_dir}" ]]; then
    log "HAILORT_DEB_DIR is set, but the directory does not exist: ${deb_dir}"
    return 1
  fi

  local debs=("${deb_dir}"/*.deb)
  if [[ ${#debs[@]} -eq 0 || ! -f "${debs[0]}" ]]; then
    log "No .deb files found in: ${deb_dir}"
    return 1
  fi

  log "Installing local HailoRT .deb packages from: ${deb_dir}"
  "${SUDO_CMD[@]}" apt-get update
  "${SUDO_CMD[@]}" apt-get install -y "${debs[@]}"
}

apt_has_package() {
  apt-cache show "$1" >/dev/null 2>&1
}

install_apt_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get is not available on this system."
    return 1
  fi

  log "Checking apt for HailoRT packages."
  if [[ "${HAILORT_SKIP_APT_UPDATE:-0}" != "1" ]]; then
    "${SUDO_CMD[@]}" apt-get update
  fi

  if [[ -n "${HAILORT_APT_PACKAGES:-}" ]]; then
    log "Installing packages from HAILORT_APT_PACKAGES: ${HAILORT_APT_PACKAGES}"
    # shellcheck disable=SC2086
    "${SUDO_CMD[@]}" apt-get install -y ${HAILORT_APT_PACKAGES}
    return 0
  fi

  if apt_has_package hailo-all; then
    log "Installing apt package: hailo-all"
    "${SUDO_CMD[@]}" apt-get install -y hailo-all
    return 0
  fi

  local packages=()
  for package in python3-hailort hailort hailort-pcie-driver; do
    if apt_has_package "${package}"; then
      packages+=("${package}")
    fi
  done

  if [[ ${#packages[@]} -eq 0 ]]; then
    log "No known HailoRT apt packages were found."
    return 1
  fi

  log "Installing apt packages: ${packages[*]}"
  "${SUDO_CMD[@]}" apt-get install -y "${packages[@]}"
}

cat <<EOF
[edge_hailo][hailort] HailoRT installer helper
[edge_hailo][hailort] Project root: ${PROJECT_ROOT}
[edge_hailo][hailort] Python: $(${PYTHON_BIN} -c 'import sys; print(sys.executable)')
EOF

log "Running current diagnostics."
run_diagnostics
finish_if_ready

log "hailo_platform is not importable yet. Trying installation sources."

if install_wheel; then
  finish_if_ready
fi

if install_debs; then
  finish_if_ready
fi

if install_apt_packages; then
  finish_if_ready
fi

cat <<'EOF'

[edge_hailo][hailort] Could not make hailo_platform importable automatically.

What to do next:
  1. Get the HailoRT package that matches the EdgeMind OS, CPU architecture, and Python version.
  2. If you received a Python wheel, run:
       HAILORT_WHEEL=/path/to/hailort-...whl bash edge_hailo/install_hailort.sh
  3. If you received .deb files, run:
       HAILORT_DEB_DIR=/path/to/deb/folder bash edge_hailo/install_hailort.sh
  4. If your apt repository uses different package names, run:
       HAILORT_APT_PACKAGES="package1 package2" bash edge_hailo/install_hailort.sh

After installation, reboot the device if the Hailo driver was installed or updated:
  sudo reboot

Then verify again:
  python3 -m edge_hailo.src.hailo.diagnostics
EOF

exit 1
