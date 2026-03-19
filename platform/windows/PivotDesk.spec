# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_submodules

project_dir = os.getcwd()

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("jinja2")
hiddenimports += collect_submodules("pandas")
hiddenimports += collect_submodules("openpyxl")

datas = []

def add_data_folder(folder_name):
    folder_path = os.path.join(project_dir, folder_name)
    if os.path.exists(folder_path):
        datas.append((folder_path, folder_name))

def add_data_file(file_name):
    file_path = os.path.join(project_dir, file_name)
    if os.path.exists(file_path):
        datas.append((file_path, "."))

for name in ("static", "templates", "plugins", "services", "scripts", "runtime", "licensing", "licenses", "data"):
    add_data_folder(name)

for name in ("config.json", "plugins.json", "requirements-core.txt"):
    add_data_file(name)

icon_file = os.path.join(project_dir, "static", "img", "pivotdesk.ico")
icon_path = icon_file if os.path.exists(icon_file) else None

a = Analysis(
    ["main.py"],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "notebook",
        "jupyter",
        "IPython",
        "pytest",
        "pandas.tests",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PivotDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PivotDesk",
)
