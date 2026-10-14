# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

repo_root = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(repo_root, 'config'), 'config'),
    (os.path.join(repo_root, 'models'), 'models'),
    (os.path.join(repo_root, 'assets'), 'assets'),
    (os.path.join(repo_root, 'src', 'engine', 'voz_node'), os.path.join('src', 'engine', 'voz_node')),
]

hiddenimports = [
    'sounddevice',
    'soundfile',
    'numpy',
    'scipy',
    'onnxruntime',
    'yaml',
    'win32gui',
    'win32process',
    'win32api',
    'win32con',
    'psutil',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'ctypes',
    'ctypes.wintypes',
]

a = Analysis(
    [os.path.join(repo_root, 'src', 'main.py')],
    pathex=[repo_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'notebook', 'IPython', 'torch'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Takt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(repo_root, 'assets', 'takt.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Takt',
)
