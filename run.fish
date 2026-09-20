#!/usr/bin/env fish
#
# Avvia ytEdit preparando l'ambiente solo quando serve.
#   ./run.fish              avvia l'applicazione
#   ./run.fish --xcb        forza X11 (anteprima mpv incorporata su Wayland)
#   ./run.fish --update     riallinea le dipendenze
#   ./run.fish --check      verifica l'ambiente senza avviare nulla

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
            echo "Uso: run.fish [opzioni] [argomenti per main.py]"
            echo
            echo "  -u, --update   reinstalla/aggiorna le dipendenze Python"
            echo "  -x, --xcb      forza QT_QPA_PLATFORM=xcb (già predefinito su"
            echo "                 Wayland quando XWayland è disponibile)"
            echo "  -w, --wayland  resta su Wayland nativo: l'anteprima mpv si apre"
            echo "                 in una finestra separata"
            echo "  -c, --check    verifica ambiente e dipendenze, poi esce"
            echo "  -h, --help     mostra questo messaggio"
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
test -n "$system_python"; or _die "Python non trovato nel PATH."

if not $system_python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
    _die "Serve Python 3.9 o superiore."
end

# --- ambiente virtuale -----------------------------------------------------

if not test -x $python
    _info "Creazione dell'ambiente virtuale in .venv"
    $system_python -m venv $venv; or _die "Creazione dell'ambiente virtuale fallita."
    rm -f $stamp
end

# Reinstalla solo se requirements.txt è cambiato dopo l'ultima installazione:
# l'avvio normale non deve aspettare pip ogni volta.
if test $do_update -eq 1; or not test -f $stamp; or test $requirements -nt $stamp
    _info "Installazione delle dipendenze Python"
    $python -m pip install --upgrade pip --quiet; or _warn "Aggiornamento di pip non riuscito."
    $python -m pip install -r $requirements --upgrade --quiet
    or _die "Installazione delle dipendenze fallita (riprova con --update)."
    touch $stamp
end

# --- dipendenze di sistema -------------------------------------------------

set -l missing
for tool in ffmpeg ffprobe
    command -q $tool; or set -a missing $tool
end
if test (count $missing) -gt 0
    _die "Manca "(string join ', ' $missing)" nel PATH. Su Arch: sudo pacman -S ffmpeg"
end
command -q mpv; or _warn "mpv non trovato: l'anteprima video sarà disattivata (sudo pacman -S mpv)."

# --- piattaforma Qt --------------------------------------------------------

if test $force_wayland -eq 1
    set -gx QT_QPA_PLATFORM wayland
    _info "Wayland nativo richiesto: l'anteprima mpv sarà in una finestra separata."
else if test $force_xcb -eq 1
    if test -z "$DISPLAY"
        _warn "Nessun DISPLAY X11 disponibile: ignoro --xcb."
    else
        set -gx QT_QPA_PLATFORM xcb
        _info "Piattaforma Qt forzata a xcb (anteprima mpv incorporata)."
    end
end
# Senza flag decide main.py: xcb su Wayland se XWayland c'è, per l'anteprima.

# --- avvio -----------------------------------------------------------------

if test $do_check -eq 1
    $python -m ytedit.doctor; or _die "Verifica fallita: risolvi i punti marcati sopra."
    _info "Ambiente pronto."
    exit 0
end

exec $python $root/main.py $app_args
