# -*- coding: utf-8 -*-
"""
providers/vnpt.py
Nhà cung cấp VNPT (hoadondientu@vnpt-invoice.vn) — portal *.vnpt-invoice.com.vn
vd Mercure Hanoi La Gare (mercurehanoi-tt78.vnpt-invoice.com.vn).

Đặc điểm email:
- KHÔNG có file đính kèm. Có link "Tại đây" dạng
  https://<cong-ty>.vnpt-invoice.com.vn/Email/EmailInvoiceView?token=<TOKEN>
  (token là duy nhất cho mỗi email) + "Mã tra cứu nhanh: <fkey>".
- Luồng tải (chỉ requests, KHÔNG Selenium/captcha):
    1) GET EmailInvoiceView?token=...   -> server gắn token vào session.
    2) POST /Email/ajxPreview/          -> JSON {html} chứa nút
       downloadZip('<checkCode>') / printInvoice('<checkCode>').
    3) checkCode -> tải:
         PDF : GET /HomeNoLogin/DownloadPdf?checkCode=<checkCode>
         XML : GET /HomeNoLogin/downloadZip?checkCode=<checkCode>  (file ZIP
               chứa XML đã ký + HTML bản thể hiện) -> bóc lấy .xml.
- Mỗi công ty 1 subdomain riêng -> host LẤY TỪ link trong email.

Interface khớp PROVIDERS trong engine:
    is_vnpt_email(subject, from_email, body_text) -> bool
    download_vnpt_invoice(body_text, save_dir, name_prefix="") -> bool
"""

import io
import os
import re
import zipfile
import logging
from html import unescape
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.9",
}

# Link xem hóa đơn có token trong email.
EMAIL_TOKEN_PATTERN = (
    r"https?://([^/\"'<>\s]+)/Email/EmailInvoiceView\?token=([^\"'<>\s&]+)"
)
# checkCode nằm trong nút bấm của trang preview.
CHECKCODE_PATTERN = r"(?:downloadZip|printInvoice|printScr)\('([^']+)'\)"


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_vnpt_email(subject, from_email, body_text):
    f = (from_email or "").lower()
    if "vnpt-invoice" in f:
        return True
    b = (body_text or "").lower()
    return "vnpt-invoice.com.vn" in b or "vnpt-invoice.vn" in b


# ==========================================
# TRÍCH HOST + TOKEN
# ==========================================
def _extract_host_token(body_text):
    text = unescape(body_text or "")
    m = re.search(EMAIL_TOKEN_PATTERN, text, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None, None


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
def download_vnpt_invoice(body_text, save_dir, name_prefix=""):
    host, token = _extract_host_token(body_text)
    if not token:
        print("VNPT: không tìm thấy link EmailInvoiceView?token= trong email")
        return False

    base = f"https://{host}"
    print("VNPT HOST:", host)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update(HEADERS)

    try:
        # 1) Gắn token vào session
        s.get(f"{base}/Email/EmailInvoiceView?token={token}", timeout=40)
        # 2) Lấy trang preview -> checkCode
        r = s.post(
            f"{base}/Email/ajxPreview/",
            data="",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{base}/Email/EmailInvoiceView?token={token}",
            },
            timeout=60,
        )
        html = r.json().get("html", "")
    except Exception as e:
        print("VNPT: lỗi lấy preview:", e)
        return False

    m = re.search(CHECKCODE_PATTERN, html)
    if not m:
        print("VNPT: không tìm thấy checkCode trong trang xem hóa đơn")
        return False
    check_code = m.group(1)
    cc = quote(check_code, safe="")
    print("VNPT checkCode:", check_code)

    pre = f"{name_prefix}_" if name_prefix else ""
    saved = 0
    base_name = None

    # --- XML (qua file ZIP: lấy .xml đã ký, tên file chuẩn của VNPT) ---
    try:
        rz = s.get(f"{base}/HomeNoLogin/downloadZip?checkCode={cc}", timeout=90)
        if rz.status_code == 200 and rz.content[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(rz.content))
            for info in zf.infolist():
                if info.filename.lower().endswith(".xml"):
                    base_name = Path(info.filename).stem
                    out = _ensure_unique(save_dir / f"{pre}{base_name}.xml")
                    out.write_bytes(zf.read(info))
                    print("VNPT - Đã lưu:", out)
                    saved += 1
                    break
    except Exception as e:
        print("VNPT: lỗi tải XML:", e)

    if not base_name:
        base_name = f"HoaDon_VNPT_{check_code[:8]}"

    # --- PDF ---
    try:
        rp = s.get(f"{base}/HomeNoLogin/DownloadPdf?checkCode={cc}", timeout=90)
        if rp.status_code == 200 and rp.content[:4] == b"%PDF":
            out = _ensure_unique(save_dir / f"{pre}{base_name}.pdf")
            out.write_bytes(rp.content)
            print("VNPT - Đã lưu:", out)
            saved += 1
        else:
            print("VNPT: PDF không hợp lệ (status %s)" % rp.status_code)
    except Exception as e:
        print("VNPT: lỗi tải PDF:", e)

    return saved > 0
