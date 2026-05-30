#!/usr/bin/env bash
# Setup and launch script for mimaki-gui
# Usage:  ./run.sh                     — check env, then launch
#         ./run.sh --check-only        — check env only, don't launch
#         ./run.sh --system-packages   — inherit system Python packages (apt/brew)
#                                        into the venv; use this when pip-installed
#                                        PyQt6 is incompatible with the CPU
#         Flags can be combined: ./run.sh --system-packages --check-only
#
# Default mode: isolated .venv/ (packages installed via pip).
# System-packages mode: .venv/ inherits site-packages already installed by the
# system package manager (e.g. python3-pyqt6 from apt), then pip only fills gaps.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
MIN_PYTHON_MINOR=11

# ── Parse arguments ───────────────────────────────────────────────────────────
CHECK_ONLY=false
SYSTEM_PKGS=false
for arg in "$@"; do
    case "$arg" in
        --check-only)      CHECK_ONLY=true ;;
        --system-packages) SYSTEM_PKGS=true ;;
        *) echo "Unknown argument: $arg  (use --check-only, --system-packages)"; exit 1 ;;
    esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${BOLD}$*${NC}"; }

if $SYSTEM_PKGS; then
    info "Mode: system-packages (venv inherits apt/brew site-packages)"
fi

# ── Find a suitable system Python (only needed to create the venv) ─────────────
find_python() {
    for cmd in python3 python3.14 python3.13 python3.12 python3.11; do
        if command -v "$cmd" &>/dev/null; then
            local minor
            minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null) || continue
            if [ "$minor" -ge "$MIN_PYTHON_MINOR" ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

SYS_PYTHON=$(find_python) || {
    fail "Python 3.${MIN_PYTHON_MINOR}+ not found."
    echo "  macOS:  brew install python"
    echo "  Ubuntu: sudo apt install python3"
    exit 1
}
PYVER=$("$SYS_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
ok "Python $PYVER  ($SYS_PYTHON)"

# ── Create / reuse virtual environment ────────────────────────────────────────
# If an existing venv was created with a different --system-site-packages
# setting than what is now requested, recreate it.
if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    if $SYSTEM_PKGS && ! grep -qi "include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg"; then
        info "Recreating .venv/ with --system-site-packages…"
        rm -rf "$VENV_DIR"
    elif ! $SYSTEM_PKGS && grep -qi "include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg"; then
        info "Recreating .venv/ in isolated mode (no system packages)…"
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -f "$VENV_DIR/bin/python" ] && [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo ""
    VENV_FLAGS=""
    $SYSTEM_PKGS && VENV_FLAGS="--system-site-packages"
    info "Creating virtual environment in .venv/ ${VENV_FLAGS}…"
    # shellcheck disable=SC2086
    "$SYS_PYTHON" -m venv $VENV_FLAGS "$VENV_DIR" || {
        fail "Could not create virtual environment."
        echo "  Try: $SYS_PYTHON -m venv $VENV_FLAGS .venv"
        exit 1
    }
    ok "Virtual environment created"
fi

# Use the venv Python for everything from here on
if [ -f "$VENV_DIR/bin/python" ]; then
    PYTHON="$VENV_DIR/bin/python"
else
    PYTHON="$VENV_DIR/bin/python3"
fi
PIP="$PYTHON -m pip"

# ── Check packages ─────────────────────────────────────────────────────────────
echo ""
info "Checking required packages…"

PYQT6_OK=false
SERIAL_OK=false
NUMPY_OK=false

"$PYTHON" -c "from PyQt6 import QtWidgets, QtGui, QtCore" 2>/dev/null && PYQT6_OK=true
"$PYTHON" -c "import serial"  2>/dev/null && SERIAL_OK=true
"$PYTHON" -c "import numpy"   2>/dev/null && NUMPY_OK=true

$PYQT6_OK  && ok "PyQt6"    || warn "PyQt6 — not installed"
$SERIAL_OK && ok "pyserial" || warn "pyserial — not installed"
$NUMPY_OK  && ok "numpy"    || warn "numpy — not installed (simulation feature will not work)"

# ── Install missing packages into the venv ────────────────────────────────────
MISSING=false
$PYQT6_OK  || MISSING=true
$SERIAL_OK || MISSING=true
$NUMPY_OK  || MISSING=true

if $MISSING; then
    echo ""
    info "Installing missing packages into .venv/ …"

    PIP_PKGS=()
    $PYQT6_OK  || PIP_PKGS+=("PyQt6>=6.6")
    $SERIAL_OK || PIP_PKGS+=("pyserial>=3.5")
    $NUMPY_OK  || PIP_PKGS+=("numpy>=1.24")

    $PIP install --upgrade pip --quiet
    $PIP install "${PIP_PKGS[@]}" || {
        fail "pip install failed — see error above."
        echo ""
        if $SYSTEM_PKGS; then
            echo "Running with --system-packages. Make sure the required apt packages"
            echo "are installed, e.g.:"
            echo "  sudo apt install python3-pyqt6 python3-serial python3-numpy"
        else
            echo "You can try manually:"
            echo "  $SYS_PYTHON -m venv .venv"
            echo "  .venv/bin/pip install PyQt6 pyserial numpy"
            echo ""
            echo "If PyQt6 crashes with an Illegal instruction error on this CPU, try:"
            echo "  sudo apt install python3-pyqt6 python3-serial python3-numpy"
            echo "  ./run.sh --system-packages"
        fi
        exit 1
    }

    # Re-check after install
    echo ""
    info "Re-checking after install…"
    "$PYTHON" -c "from PyQt6 import QtWidgets, QtGui, QtCore" 2>/dev/null \
        && ok "PyQt6 OK" \
        || { fail "PyQt6 still not importable after install."; exit 1; }
    "$PYTHON" -c "import serial" 2>/dev/null \
        && ok "pyserial OK" \
        || { fail "pyserial still not importable after install."; exit 1; }
    "$PYTHON" -c "import numpy" 2>/dev/null \
        && ok "numpy OK" \
        || warn "numpy still not available — simulation feature disabled."
fi

# ── Verify application modules ────────────────────────────────────────────────
echo ""
info "Checking application modules…"
IMPORT_RESULT=$("$PYTHON" - 2>&1 <<'PYEOF'
import sys
mods = [
    'app.config',
    'app.model.types',
    'app.model.gcode_object',
    'app.model.project',
    'app.model.zone',
    'app.model.undo',
    'app.io.gcode_parser',
    'app.io.hpgl_parser',
    'app.io.hpgl_writer',
    'app.io.serial_sender',
    'app.io.project_io',
    'app.gui.canvas',
    'app.gui.object_panel',
    'app.gui.send_panel',
    'app.gui.main_window',
]
failed = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        failed.append(f'  {m}: {e}')
if failed:
    print('\n'.join(failed))
    sys.exit(1)
PYEOF
) && ok "All application modules import cleanly" || {
    fail "Import errors detected:"
    echo "$IMPORT_RESULT"
    exit 1
}

if $CHECK_ONLY; then
    echo ""
    ok "Environment check passed. Run ./run.sh to launch."
    exit 0
fi

# ── Launch ────────────────────────────────────────────────────────────────────
echo ""
ok "Starting mimaki-gui…"
exec "$PYTHON" main.py
