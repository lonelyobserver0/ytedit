#!/usr/bin/env bash
#
# Starts ytEdit, preparing the environment only when it is needed.
#   ./run.sh              start the application
#   ./run.sh --xcb        force X11 (mpv preview embedded on Wayland)
#   ./run.sh --update     bring the dependencies back in line
#   ./run.sh --check      check the environment without starting anything

set -euo pipefail

# realpath: lo script deve funzionare anche se richiamato via symlink.
root="$(cd -- "$(dirname -- "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
cd "$root"

venv="$root/.venv"
python="$venv/bin/python"
stamp="$venv/.deps-stamp"
requirements="$root/requirements.txt"

_info() { echo "→ $*"; }
_warn() { echo "! $*" >&2; }
_die() { echo "✖ $*" >&2; exit 1; }

do_update=0
do_check=0
force_xcb=0
force_wayland=0
app_args=()

while (($# > 0)); do
    case "$1" in
        -h | --help)
            echo "Usage: run.sh [options] [arguments for main.py]"
            echo
            echo "  -u, --update   reinstall/upgrade the Python dependencies"
            echo "  -x, --xcb      force QT_QPA_PLATFORM=xcb (already the default on"
            echo "                 Wayland when XWayland is available)"
            echo "  -w, --wayland  stay on native Wayland: the mpv preview opens"
            echo "                 in a separate window"
            echo "  -c, --check    check the environment and dependencies, then exit"
            echo "  -h, --help     show this message"
            exit 0
            ;;
        -u | --update) do_update=1 ;;
        -x | --xcb) force_xcb=1 ;;
        -w | --wayland) force_wayland=1 ;;
        -c | --check) do_check=1 ;;
        *) app_args+=("$1") ;;
    esac
    shift
done

# --- interprete di sistema -------------------------------------------------

system_python=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        system_python="$candidate"
        break
    fi
done
[[ -n "$system_python" ]] || _die "Python not found in the PATH."

if ! "$system_python" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
    _die "Python 3.9 or newer is required."
fi

# --- ambiente virtuale -----------------------------------------------------

if [[ ! -x "$python" ]]; then
    _info "Creating the virtual environment in .venv"
    "$system_python" -m venv "$venv" || _die "Could not create the virtual environment."
    rm -f "$stamp"
fi

# Reinstalla solo se requirements.txt è cambiato dopo l'ultima installazione:
# l'avvio normale non deve aspettare pip ogni volta.
if ((do_update)) || [[ ! -f "$stamp" ]] || [[ "$requirements" -nt "$stamp" ]]; then
    _info "Installing the Python dependencies"
    "$python" -m pip install --upgrade pip --quiet || _warn "Could not upgrade pip."
    "$python" -m pip install -r "$requirements" --upgrade --quiet \
        || _die "Could not install the dependencies (try again with --update)."
    touch "$stamp"
fi

# --- dipendenze di sistema -------------------------------------------------

missing=()
for tool in ffmpeg ffprobe; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ((${#missing[@]} > 0)); then
    # ${array[*]} unisce col PRIMO carattere di IFS, uno solo: per ", " serve printf.
    list="$(printf '%s, ' "${missing[@]}")"
    _die "${list%, } missing from the PATH. On Arch: sudo pacman -S ffmpeg"
fi
command -v mpv >/dev/null 2>&1 \
    || _warn "mpv not found: the video preview will be disabled (sudo pacman -S mpv)."

# --- piattaforma Qt --------------------------------------------------------

if ((force_wayland)); then
    export QT_QPA_PLATFORM=wayland
    _info "Native Wayland requested: the mpv preview will be in a separate window."
elif ((force_xcb)); then
    if [[ -z "${DISPLAY:-}" ]]; then
        _warn "No X11 DISPLAY available: ignoring --xcb."
    else
        export QT_QPA_PLATFORM=xcb
        _info "Qt platform forced to xcb (mpv preview embedded)."
    fi
fi
# Senza flag decide main.py: xcb su Wayland se XWayland c'è, per l'anteprima.

# --- avvio -----------------------------------------------------------------

if ((do_check)); then
    "$python" -m ytedit.doctor || _die "Check failed: sort out the items marked above."
    _info "Environment ready."
    exit 0
fi

exec "$python" "$root/main.py" ${app_args[@]+"${app_args[@]}"}
