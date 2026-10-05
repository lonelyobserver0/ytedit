#!/usr/bin/env fish
#
# Starts ytEdit, preparing the environment only when it is needed.
#   ./run.fish              start the application
#   ./run.fish --xcb        force X11 (mpv preview embedded on Wayland)
#   ./run.fish --update     bring the dependencies back in line
#   ./run.fish --check      check the environment without starting anything

set -l root (dirname (realpath (status filename)))
cd $root; or exit 1

set -l venv $root/.venv
set -l python $venv/bin/python
set -l stamp $venv/.deps-stamp
set -l requirements $root/requirements.txt

function _info; echo "→ $argv"; end
function _warn; echo "! $argv" >&2; end
function _die; echo "✖ $argv" >&2; exit 1; end

set -l do_update 0
set -l do_check 0
set -l force_xcb 0
set -l force_wayland 0
set -l app_args

for arg in $argv
    switch $arg
        case -h --help
            echo "Usage: run.fish [options] [arguments for main.py]"
            echo
            echo "  -u, --update   reinstall/upgrade the Python dependencies"
            echo "  -x, --xcb      force QT_QPA_PLATFORM=xcb (already the default on"
            echo "                 Wayland when XWayland is available)"
            echo "  -w, --wayland  stay on native Wayland: the mpv preview opens"
            echo "                 in a separate window"
            echo "  -c, --check    check the environment and dependencies, then exit"
            echo "  -h, --help     show this message"
            exit 0
        case -u --update
            set do_update 1
        case -x --xcb
            set force_xcb 1
        case -w --wayland
            set force_wayland 1
        case -c --check
            set do_check 1
        case '*'
            set -a app_args $arg
    end
end

# --- interprete di sistema -------------------------------------------------

set -l system_python
for candidate in python3 python
    if command -q $candidate
        set system_python $candidate
        break
    end
end
test -n "$system_python"; or _die "Python not found in the PATH."

if not $system_python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
    _die "Python 3.9 or newer is required."
end

# --- ambiente virtuale -----------------------------------------------------

if not test -x $python
    _info "Creating the virtual environment in .venv"
    $system_python -m venv $venv; or _die "Could not create the virtual environment."
    rm -f $stamp
end

# Reinstalla solo se requirements.txt è cambiato dopo l'ultima installazione:
# l'avvio normale non deve aspettare pip ogni volta.
if test $do_update -eq 1; or not test -f $stamp; or test $requirements -nt $stamp
    _info "Installing the Python dependencies"
    $python -m pip install --upgrade pip --quiet; or _warn "Could not upgrade pip."
    $python -m pip install -r $requirements --upgrade --quiet
    or _die "Could not install the dependencies (try again with --update)."
    touch $stamp
end

# --- dipendenze di sistema -------------------------------------------------

set -l missing
for tool in ffmpeg ffprobe
    command -q $tool; or set -a missing $tool
end
if test (count $missing) -gt 0
    _die (string join ', ' $missing)" missing from the PATH. On Arch: sudo pacman -S ffmpeg"
end
command -q mpv; or _warn "mpv not found: the video preview will be disabled (sudo pacman -S mpv)."

# --- piattaforma Qt --------------------------------------------------------

if test $force_wayland -eq 1
    set -gx QT_QPA_PLATFORM wayland
    _info "Native Wayland requested: the mpv preview will be in a separate window."
else if test $force_xcb -eq 1
    if test -z "$DISPLAY"
        _warn "No X11 DISPLAY available: ignoring --xcb."
    else
        set -gx QT_QPA_PLATFORM xcb
        _info "Qt platform forced to xcb (mpv preview embedded)."
    end
end
# Senza flag decide main.py: xcb su Wayland se XWayland c'è, per l'anteprima.

# --- avvio -----------------------------------------------------------------

if test $do_check -eq 1
    $python -m ytedit.doctor; or _die "Check failed: sort out the items marked above."
    _info "Environment ready."
    exit 0
end

exec $python $root/main.py $app_args
