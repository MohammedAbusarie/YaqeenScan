# -*- mode: python ; coding: utf-8 -*-
"""Debug PyInstaller spec for YaqeenScan with console enabled."""

import os

from PyInstaller.utils.hooks import collect_data_files

try:
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _PROJECT_ROOT = os.getcwd()

server_templates = os.path.join(_PROJECT_ROOT, "server", "templates")
server_static = os.path.join(_PROJECT_ROOT, "server", "static")
datas_server = []
if os.path.isdir(server_templates):
    datas_server.append((server_templates, "server/templates"))
if os.path.isdir(server_static):
    datas_server.append((server_static, "server/static"))

try:
    customtkinter_datas = collect_data_files("customtkinter")
except Exception:
    customtkinter_datas = []

a = Analysis(
    [os.path.join(_PROJECT_ROOT, "run.py")],
    pathex=[_PROJECT_ROOT],
    binaries=[],
    datas=datas_server + customtkinter_datas,
    hiddenimports=[
        "core",
        "core.config",
        "core.database",
        "core.exceptions",
        "core.fingerprint",
        "core.models",
        "core.token_manager",
        "network",
        "network.hotspot",
        "network.arp_scanner",
        "server",
        "server.app",
        "server.routes",
        "gui",
        "gui.main_window",
        "gui.qr_panel",
        "gui.attendance_panel",
        "gui.session_controls",
        "export",
        "export.exporter",
        "security",
        "security.firewall",
        "security.ics",
        "security.name_resolution",
        "customtkinter",
        "PIL",
        "PIL.Image",
        "qrcode",
        "openpyxl",
        "werkzeug.serving",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "matplotlib",
        "IPython",
        "pytest",
        "jedi",
        "parso",
        "nbformat",
        "zmq",
        "orjson",
        "black",
        "yapf",
        "blib2to3",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="YaqeenScan_debug",
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(_PROJECT_ROOT, "assets", "appicon.ico"),
)

