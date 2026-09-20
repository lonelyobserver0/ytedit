"""Verifica dell'ambiente: `python -m ytedit.doctor`.

Usato dagli script di avvio e invocabile a mano per capire cosa manca.
"""
import importlib
import shutil
import sys

PACKAGES = ("PySide6", "yt_dlp")
REQUIRED_TOOLS = ("ffmpeg", "ffprobe")
OPTIONAL_TOOLS = ("mpv",)


def package_version(name: str) -> str:
    """yt-dlp tiene la versione in `yt_dlp.version`, PySide6 in `__version__`."""
    module = importlib.import_module(name)
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    submodule = getattr(module, "version", None)
    if submodule is not None:
        version = getattr(submodule, "__version__", None)
        if version:
            return str(version)
    try:
        from importlib.metadata import version as metadata_version
        return metadata_version(name.replace("_", "-"))
    except Exception:
        return "versione sconosciuta"


def main() -> int:
    ok = True
    print(f"→ Python       {sys.version.split()[0]}  ({sys.executable})")

    for name in PACKAGES:
        try:
            print(f"→ {name:<12} {package_version(name)}")
        except ImportError as exc:
            print(f"✖ {name:<12} non importabile: {exc}")
            ok = False

    for tool in REQUIRED_TOOLS:
        path = shutil.which(tool)
        print(f"{'→' if path else '✖'} {tool:<12} {path or 'non trovato nel PATH'}")
        ok = ok and bool(path)

    for tool in OPTIONAL_TOOLS:
        path = shutil.which(tool)
        print(f"{'→' if path else '!'} {tool:<12} "
              f"{path or 'non trovato (anteprima video disattivata)'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
