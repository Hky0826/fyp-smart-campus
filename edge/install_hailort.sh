#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
PTH_FILE_NAME="edge_hailort_system.pth"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO_CMD=()
else
  SUDO_CMD=("${SUDO:-sudo}")
fi

cd "${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

log() {
  echo "[edge][hailort] $*"
}

python_exec() {
  "${PYTHON_BIN}" -c 'import sys; print(sys.executable)'
}

python_version() {
  "${PYTHON_BIN}" -c 'import sys; print("{}.{}.{}".format(*sys.version_info[:3]))'
}

python_major_minor() {
  local python_bin="$1"
  "${python_bin}" -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))'
}

in_virtualenv() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else 1)
PY
}

run_diagnostics() {
  "${PYTHON_BIN}" -m edge.src.hailo.diagnostics || true
}

python_can_import_hailort() {
  local python_bin="$1"
  "${python_bin}" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("hailo_platform")
PY
}

hailort_importable() {
  python_can_import_hailort "${PYTHON_BIN}"
}

finish_if_ready() {
  if hailort_importable; then
    log "hailo_platform is importable in $(python_exec)."
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

active_site_packages() {
  "${PYTHON_BIN}" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
}

system_hailort_package_dir() {
  local system_python="$1"
  "${system_python}" - <<'PY'
from pathlib import Path
import importlib.util

spec = importlib.util.find_spec("hailo_platform")
if spec is None or spec.origin is None:
    raise SystemExit(1)
origin = Path(spec.origin).resolve()
if origin.name == "__init__.py":
    print(origin.parent.parent)
else:
    print(origin.parent)
PY
}

system_python_candidates() {
  local current
  current="$(python_exec)"
  for candidate in /usr/bin/python3 /usr/bin/python3.11 /usr/bin/python3.10 /usr/local/bin/python3 /usr/local/bin/python3.11 /usr/local/bin/python3.10; do
    if [[ -x "${candidate}" && "${candidate}" != "${current}" ]]; then
      echo "${candidate}"
    fi
  done
}

bridge_system_hailort_into_venv() {
  if ! in_virtualenv; then
    return 1
  fi

  local system_python=""
  local package_dir=""
  local active_major_minor
  active_major_minor="$(python_major_minor "${PYTHON_BIN}")"

  for candidate in $(system_python_candidates); do
    if [[ "$(python_major_minor "${candidate}")" != "${active_major_minor}" ]]; then
      log "Skipping ${candidate}; it does not match active Python ${active_major_minor}."
      continue
    fi
    if python_can_import_hailort "${candidate}"; then
      system_python="${candidate}"
      package_dir="$(system_hailort_package_dir "${candidate}")"
      break
    fi
  done

  if [[ -z "${system_python}" || -z "${package_dir}" || ! -d "${package_dir}" ]]; then
    return 1
  fi

  local venv_site
  venv_site="$(active_site_packages)"
  mkdir -p "${venv_site}"

  log "System Python can import hailo_platform: ${system_python}"
  log "Adding HailoRT package path to active venv: ${package_dir}"
  printf '%s\n' "${package_dir}" > "${venv_site}/${PTH_FILE_NAME}"

  if hailort_importable; then
    log "Linked system HailoRT into the active virtualenv."
    return 0
  fi

  log "Created ${venv_site}/${PTH_FILE_NAME}, but hailo_platform is still not importable."
  return 1
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
[edge][hailort] HailoRT installer helper
[edge][hailort] Project root: ${PROJECT_ROOT}
[edge][hailort] Python: $(python_exec)
[edge][hailort] Python version: $(python_version)
EOF

if in_virtualenv; then
  log "Active Python is a virtualenv. The script will also check system Python for HailoRT and link it into this venv if needed."
fi

log "Running current diagnostics."
run_diagnostics
finish_if_ready

log "hailo_platform is not importable in the active Python yet. Trying installation sources."

if bridge_system_hailort_into_venv; then
  finish_if_ready
fi

if install_wheel; then
  finish_if_ready
fi

if install_debs; then
  if bridge_system_hailort_into_venv; then
    finish_if_ready
  fi
  finish_if_ready
fi

if install_apt_packages; then
  if bridge_system_hailort_into_venv; then
    finish_if_ready
  fi
  finish_if_ready
fi

cat <<'EOF'

[edge][hailort] Could not make hailo_platform importable automatically.

For your diagnostic shape, the most common cause is an isolated .venv:
  hailo_device: true
  python_executable: /path/to/project/.venv/bin/python3
  hailo_platform_importable: false

Try these checks on the EdgeMind device:
  /usr/bin/python3 -c "import hailo_platform; print('system HailoRT OK')"
  python3 -c "import sys; print(sys.executable); print(sys.prefix); print(getattr(sys, 'base_prefix', sys.prefix))"

If system Python can import HailoRT, rerun this script while the venv is active:
  bash edge/install_hailort.sh

If system Python cannot import HailoRT, install the EdgeMind/HailoRT package first:
  sudo apt update
  sudo apt install hailo-all

Or provide the vendor package explicitly:
  HAILORT_WHEEL=/path/to/hailort-...whl bash edge/install_hailort.sh
  HAILORT_DEB_DIR=/path/to/deb/folder bash edge/install_hailort.sh

After installing or updating the Hailo driver, reboot:
  sudo reboot

Then verify again:
  python3 -m edge.src.hailo.diagnostics
EOF

exit 1
