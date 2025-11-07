# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


def collect_template_files():
    """Return (src, dest) tuples for every template asset."""
    templates_root = Path(__file__).parent / "backend" / "app" / "templates"
    datas = []
    for path in templates_root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(templates_root)
            dest = Path("backend") / "app" / "templates" / rel
            datas.append((str(path), str(dest)))
    return datas


tmpl_datas = collect_template_files()

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('config.json', '.')] + tmpl_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='go-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
