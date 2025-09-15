from cx_Freeze import setup, Executable
from pathlib import Path

APP_NAME   = "AutoScraper"
VERSION    = "1.0.0"
COMPANY    = "Fyind"
ICON       = "assets/icon.ico"

base = "Win32GUI"  # keep GUI (no console)

include_files = [
    ("assets", "assets"),            # icon + chromedriver live here
    ("output", "output"),            # optional default output folder
]

build_exe_options = {
    "packages": [
        "selenium", "requests", "idna", "certifi", "charset_normalizer", "urllib3",
        "pkg_resources", "PyQt5", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.QtCore"
    ],
    "excludes": ["tkinter", "PySide2", "PySide6", "tests", "unittest"],
    "include_files": [("assets", "assets"), ("output", "output")],
    "include_msvcr": True,
}

# Start-menu + desktop shortcuts
shortcut_table = [
    ("StartMenuShortcut", "ProgramMenuFolder", APP_NAME,
     "TARGETDIR", "[TARGETDIR]AutoScraper.exe", None, None, None, None, None, None, "TARGETDIR"),
    ("DesktopShortcut", "DesktopFolder", APP_NAME,
     "TARGETDIR", "[TARGETDIR]AutoScraper.exe", None, None, None, None, None, None, "TARGETDIR"),
]

bdist_msi_options = {
    "all_users": False,  # per-user install (matches your current install)
    "add_to_path": False,
    "upgrade_code": "{5355E728-A843-4D04-BA2B-F59AD69F64E0}",  # keep this stable
    "data": {
        "Shortcut": [
            ("StartMenuShortcut", "ProgramMenuFolder", APP_NAME,
             "TARGETDIR", f"{APP_NAME}.exe", None, None, None, None, None, None, "TARGETDIR")
        ]
    },
}

executables = [
    Executable("main.py", base="Win32GUI", target_name=f"{APP_NAME}.exe", icon=ICON)
]

setup(
    name=APP_NAME,
    version=VERSION,
    description="Point-and-click web autoscraper",
    options={"build_exe": build_exe_options, "bdist_msi": bdist_msi_options},
    executables=executables,
)
