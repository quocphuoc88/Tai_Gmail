# -*- coding: utf-8 -*-
"""
providers/vetc.py
Nhà cung cấp VETC (Thu phí tự động) — tracuuhoadon.vetc.com.vn

Đặc điểm email:
- KHÔNG có link tải trực tiếp, chỉ có "Mã tra cứu hóa đơn" + trang tra cứu.
- Tra cứu: POST mã (secureId) lên trang -> trang trả link /download/<mã>
  -> tải về file ZIP chứa PDF + XML (+ HTML). KHÔNG cần captcha, không Selenium.

Interface khớp PROVIDERS trong engine:
    is_vetc_email(subject, from_email, body_text) -> bool
    download_vetc_invoice(body_text, save_dir, name_prefix="") -> bool
"""

import io
import os
import re
import zipfile
import logging
from html import unescape
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE = "https://tracuuhoadon.vetc.com.vn/"
ORIGIN = "https://tracuuhoadon.vetc.com.vn"
DOWNLOAD_PREFIX = BASE + "download/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.9",
}


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_vetc_email(subject, from_email, body_text):
    f = (from_email or "").lower()
    if f.endswith("@vetc.com.vn"):
        return True
    b = (body_text or "").lower()
    return ("tracuuhoadon.vetc.com.vn" in b) or ("vetc" in b and "mã tra cứu" in b)


# ==========================================
# TRÍCH MÃ TRA CỨU (giữ nguyên hoa/thường - secureId phân biệt hoa thường)
# ==========================================
def _strip_html(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text)


def extract_vetc_code(body_text):
    text = _strip_html(body_text or "")
    # "Mã tra cứu hóa đơn E8izrer64tJU"
    m = re.search(
        r"M[ãa]\s*tra\s*c[ứu]+u?\s*h[óo]a\s*[đd][ơo]n\s*[:\-]?\s*([A-Za-z0-9]{8,24})",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    # Dự phòng: mã đứng ngay trước "Tra cứu tại"
    m = re.search(r"([A-Za-z0-9]{8,24})\s+Tra\s*c[ứu]+u?\s*t[ạa]i", text, re.IGNORECASE)
    return m.group(1) if m else None


def _ensure_unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_vetc_invoice(body_text, save_dir, name_prefix=""):
    code = extract_vetc_code(body_text)
    if not code:
        print("VETC: không tìm thấy mã tra cứu")
        return False

    print("VETC CODE:", code)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        # 1) GET lấy cookie (WAF F5)
        s.get(BASE, timeout=30)
        # 2) POST mã tra cứu như form trên trang
        s.post(
            BASE,
            data={"searchType": "SECURE_ID", "secureId": code, "ticketId": "", "plate": ""},
            headers={
                "Referer": BASE,
                "Origin": ORIGIN,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
        # 3) Tải file theo link /download/<mã>
        r = s.get(DOWNLOAD_PREFIX + code, headers={"Referer": BASE}, timeout=90)
    except Exception as e:
        print("VETC: lỗi tra cứu/tải:", e)
        return False

    if r.status_code != 200 or not r.content:
        print(f"VETC: tải fail (status {r.status_code})")
        return False
    if b"<html" in r.content[:400].lower():
        print("VETC: trang trả về HTML (mã sai/hết hạn?) - không phải file")
        return False

    pre = f"{name_prefix}_" if name_prefix else ""

    # ZIP -> bóc PDF + XML
    if r.content[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            saved = 0
            for info in zf.infolist():
                ext = os.path.splitext(info.filename)[1].lower()
                if ext not in (".pdf", ".xml"):
                    continue
                stem = Path(info.filename).stem
                out = _ensure_unique(save_dir / f"{pre}{stem}{ext}")
                out.write_bytes(zf.read(info))
                print("VETC - Đã lưu:", out)
                saved += 1
            if saved:
                return True
            # zip không có pdf/xml -> lưu nguyên zip
        except zipfile.BadZipFile:
            pass

    # Không phải zip (hoặc zip lỗi) -> lưu nguyên file theo Content-Disposition
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd, re.IGNORECASE)
    name = m.group(1).strip() if m else f"VETC_{code}.bin"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    out = _ensure_unique(save_dir / f"{pre}{name}")
    out.write_bytes(r.content)
    print("VETC - Đã lưu:", out)
    return True
