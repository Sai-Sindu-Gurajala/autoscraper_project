# autoscraper_core/pathing.py
import os, sys

def _project_root_from_this_file() -> str:
    """
    When running from source:
      this file = .../autoscraper_core/pathing.py
      project root = parent of autoscraper_core
    When running as PyInstaller --onefile:
      use sys._MEIPASS (temp bundle dir).
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .../autoscraper_core
    return os.path.abspath(os.path.join(here, os.pardir))   # project root

def resource_path(rel_path: str) -> str:
    """
    Return absolute path to a resource relative to PROJECT ROOT in dev,
    or to the bundle folder in a PyInstaller build.
    """
    base = getattr(sys, "_MEIPASS", _project_root_from_this_file())
    return os.path.join(base, rel_path)
