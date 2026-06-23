#!/usr/bin/env bash
set -euo pipefail

TARGET_VERSION="${HAILORT_TARGET_VERSION:-4.23.0}"

section() {
  printf '\n== %s ==\n' "$1"
}

run() {
  printf '+ %s\n' "$*"
  "$@" || true
}

section "Hailo device"
run ls -l /dev/hailo0
if command -v fuser >/dev/null 2>&1; then
  run fuser -v /dev/hailo0
fi
run sh -c 'ps -ef | grep -E "edge|uvicorn|python" | grep -v grep'
run lsmod
if command -v modinfo >/dev/null 2>&1; then
  run modinfo hailo_pci
fi

section "HailoRT CLI and loaded library"
if command -v hailortcli >/dev/null 2>&1; then
  HAILORTCLI_PATH="$(command -v hailortcli)"
  echo "hailortcli: ${HAILORTCLI_PATH}"
  run hailortcli --version
  if command -v ldd >/dev/null 2>&1; then
    run ldd "${HAILORTCLI_PATH}"
  fi
else
  echo "hailortcli was not found on PATH."
fi

section "Installed Hailo packages"
run sh -c 'dpkg -l | grep -Ei "hailo|hailort"'

section "Available Hailo apt versions"
if command -v apt-cache >/dev/null 2>&1; then
  run apt-cache policy hailort hailort-pcie-driver hailo-all
  run apt-cache madison hailort hailort-pcie-driver hailo-all
  run apt-cache search hailo
fi

section "HailoRT library files"
run sh -c 'find /usr /opt -name "libhailort.so*" -exec ls -l {} \; 2>/dev/null'
if command -v ldconfig >/dev/null 2>&1; then
  run sh -c 'ldconfig -p | grep -i hailort'
fi

section "Python Hailo packages"
run sh -c 'find /usr /opt -name "hailo_platform" -o -name "*hailort*.whl" 2>/dev/null'
for python_bin in python3 python3.11 python3.10 /usr/bin/python3 /usr/bin/python3.11 /usr/bin/python3.10; do
  if command -v "${python_bin}" >/dev/null 2>&1 || [[ -x "${python_bin}" ]]; then
    echo "-- ${python_bin} --"
    "${python_bin}" --version || true
    "${python_bin}" - <<'PY' || true
import sys
print("executable:", sys.executable)
print("sys.path:")
for path in sys.path:
    print(" ", path)
try:
    import hailo_platform
    print("hailo_platform: OK", getattr(hailo_platform, "__file__", None))
except Exception as exc:
    print("hailo_platform: FAIL", repr(exc))
PY
  fi
done

section "Suggested repair commands"
cat <<EOF
Your target is one consistent HailoRT version across driver and library.
For your current error, prefer ${TARGET_VERSION} because the driver is ${TARGET_VERSION}.

1. Check the exact apt version strings above. If ${TARGET_VERSION} is available, run:
   sudo apt update
   sudo apt install --reinstall hailort=${TARGET_VERSION} hailort-pcie-driver=${TARGET_VERSION}
   sudo ldconfig
   sudo reboot

2. If apt shows versions like ${TARGET_VERSION}-1, use that exact string:
   sudo apt install --reinstall hailort=${TARGET_VERSION}-1 hailort-pcie-driver=${TARGET_VERSION}-1

3. If apt cannot provide ${TARGET_VERSION}, install matching vendor .deb files instead:
   sudo dpkg -i hailort_${TARGET_VERSION}_arm64.deb hailort-pcie-driver_${TARGET_VERSION}_all.deb
   sudo apt -f install -y
   sudo ldconfig
   sudo reboot

4. If a stale 4.22 lib appears before 4.23 in ldconfig/ldd output, remove the package that owns it:
   dpkg -S /path/to/libhailort.so.4.22.0
   sudo apt remove <owning-package>
   sudo ldconfig

After reboot, verify:
   hailortcli --version
   python3 -m edge.src.hailo.diagnostics
EOF
