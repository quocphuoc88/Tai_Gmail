# -*- coding: utf-8 -*-
"""
providers/ipos.py
Nhà cung cấp IPOS.VN (tracuuhoadon.ipos.vn) — vd GARDEN KISSES.

Đặc điểm: email có LINK TẢI TRỰC TIẾP (không captcha, không Selenium):
- PDF: .../Invoice/getinvoice?token=...
- XML: .../Invoice/Download78?id=...
Cả hai trả file thẳng (Content-Disposition: attachment).

Interface khớp PROVIDERS trong engine:
    is_ipos_email(subject, from_email, body_text) -> bool
    download_ipos_invoice(body_text, save_dir, name_prefix="") -> bool
"""

import os
import re
import logging
from html import unescape
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ==========================================
# NHẬN DIỆN
# ==========================================
def is_ipos_email(subject, from_email, body_text):
    f = (from_email or "").lower()
    if f.endswith("@ipos.vn"):
        return True
    b = (body_text or "").lower()
    return "tracuuhoadon.ipos.vn" in b


# ==========================================
# TRÍCH LINK
# ==========================================
def extract_ipos_links(body_text):
    """Trả về (pdf_url, xml_url). getinvoice -> PDF, Download78 -> XML."""
    pdf_url = xml_url = None
    urls = re.findall(r'https?://tracuuhoadon\.ipos\.vn/[^\s"\'<>)]+',
                      unescape(body_text or ""), re.IGNORECASE)
    for u in urls:
        ul = u.lower()
        if "getinvoice" in ul and not pdf_url:
            pdf_url = u
        elif "download78" in ul and not xml_url:
            xml_url = u
    return pdf_url, xml_url


def _ensure_unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _download(session, url, save_dir: Path, default_name, name_prefix=""):
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
    except Exception as e:
        logger.error("IPOS tải lỗi %s: %s", url, e)
        return None
    if r.status_code != 200 or not r.content:
        print(f"IPOS: tải fail (status {r.status_code})")
        return None
    if b"<html" in r.content[:300].lower():
        print("IPOS: link trả về HTML (không phải file)")
        return None

    name = default_name
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd, re.IGNORECASE)
    if m:
        name = re.sub(r'[\\/:*?"<>|]', "_", unescape(m.group(1)).strip())
    if name_prefix:
        name = f"{name_prefix}_{name}"

    out = _ensure_unique(save_dir / name)
    out.write_bytes(r.content)
    print("IPOS - Đã lưu:", out)
    return out


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_ipos_invoice(body_text, save_dir, name_prefix=""):
    pdf_url, xml_url = extract_ipos_links(body_text)
    if not pdf_url and not xml_url:
        print("IPOS: không tìm thấy link tải")
        return False

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(HEADERS)

    ok = False
    if pdf_url:
        if _download(s, pdf_url, save_dir, "ipos_invoice.pdf", name_prefix):
            ok = True
    else:
        print("IPOS: không có link PDF")
    if xml_url:
        if _download(s, xml_url, save_dir, "ipos_invoice.xml", name_prefix):
            ok = True
    else:
        print("IPOS: không có link XML")
    return ok
