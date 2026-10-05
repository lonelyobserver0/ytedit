"""Scelta della piattaforma Qt prima che l'applicazione venga creata."""
import os


def prefer_x11_for_embedding(environ=None, announce=True):
    """Su Wayland preferisce 'xcb' così l'anteprima mpv resta nella finestra.

    L'incorporamento usa `--wid` di mpv, supportato solo su finestre X11. Se la
    sessione è Wayland ma XWayland è disponibile (`DISPLAY` valorizzato), usare
    xcb è l'unico modo per non aprire una finestra separata.

    Restituisce la piattaforma impostata, o None se non si tocca nulla.
    Rispetta sempre una scelta esplicita (`QT_QPA_PLATFORM`, `YTEDIT_KEEP_WAYLAND`).
    """
    env = os.environ if environ is None else environ
    if env.get("QT_QPA_PLATFORM") or env.get("YTEDIT_KEEP_WAYLAND"):
        return None
    if env.get("XDG_SESSION_TYPE") != "wayland" or not env.get("DISPLAY"):
        return None
    env["QT_QPA_PLATFORM"] = "xcb"
    if announce:
        print("ytEdit: Qt platform 'xcb' for the embedded video preview "
              "(QT_QPA_PLATFORM=wayland to turn it off).", flush=True)
    return "xcb"
