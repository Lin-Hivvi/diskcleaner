# -*- mode: python ; coding: utf-8 -*-
# DiskCleaner PyInstaller 构建配置
# 本文件位于 scripts/ 下，路径相对于此文件位置

a = Analysis(
    ['../src/disk_cleaner.py'],
    pathex=['..'],        # 添加项目根目录到 sys.path，使 src 包可导入
    binaries=[],
    datas=[
        ('../lang', 'lang'),                        # 语言包
        ('../resources/icon.ico', 'resources'),     # 图标
    ],
    hiddenimports=['queue'],
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
    name='DiskCleaner',
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
    version='../resources/version_info.txt',
    icon=['../resources/icon.ico'],
)
