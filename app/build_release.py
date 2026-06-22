# -*- coding: utf-8 -*-
"""Đóng gói bản phát hành cho khách (launcher .exe + mã nguồn rời cập nhật được).

Chạy:  .venv\\Scripts\\python.exe app\\build_release.py
Kết quả:
  dist\\TaiHoaDonGmail\\                 (thư mục gửi khách)
  dist\\TaiHoaDonGmail_v<ver>.zip       (file nén để gửi)

Các bước: (1) PyInstaller build launcher .exe; (2) chép MÃ NGUỒN SẠCH vào
dist\\TaiHoaDonGmail\\app\\ (loại dữ liệu/bí mật cá nhân); (3) clients.json trắng;
(4) nén ZIP.
"""
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

APP_DIR = os.path.dirname(os.path.abspath(__file__))           # …\app
PROJ_DIR = os.path.dirname(APP_DIR)                            # gốc dự án
DIST = os.path.join(PROJ_DIR, "dist", "TaiHoaDonGmail")
DIST_APP = os.path.join(DIST, "app")
PY = sys.executable

# Thư mục con của app/ được copy nguyên (mã nguồn app).
COPY_DIRS = ["core", "providers", "docs"]
# File lẻ trong app/ được copy.
COPY_FILES = ["gui.py", "version.txt", "update_config.json",
              "clients.example.json", "requirements.txt", "icon.ico"]
# KHÔNG copy (bí mật / dữ liệu riêng / rác).
SKIP_NAMES = {"__pycache__"}


def run_pyinstaller():
    print(">> PyInstaller build launcher ...")
    subprocess.run(
        [PY, "-m", "PyInstaller", os.path.join(APP_DIR, "TaiHoaDonGmail.spec"),
         "--noconfirm", "--clean",
         "--distpath", os.path.join(PROJ_DIR, "dist"),
         "--workpath", os.path.join(PROJ_DIR, "build")],
        check=True,
    )


def _ignore(_dir, names):
    return [n for n in names if n in SKIP_NAMES or n.endswith(".pyc")]


def stage_source():
    print(">> Chép mã nguồn sạch vào", DIST_APP)
    os.makedirs(DIST_APP, exist_ok=True)
    for d in COPY_DIRS:
        src = os.path.join(APP_DIR, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(DIST_APP, d),
                            ignore=_ignore, dirs_exist_ok=True)
    for f in COPY_FILES:
        src = os.path.join(APP_DIR, f)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(DIST_APP, f))
    # clients.json TRẮNG (không kèm tài khoản nào)
    with open(os.path.join(DIST_APP, "clients.json"), "w", encoding="utf-8") as fp:
        fp.write("{}\n")
    # Hướng dẫn nhanh cạnh .exe
    quick = (
        "TAI HOA DON GMAIL - HUONG DAN NHANH\n"
        "==================================\n\n"
        "1) Giai nen TOAN BO thu muc nay ra noi de ghi (Desktop / Documents),\n"
        "   KHONG dat trong 'Program Files'.\n"
        "2) Bam dup file:  TaiHoaDonGmail.exe\n"
        "   (Windows SmartScreen canh bao -> More info -> Run anyway).\n"
        "3) Trong app bam nut '\U0001F4D6 Huong dan su dung' de xem huong dan day du\n"
        "   (cach tao file credentials .json, them tai khoan Gmail...).\n\n"
        "LUU Y:\n"
        "- Cau hinh & du lieu luu trong thu muc 'app' canh .exe. Doi may thi copy\n"
        "  ca thu muc.\n"
        "- Can cai san Google Chrome (cho hoa don MISA / SmartSign).\n"
        "- Co ban moi: bam '\U0001F504 Kiem tra cap nhat' trong app de tu cap nhat.\n"
    )
    with open(os.path.join(DIST, "HUONG DAN NHANH.txt"), "w", encoding="utf-8") as fp:
        fp.write(quick)


def make_zip():
    ver = open(os.path.join(APP_DIR, "version.txt"), encoding="utf-8").read().strip()
    out = os.path.join(PROJ_DIR, "dist", f"TaiHoaDonGmail_v{ver}")
    if os.path.exists(out + ".zip"):
        os.remove(out + ".zip")
    print(">> Nen ZIP ...")
    shutil.make_archive(out, "zip", DIST)
    mb = os.path.getsize(out + ".zip") / (1024 * 1024)
    print(f">> XONG: {out}.zip  ({mb:.1f} MB)")


if __name__ == "__main__":
    if "--no-build" not in sys.argv:
        run_pyinstaller()
    stage_source()
    make_zip()
    print(">> Ban phat hanh san sang trong:", DIST)
