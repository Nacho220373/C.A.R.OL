import os
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """
    Best-effort repo root detection for dev runs.
    We look upward for a marker file so running from any cwd works.
    """
    for p in (start, *start.parents):
        if (p / "requirements.txt").exists() and (p / "main.py").exists():
            return p
    return start


def is_frozen() -> bool:
    """True when running from a PyInstaller/frozen executable."""
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Path:
    """
    Directory where the user keeps runtime files:
    - Frozen: directory containing the .exe
    - Source: repo root directory
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _find_repo_root(Path(__file__).resolve().parent)


def bundle_dir() -> Path:
    """
    Directory where bundled resources live:
    - Frozen onefile: temporary extraction directory (sys._MEIPASS)
    - Source: same as runtime_dir()
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return runtime_dir()


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled resource (assets, etc.)."""
    return str(bundle_dir().joinpath(*parts))


def env_path(filename: str = ".env") -> str:
    """Absolute path to external env file (next to the exe in frozen mode)."""
    return str(runtime_dir() / filename)


def user_data_dir(app_name: str = "CAROL") -> str:
    """
    A per-user writable directory.
    - Windows: %APPDATA%\\<app_name> (fallback: user home)
    - Linux/macOS: ~/.local/share/<app_name>
    """
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home())
        path = Path(base) / app_name
    else:
        path = Path.home() / ".local" / "share" / app_name

    path.mkdir(parents=True, exist_ok=True)
    return str(path)

