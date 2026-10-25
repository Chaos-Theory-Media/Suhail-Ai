"""All file locations in one place. Everything Sawti writes lives under one data folder."""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = os.environ.get("SAWTI_DATA")
    p = Path(base) if base else Path.home() / "Library" / "Application Support" / "Sawti"
    p.mkdir(parents=True, exist_ok=True)
    return p


def install_dir() -> Path:
    """Where the installer puts runtimes (Ollama, models, audio helper). Not affected by SAWTI_DATA."""
    base = os.environ.get("SAWTI_INSTALL")
    return Path(base) if base else Path.home() / "Library" / "Application Support" / "Sawti"


def sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir() -> Path:
    return sub("run")


def templates_dir() -> Path:
    return sub("templates")


def models_dir() -> Path:
    p = install_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def helper_path() -> Path:
    return install_dir() / "bin" / "sawti-audio"


def ollama_binary():
    """Sawti's private Ollama first, then any Ollama on PATH."""
    import shutil
    private = install_dir() / "runtime" / "Ollama.app" / "Contents" / "Resources" / "ollama"
    if private.is_file() and os.access(private, os.X_OK):
        return str(private)
    return shutil.which("ollama")


def default_recording_root() -> Path:
    return Path.home() / "Music" / "Sawti Recordings"


def simulate() -> bool:
    return os.environ.get("SAWTI_SIMULATE", "") == "1"
