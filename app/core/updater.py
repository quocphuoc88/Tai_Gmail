"""Cập nhật code online từ GitHub.

Cách hoạt động:
- `app/version.txt`      : phiên bản đang cài (vd 1.0.0).
- `app/update_config.json`: {"repo": "OWNER/REPO", "branch": "main"} -> nơi lấy bản mới.
- check_update(): đọc version.txt trên GitHub, so với bản local.
- download_and_apply(): tải zip nhánh, ghi đè CODE, GIỮ NGUYÊN dữ liệu người dùng
  (clients.json, credentials*, token*, .venv...). Sau đó khởi động lại app.

KHÔNG cần thư viện ngoài (chỉ dùng urllib, zipfile của Python).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../app
PROJECT_DIR = os.path.dirname(APP_DIR)                                  # gốc dự án
CONFIG_FILE = os.path.join(APP_DIR, "update_config.json")
VERSION_FILE = os.path.join(APP_DIR, "version.txt")

# Tên file/thư mục KHÔNG được ghi đè khi cập nhật (dữ liệu & cấu hình của người dùng).
PROTECTED_FILES = {"clients.json"}
SKIP_DIRS = {".git", ".idea", ".claude", ".venv", "build", "dist", "__pycache__"}


def local_version() -> str:
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8-sig") as f:
        return json.load(f)


def is_configured() -> bool:
    """True nếu update_config.json đã điền repo thật (không phải placeholder)."""
    try:
        c = _config()
        repo = (c.get("repo") or "").strip()
        return ("/" in repo) and ("OWNER" not in repo.upper())
    except Exception:
        return False


def _vtuple(v: str):
    out = []
    for p in str(v).strip().split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _http_get(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "TaiHoaDon-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_update():
    """Trả (has_update, remote_version, local_version).

    Lỗi mạng / chưa cấu hình -> (False, None, local_version).
    """
    lv = local_version()
    if not is_configured():
        return (False, None, lv)
    c = _config()
    repo, branch = c["repo"].strip(), (c.get("branch") or "main").strip()
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/app/version.txt"
    try:
        rv = _http_get(url, timeout=15).decode("utf-8").strip()
    except Exception:
        return (False, None, lv)
    return (_vtuple(rv) > _vtuple(lv), rv, lv)


def download_and_apply(logger=print):
    """Tải bản mới nhất của nhánh và ghi đè code. Trả (ok, message)."""
    if not is_configured():
        return (False, "Chưa cấu hình update_config.json (repo).")

    c = _config()
    repo, branch = c["repo"].strip(), (c.get("branch") or "main").strip()
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"

    logger(f"Đang tải bản mới: {url}")
    try:
        data = _http_get(url, timeout=180)
    except Exception as e:
        return (False, f"Tải thất bại: {e}")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        return (False, f"File tải về hỏng: {e}")

    tmp = tempfile.mkdtemp(prefix="taihd_update_")
    try:
        zf.extractall(tmp)
        roots = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
        if not roots:
            return (False, "Gói cập nhật rỗng.")
        src_root = os.path.join(tmp, roots[0])

        copied = 0
        for dirpath, dirnames, filenames in os.walk(src_root):
            rel_dir = os.path.relpath(dirpath, src_root)
            if rel_dir != "." and any(p in SKIP_DIRS for p in rel_dir.split(os.sep)):
                continue
            for fn in filenames:
                if fn in PROTECTED_FILES:
                    continue
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, src_root)
                dst = os.path.join(PROJECT_DIR, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copyfile(src, dst)
                    copied += 1
                except Exception as e:
                    logger(f"Bỏ qua {rel}: {e}")

        logger(f"Đã ghi {copied} file.")
        return (True, f"Đã cập nhật {copied} file. Hãy ĐÓNG và MỞ LẠI ứng dụng để áp dụng.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pip_install_requirements(logger=print) -> bool:
    """Cài lại thư viện theo requirements (phòng khi bản mới thêm thư viện)."""
    import subprocess
    pip = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pip.exe")
    req = os.path.join(APP_DIR, "requirements.txt")
    if not (os.path.exists(pip) and os.path.exists(req)):
        return False
    try:
        logger("Đang cập nhật thư viện (requirements.txt)...")
        subprocess.run([pip, "install", "-r", req], check=False,
                       capture_output=True, text=True)
        return True
    except Exception as e:
        logger(f"Cập nhật thư viện lỗi: {e}")
        return False
