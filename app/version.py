"""Centralizovaná správa verze aplikace iVysílání Server."""

import subprocess
from typing import Dict, Any

__version__ = "2.2.1"
__release_date__ = "2026-11-22"
__app_name__ = "iVysílání Server"

def get_git_commit() -> str:
    """Vrátí zkrácený hash aktuálního git commitu nebo 'release'."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=1
        ).decode("ascii").strip()
        return commit
    except Exception:
        return "e8c529a"

def get_version_info() -> Dict[str, Any]:
    """Vrátí strukturované informace o verzi serveru."""
    return {
        "name": __app_name__,
        "version": __version__,
        "release_date": __release_date__,
        "commit": get_git_commit(),
        "api_versions": {
            "xtream": "2.2.0",
            "stremio": "2.2.0",
            "streamcube": "1.0.0",
            "m3u_xmltv": "2.2.0"
        }
    }
