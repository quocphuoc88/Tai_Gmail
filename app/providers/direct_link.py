# -*- coding: utf-8 -*-
"""
providers/direct_link.py
Provider tổng quát cho các nhà mạng gửi LINK TẢI TRỰC TIẾP trong email
(không cần Selenium, không cần postback).

Hiện nhận diện:
- Fast e-Invoice (einvoice.fast.com.vn): type=3 -> PDF, type=2 -> XML
- Pattern chung: link chứa 'pdfdownload' / đuôi .pdf -> PDF
                 link chứa 'getinvoice'  / đuôi .xml -> XML
Thêm nhà mạng mới có link trực tiếp: chỉ cần thêm hint vào PDF_HINTS / XML_HINTS.

Interface khớp với PROVIDERS trong gmail_sync_v3:
    is_direct_link_email(subject, from_email, body_text) -> bool
    download_direct_invoice(body_text, save_dir) -> bool
"""

import os
import re
import logging
import unicodedata
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

# Hint nhận diện link theo loại file (so khớp trên href đã lowercase)
PDF_HINTS = [
    "type=3",          # Fast e-Invoice
    "pdfdownload",
    ".pdf",
]

XML_HINTS = [
    "type=2",          # Fast e-Invoice
    "getinvoice",
    ".xml",
]

# Link "xem" không phải link tải -> loại trừ
EXCLUDE_HINTS = [
    "type=1",          # Fast: bản thể hiện xem online
]


# ==========================================
# HELPERS
# ==========================================
def _strip_html(html):

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "",
                  flags=re.IGNORECASE | re.DOTALL)

    text = re.sub(r"<[^>]+>", " ", text)

    text = unescape(text)

    return re.sub(r"\s+", " ", text)


def _extract_hrefs(html):
    """Lấy tất cả href trong body (decode &amp; -> &)."""

    hrefs = re.findall(
        r'href\s*=\s*["\']([^"\']+)["\']',
        html or "",
        re.IGNORECASE
    )

    return [unescape(h).strip() for h in hrefs]


def extract_links(body_html):
    """Trả về (pdf_url, xml_url) - None nếu không có."""

    pdf_url = xml_url = None

    for href in _extract_hrefs(body_html):

        h = href.lower()

        if not h.startswith("http"):
            continue

        if any(x in h for x in EXCLUDE_HINTS):
            # type=1 cũng chứa... không, type=1 khác type=3; check riêng
            # nhưng cẩn thận: "type=1" nằm trong "type=12"? -> dùng regex biên
            if re.search(r"[?&]type=1(?!\d)", h):
                continue

        if pdf_url is None and any(x in h for x in PDF_HINTS):
            pdf_url = href

        elif xml_url is None and any(x in h for x in XML_HINTS):
            xml_url = href

    return pdf_url, xml_url


def extract_invoice_number(body_html):
    """Tìm số hóa đơn trong body để đặt tên file."""

    text = _strip_html(body_html)

    patterns = [
        r"S[oố]\s*h[oó]a\s*[dđ][oơ]n[^0-9]{0,40}?(\d{1,8})(?![A-Za-z0-9])",
        r"H[oó]a\s*[dđ][oơ]n\s*(?:m[oớ]i\s*)?s[oố][^0-9]{0,40}?(\d{1,8})(?![A-Za-z0-9])",
        r"Invoice\s*(?:Number|No)\.?[^0-9]{0,40}?(\d{1,8})(?![A-Za-z0-9])",
    ]

    for p in patterns:

        m = re.search(p, text, re.IGNORECASE)

        if m:
            return m.group(1)

    return "invoice"


def _ensure_unique(path: Path) -> Path:

    if not path.exists():
        return path

    i = 1

    while True:

        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")

        if not cand.exists():
            return cand

        i += 1


def _download(url, save_path: Path, timeout=30, honor_content_disposition=True):

    try:

        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True)

        r.raise_for_status()

        ctype = r.headers.get("Content-Type", "").lower()

        # Server trả về trang HTML thay vì file -> link không tải trực tiếp được
        if "text/html" in ctype and b"<html" in r.content[:500].lower():

            logger.warning("Link trả về HTML (không phải file): %s", url)
            return None

        # Ưu tiên tên file từ Content-Disposition nếu server có gửi.
        # (Bỏ qua khi có tiền tố brand để giữ đúng tên <brand>_<số> - TaiLoc.)
        if honor_content_disposition:
            cd = r.headers.get("Content-Disposition", "")

            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)

            if m:
                save_path = save_path.with_name(
                    re.sub(r'[\\/:*?"<>|]', "_", m.group(1).strip())
                )

        save_path = _ensure_unique(save_path)

        save_path.write_bytes(r.content)

        print("DIRECT - Đã tải:", save_path)

        return save_path

    except Exception as e:

        logger.error("Lỗi tải %s: %s", url, e)
        return None


# ==========================================
# TÊN CÔNG TY PHÁT HÀNH (để xếp thư mục theo nhà cung cấp)
# Hóa đơn Fast/EasyInvoice đều gửi từ 1 địa chỉ chung -> tách theo công ty
# phát hành ghi trong nội dung email.
# ==========================================
def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# Bỏ tiền tố loại hình doanh nghiệp để lấy tên đặc trưng (KAMEREO, ...)
_ISSUER_PREFIX = re.compile(
    r"^C[ÔO]NG\s*TY\s*(?:TNHH(?:\s*MTV)?|C[ỔO]\s*PH[ẦA]N|CP|TM(?:\s*DV)?|SX(?:\s*TM)?)?\s*",
    re.IGNORECASE,
)


def extract_issuer_folder(body_text):
    """Tên thư mục theo công ty PHÁT HÀNH hóa đơn (vd 'KAMEREO'); None nếu không thấy."""
    text = _strip_html(body_text or "")

    # 1) "CÔNG TY ... xin gửi cho Quý khách" (câu mở đầu)
    m = re.search(r"(C[ÔO]NG\s*TY\s+[^.\n<]{2,70}?)\s+xin\s+g[ửu]i", text, re.IGNORECASE)
    if not m:
        # 2) chữ ký cuối: "Trân trọng kính chào ! CÔNG TY ..."
        m = re.search(r"k[íi]nh\s*ch[àa]o\s*[!.]?\s*(C[ÔO]NG\s*TY\s+[^.\n<]{2,70})", text, re.IGNORECASE)
    if not m:
        return None

    name = m.group(1).strip()
    core = _ISSUER_PREFIX.sub("", name).strip() or name
    folder = _strip_accents(core).upper()
    folder = re.sub(r'[\\/:*?"<>|]', " ", folder)
    folder = re.sub(r"\s+", " ", folder).strip()
    return folder[:60] or None


def folder_hint(subject, from_email, body_text):
    """Gợi ý thư mục theo nhà phát hành (engine dùng khi lưu theo người gửi)."""
    return extract_issuer_folder(body_text)


# ==========================================
# INTERFACE PROVIDER
# ==========================================
def is_direct_link_email(subject, from_email, body_text):
    """Email được coi là 'direct link' nếu tìm thấy ít nhất 1 link PDF/XML."""

    pdf_url, xml_url = extract_links(body_text or "")

    return bool(pdf_url or xml_url)


def download_direct_invoice(body_text, save_dir, name_prefix=""):

    pdf_url, xml_url = extract_links(body_text or "")

    if not pdf_url and not xml_url:

        print("DIRECT: Không tìm thấy link tải")
        return False

    so_hd = extract_invoice_number(body_text)

    # Tiền tố brand (vd TaiLoc: "ACECOOK_12345"); rỗng -> giữ tên cũ "<số>".
    stem = f"{name_prefix}_{so_hd}" if name_prefix else so_hd
    honor_cd = not name_prefix   # có brand -> ép tên, không theo Content-Disposition

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    ok = False

    if pdf_url:
        if _download(pdf_url, save_dir / f"{stem}.pdf", honor_content_disposition=honor_cd):
            ok = True
    else:
        print("DIRECT: Không có link PDF")

    if xml_url:
        if _download(xml_url, save_dir / f"{stem}.xml", honor_content_disposition=honor_cd):
            ok = True
    else:
        print("DIRECT: Không có link XML")

    return ok


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    import sys

    if len(sys.argv) > 1:
        html = open(sys.argv[1], encoding="utf-8").read()
        print("PDF/XML:", extract_links(html))
        print("Số HĐ  :", extract_invoice_number(html))
