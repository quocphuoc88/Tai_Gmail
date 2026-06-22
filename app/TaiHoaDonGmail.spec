# -*- mode: python ; coding: utf-8 -*-
# Build GUI đa tài khoản (gui.py) thành bản phân phối cho khách.
#   .venv\Scripts\python.exe -m PyInstaller app\TaiHoaDonGmail.spec --noconfirm --clean
# Kết quả: dist\TaiHoaDonGmail\TaiHoaDonGmail.exe (+ thư mục _internal).
import os

APP = SPECPATH  # = thư mục chứa file .spec (…\app)

datas = [
    (os.path.join(APP, "docs"), "docs"),            # hướng dẫn sử dụng (HTML)
    (os.path.join(APP, "version.txt"), "."),        # cho updater.local_version()
    (os.path.join(APP, "update_config.json"), "."),  # cho kiểm tra bản mới
]

# Thư viện nặng CHỈ dùng cho OCR captcha Petrolimex (nạp lười) -> loại để build gọn & chắc.
excludes = [
    "ddddocr", "onnxruntime", "cv2", "opencv-python",
    "pandas", "openpyxl", "et_xmlfile", "numpy", "matplotlib",
]

a = Analysis(
    [os.path.join(APP, "gui.py")],
    pathex=[APP],
    binaries=[],
    datas=datas,
    hiddenimports=["tkcalendar", "babel.numbers"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TaiHoaDonGmail",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # ứng dụng GUI, không cửa sổ đen
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TaiHoaDonGmail",
)
