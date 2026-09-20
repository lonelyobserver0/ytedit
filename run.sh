#!/usr/bin/env bash
#
# Avvia ytEdit preparando l'ambiente solo quando serve.
#   ./run.sh              avvia l'applicazione
#   ./run.sh --xcb        forza X11 (anteprima mpv incorporata su Wayland)
#   ./run.sh --update     riallinea le dipendenze
#   ./run.sh --check      verifica l'ambiente senza avviare nulla

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
            echo "Uso: run.sh [opzioni] [argomenti per main.py]"
            echo
            echo "  -u, --update   reinstalla/aggiorna le dipendenze Python"
            echo "  -x, --xcb      forza QT_QPA_PLATFORM=xcb (già predefinito su"
            echo "                 Wayland quando XWayland è disponibile)"
            echo "  -w, --wayland  resta su Wayland nativo: l'anteprima mpv si apre"
            echo "                 in una finestra separata"
            echo "  -c, --check    verifica ambiente e dipendenze, poi esce"
            echo "  -h, --help     mostra questo messaggio"
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
[[ -n "$system_python" ]] || _die "Python non trovato nel PATH."

if ! "$system_python" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
    _die "Serve Python 3.9 o superiore."
fi

# --- ambiente virtuale -----------------------------------------------------

if [[ ! -x "$python" ]]; then
    _info "Creazione dell'ambiente virtuale in .venv"
    "$system_python" -m venv "$venv" || _die "Creazione dell'ambiente virtuale fallita."
    rm -f "$stamp"
fi

# Reinstalla solo se requirements.txt è cambiato dopo l'ultima installazione:
# l'avvio normale non deve aspettare pip ogni volta.
if ((do_update)) || [[ ! -f "$stamp" ]] || [[ "$requirements" -nt "$stamp" ]]; then
    _info "Installazione delle dipendenze Python"
    "$python" -m pip install --upgrade pip --quiet || _warn "Aggiornamento di pip non riuscito."
    "$python" -m pip install -r "$requirements" --upgrade --quiet \
        || _die "Installazione delle dipendenze fallita (riprova con --update)."
    touch "$stamp"
fi

# --- dipendenze di sistema -------------------------------------------------

missing=()
for tool in ffmpeg ffprobe; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ((${#missing[@]} > 0)); then
    _die "Manca $(IFS=', '; echo "${missing[*]}") nel PATH. Su Arch: sudo pacman -S ffmpeg"
fi
command -v mpv >/dev/null 2>&1 \
    || _warn "mpv non trovato: l'anteprima video sarà disattivata (sudo pacman -S mpv)."

# --- piattaforma Qt --------------------------------------------------------

if ((force_wayland)); then
    export QT_QPA_PLATFORM=wayland
    _info "Wayland nativo richiesto: l'anteprima mpv sarà in una finestra separata."
elif ((force_xcb)); then
    if [[ -z "${DISPLAY:-}" ]]; then
        _warn "Nessun DISPLAY X11 disponibile: ignoro --xcb."
    else
        export QT_QPA_PLATFORM=xcb
        _info "Piattaforma Qt forzata a xcb (anteprima mpv incorporata)."
    fi
fi
# Senza flag decide main.py: xcb su Wayland se XWayland c'è, per l'anteprima.

# --- avvio -----------------------------------------------------------------

if ((do_check)); then
    "$python" -m ytedit.doctor || _die "Verifica fallita: risolvi i punti marcati sopra."
    _info "Ambiente pronto."
    exit 0
fi

exec "$python" "$root/main.py" ${app_args[@]+"${app_args[@]}"}
