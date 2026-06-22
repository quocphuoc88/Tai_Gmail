# -*- coding: utf-8 -*-
"""
providers/softdream.py
Nhà mạng SoftDreams / EasyInvoice (hoadon-noreply@softdreams.vn).

Đặc điểm email:
- Có khi đính kèm sẵn PDF/XML -> gmail_sync tự tải (provider trả False là được).
- Có khi chỉ có link:
    .../Invoice/ViewFromEmail?token=...     (trang xem hóa đơn)
    .../Invoice/DownloadInvPdf?token=...    (TẢI PDF TRỰC TIẾP - không cần Selenium)
  XML không có link trực tiếp trong email.

Chiến lược tải XML (theo thứ tự):
1. Thử các endpoint "anh em" với DownloadInvPdf (DownloadInvXml, DownloadXml, ...)
   -> nếu server hỗ trợ thì xong, không tốn Selenium.
2. Fallback: mở trang ViewFromEmail bằng Selenium, bấm nút tải XML (giống MISA).

Interface khớp PROVIDERS trong gmail_sync_v3:
    is_softdream_email(subject, from_email, body_text) -> bool
    download_softdream_invoice(body_text, save_dir) -> bool
"""

import os
import re
import time
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

# Các endpoint XML khả dĩ (thử lần lượt, thay cho "DownloadInvPdf" trong link PDF)
XML_ENDPOINT_CANDIDATES = [
    "DownloadInvXml",
    "DownloadXml",
    "DownloadInvoiceXml",
]

# Bật/tắt fallback Selenium khi không endpoint XML nào chạy
USE_SELENIUM_FALLBACK = True
PAGE_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_softdream_email(subject, from_email, body_text):

    f = (from_email or "").lower()

    if f.endswith("@softdreams.vn"):
        return True

    b = (body_text or "").lower()

    # Email có khi được KHÁCH forward -> From là gmail của khách, không phải
    # softdreams.vn. Khi đó nhận diện theo DOMAIN đặc trưng của Softdream/EasyInvoice.
    # KHÔNG dùng marker đường dẫn chung như "/invoice/viewfromemail" vì nhiều
    # nhà cung cấp khác (vd IPOS) cũng dùng đường dẫn đó -> nhận nhầm.
    markers = (
        "softdreams",          # nguồn gốc trong header forward
        "easyinvoice.vn",      # tracuu.easyinvoice.vn ...
        "easyinvoice.com.vn",  # easy-pit / sản phẩm EasyInvoice
    )
    return any(mk in b for mk in markers)


# ==========================================
# TRÍCH THÔNG TIN TỪ BODY
# ==========================================
def _strip_html(html):

    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text)


def extract_softdream_info(body_html):
    """
    Trả về dict:
        pdf_url  : link DownloadInvPdf (None nếu không có)
        view_url : link ViewFromEmail  (None nếu không có)
        so_hd    : số hóa đơn (fallback 'invoice')
        ma_tc    : mã tra cứu (có thể None)
    """

    body_html = body_html or ""

    info = {"pdf_url": None, "view_url": None,
            "so_hd": "invoice", "ma_tc": None}

    hrefs = [
        unescape(h) for h in
        re.findall(r'href\s*=\s*["\']([^"\']+)["\']', body_html, re.IGNORECASE)
    ]

    for h in hrefs:

        hl = h.lower()

        if "downloadinvpdf" in hl and not info["pdf_url"]:
            info["pdf_url"] = h

        elif "viewfromemail" in hl and not info["view_url"]:
            info["view_url"] = h

    text = _strip_html(body_html)

    # (?![A-Za-z0-9]) tránh khớp nhầm "Ký hiệu MẪU SỐ HÓA ĐƠN: 1C26TAA" -> "1"
    m = re.search(r"S[oố]\s*h[oó]a\s*[dđ][oơ]n\s*[:\-]?\s*(\d{1,8})(?![A-Za-z0-9])",
                  text, re.IGNORECASE)
    if m:
        info["so_hd"] = m.group(1)

    m = re.search(r"M[aã]\s*tra\s*c[uứ]+u?\s*[:\-]?\s*([A-Z0-9]{6,25})",
                  text, re.IGNORECASE)
    if m:
        info["ma_tc"] = m.group(1).upper()

    return info


# ==========================================
# TẢI FILE QUA REQUESTS
# ==========================================
def _ensure_unique(path: Path) -> Path:

    if not path.exists():
        return path

    i = 1
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _save_response(r, save_dir: Path, default_name: str):
    """Lưu response thành file; tự nhận diện đuôi theo nội dung."""

    content = r.content

    # Server trả HTML -> không phải file
    if b"<html" in content[:500].lower():
        return None

    name = default_name

    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        name = re.sub(r'[\\/:*?"<>|]', "_", unescape(m.group(1)).strip())

    # Sửa đuôi theo magic bytes nếu cần
    stem, ext = os.path.splitext(name)
    if content[:4] == b"%PDF":
        ext = ".pdf"
    elif content[:2] == b"PK":
        ext = ".zip"          # EasyInvoice hay nén XML trong zip
    elif content.lstrip()[:5] == b"<?xml":
        ext = ext if ext.lower() == ".xml" else ".xml"

    path = _ensure_unique(save_dir / f"{stem}{ext}")
    path.write_bytes(content)
    print("SOFTDREAM - Đã tải:", path)
    return path


def _try_get(session, url, save_dir, default_name, timeout=30):

    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None
        return _save_response(r, save_dir, default_name)
    except Exception as e:
        logger.debug("GET fail %s: %s", url, e)
        return None


# ==========================================
# TẢI XML QUA TRANG ViewFromEmail (KHÔNG CẦN SELENIUM)
# Theo capture DevTools: nút tải XML gọi
#   GET /Invoice/Download?fileGuid=<GUID>&fileName=HOADON_..._.xml
# kèm cookie session + Referer của trang ViewFromEmail.
# fileGuid nằm trong HTML/JS của trang xem hóa đơn.
# ==========================================
_GUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def _download_all_via_view_page(session, view_url, save_dir, default_stem,
                                timeout=30):
    """
    Mở trang ViewFromEmail 1 lần, móc TẤT CẢ các cặp fileGuid + fileName
    rồi tải hết (XML, PDF, ZIP...). Trả về list Path đã lưu.
    Theo capture DevTools: cả nút PDF lẫn XML đều gọi
        GET /Invoice/Download?fileGuid=<GUID>&fileName=<tên file>
    chỉ khác fileName (.xml / .zip).
    """

    saved = []

    try:
        r = session.get(view_url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        logger.error("SOFTDREAM: không mở được trang xem hóa đơn: %s", e)
        return saved

    page = unescape(r.text)

    base = re.match(r"(https?://[^/]+)", r.url).group(1)

    # ---- Gom mọi cặp guid + fileName ----
    entries = []   # list (guid, fileName)
    seen = set()

    # Cách 1: link đầy đủ Download?fileGuid=...&fileName=...
    for m in re.finditer(
        r"Download\?fileGuid=(" + _GUID_RE + r")&fileName=([^\"'&<>\s]+)",
        page,
        re.IGNORECASE,
    ):
        key = (m.group(1).lower(), m.group(2).lower())
        if key not in seen:
            seen.add(key)
            entries.append((m.group(1), m.group(2)))

    # Cách 2: fileGuid + fileName nằm rời trong JS
    if not entries:
        guids = re.findall(
            r"fileGuid['\"]?\s*[:=]\s*['\"](" + _GUID_RE + r")['\"]",
            page, re.IGNORECASE)

        names = re.findall(
            r"['\"]([\w\-\.]+\.(?:xml|pdf|zip))['\"]",
            page, re.IGNORECASE)

        for i, g in enumerate(dict.fromkeys(guids)):
            name = names[i] if i < len(names) else f"{default_stem}_{i}"
            key = (g.lower(), name.lower())
            if key not in seen:
                seen.add(key)
                entries.append((g, name))

    if not entries:
        logger.warning("SOFTDREAM: không tìm thấy fileGuid trong trang xem hóa đơn")
        return saved

    # ---- Tải từng entry ----
    for file_guid, file_name in entries:

        dl_url = f"{base}/Invoice/Download?fileGuid={file_guid}&fileName={file_name}"

        logger.info("SOFTDREAM tải: %s", dl_url)

        try:
            r = session.get(
                dl_url,
                headers={"Referer": view_url},
                timeout=timeout,
                allow_redirects=True,
            )
            if r.status_code != 200:
                continue
            p = _save_response(r, save_dir, file_name)
            if p:
                saved.append(p)
        except Exception as e:
            logger.error("SOFTDREAM: lỗi tải %s: %s", dl_url, e)

    return saved


# ==========================================
# FALLBACK SELENIUM (giống MISA)
# Trang ViewFromEmail render bằng JS, fileGuid chỉ sinh ra khi bấm nút
# -> requests không thấy gì, phải dùng trình duyệt thật.
# Tải CẢ PDF lẫn XML trong CÙNG 1 phiên Chrome.
# ==========================================
def _selenium_download(view_url, save_dir, need_pdf=True, need_xml=True):
    """Trả về (pdf_ok, xml_ok)."""

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("SOFTDREAM: chưa cài selenium, bỏ qua fallback")
        return False, False

    save_dir = os.path.abspath(str(save_dir))

    chrome_options = Options()
    prefs = {
        "download.default_directory": save_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=chrome_options)

    def snapshot():
        try:
            return set(os.listdir(save_dir))
        except OSError:
            return set()

    def wait_download(before, timeout=DOWNLOAD_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            cur = snapshot()
            new_done = [f for f in cur - before
                        if not f.endswith((".crdownload", ".tmp"))]
            downloading = any(f.endswith(".crdownload") for f in cur)
            if new_done and not downloading:
                return True
            time.sleep(1)
        return False

    def click_and_wait(xpaths, label):
        """Thử lần lượt các xpath, click được thì chờ file về."""
        before = snapshot()
        for xp in xpaths:
            try:
                el = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                el.click()
                break
            except Exception:
                continue
        else:
            print(f"SOFTDREAM: không tìm thấy nút tải {label} trên trang")
            return False

        if wait_download(before):
            print(f"SOFTDREAM {label} OK (selenium)")
            return True

        print(f"SOFTDREAM {label}: timeout chờ tải (selenium)")
        return False

    PDF_XPATHS = [
        "//*[contains(text(),'Tải PDF')]",
        "//*[contains(text(),'Tải hóa đơn PDF')]",
        "//*[contains(text(),'PDF')]",
        "//*[contains(@href,'Pdf') or contains(@href,'pdf')]",
        "//*[contains(@onclick,'Pdf') or contains(@onclick,'pdf')]",
    ]

    XML_XPATHS = [
        "//*[contains(text(),'Tải XML')]",
        "//*[contains(text(),'Tải hóa đơn XML')]",
        "//*[contains(text(),'XML')]",
        "//*[contains(@href,'Xml') or contains(@href,'xml')]",
        "//*[contains(@onclick,'Xml') or contains(@onclick,'xml')]",
    ]

    pdf_ok = xml_ok = False

    try:
        driver.get(view_url)

        if need_pdf:
            pdf_ok = click_and_wait(PDF_XPATHS, "PDF")

        if need_xml:
            xml_ok = click_and_wait(XML_XPATHS, "XML")

        return pdf_ok, xml_ok

    except Exception as e:
        print("SOFTDREAM SELENIUM ERROR:", e)
        return pdf_ok, xml_ok

    finally:
        driver.quit()


# Giữ tên cũ để tương thích nếu nơi khác có gọi
def _selenium_download_xml(view_url, save_dir):
    _, xml_ok = _selenium_download(view_url, save_dir,
                                   need_pdf=False, need_xml=True)
    return xml_ok


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_softdream_invoice(body_text, save_dir):

    info = extract_softdream_info(body_text)

    if not info["pdf_url"] and not info["view_url"]:
        # Email dạng đính kèm, không có link
        # -> trả False để gmail_sync rơi xuống tải file đính kèm
        print("SOFTDREAM: không có link trong email -> tải đính kèm")
        return False

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    so_hd = info["so_hd"]

    session = requests.Session()
    session.headers.update(HEADERS)

    # ---------- CÁCH CHÍNH: vào trang ViewFromEmail, tải HẾT mọi entry
    # fileGuid (cả PDF/ZIP lẫn XML) - theo capture DevTools cả 2 nút
    # đều gọi /Invoice/Download?fileGuid=... ----------
    saved = []

    if info["view_url"]:
        saved = _download_all_via_view_page(
            session, info["view_url"], save_dir, so_hd
        )

    def _has(*exts):
        return any(p.suffix.lower() in exts for p in saved)

    # .zip của EasyInvoice chứa bản PDF/XML nén -> tính là có
    pdf_ok = _has(".pdf", ".zip")
    xml_ok = _has(".xml", ".zip")

    # ---------- DỰ PHÒNG PDF: link DownloadInvPdf trong email
    # (thử bằng session ĐÃ CÓ cookie từ trang view - có thể link email
    # chỉ fail khi gọi nguội, không có session) ----------
    if not pdf_ok and info["pdf_url"]:
        if _try_get(session, info["pdf_url"], save_dir, f"{so_hd}.pdf"):
            pdf_ok = True
        else:
            print("SOFTDREAM PDF: link trong email không tải được")

    # ---------- DỰ PHÒNG XML: endpoint anh em ----------
    if not xml_ok and info["pdf_url"]:
        for ep in XML_ENDPOINT_CANDIDATES:
            url = re.sub(r"DownloadInvPdf", ep, info["pdf_url"],
                         flags=re.IGNORECASE)
            if _try_get(session, url, save_dir, f"{so_hd}.xml"):
                xml_ok = True
                break

    # ---------- DỰ PHÒNG CUỐI: Selenium - 1 phiên Chrome tải hết
    # những gì còn thiếu (cả PDF lẫn XML) ----------
    if (not pdf_ok or not xml_ok) and USE_SELENIUM_FALLBACK and info["view_url"]:

        sel_pdf, sel_xml = _selenium_download(
            info["view_url"],
            save_dir,
            need_pdf=not pdf_ok,
            need_xml=not xml_ok,
        )

        pdf_ok = pdf_ok or sel_pdf
        xml_ok = xml_ok or sel_xml

    ok = pdf_ok or xml_ok or bool(saved)

    if not pdf_ok:
        print("SOFTDREAM PDF: không tải được")
    if not xml_ok:
        print("SOFTDREAM XML: không tải được")

    return ok
