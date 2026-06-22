# -*- mode: python ; coding: utf-8 -*-
# Build LAUNCHER cho khách: .exe chứa Python + thư viện; MÃ NGUỒN app để RỜI
# (cập nhật online được). Xem app/launcher.py.
#   .venv\Scripts\python -m PyInstaller app\TaiHoaDonGmail.spec --noconfirm --clean
# Kết quả: dist\TaiHoaDonGmail\TaiHoaDonGmail.exe (+ _internal). Sau đó đặt bản
# rời mã nguồn vào dist\TaiHoaDonGmail\app\ (script build_release lo việc này).
import os

APP = SPECPATH  # = thư mục chứa file .spec (…\app)

# Thư viện nặng CHỈ dùng cho OCR captcha Petrolimex (nạp lười) -> loại cho gọn.
excludes = [
    "ddddocr", "onnxruntime", "cv2", "opencv-python",
    "pandas", "openpyxl", "et_xmlfile", "numpy", "matplotlib",
]

a = Analysis(
    [os.path.join(APP, "launcher.py")],
    pathex=[APP],            # để 'import gui' trong launcher dò ra app + thư viện
    binaries=[],
    datas=[],                # KHÔNG gói mã nguồn/docs: chúng ship rời, cập nhật được
    hiddenimports=["tkcalendar", "babel.numbers"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Loại các MODULE CỦA APP khỏi gói -> luôn nạp từ bản rời (.\app\*.py) để cập
# nhật online có hiệu lực. (Thư viện bên thứ ba vẫn nằm trong gói.)
_APP_TOP = {"gui", "core", "providers", "launcher"}
a.pure[:] = [e for e in a.pure if e[0].split(".")[0] not in _APP_TOP]

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
