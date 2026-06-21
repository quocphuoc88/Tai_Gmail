# -*- coding: utf-8 -*-
"""
providers/petrolimex.py
Nhà mạng PETROLIMEX (hoadon.petrolimex.com.vn) - hóa đơn xăng dầu.

Đặc điểm email (thường là mail FORWARD nên From là gmail cá nhân, KHÔNG phải
@petrolimex.com.vn) -> nhận diện theo BODY:
    - có "hoadon.petrolimex.com.vn", hoặc
    - có "PETROLIMEX" + "Mã tra cứu"

Email chỉ cung cấp:
    - Mã tra cứu (vd "BIVW8BMAG*" - dấu * LÀ ký tự của mã, giữ nguyên)
    - link portal https://hoadon.petrolimex.com.vn (không kèm mã trong URL)

LUỒNG TẢI (kiểu C có CAPTCHA, nhưng captcha là ẢNH TỰ SINH 4 CHỮ SỐ -> OCR được):
    1. GET /                       -> session cookie + hidden __RequestVerificationToken
    2. GET /Captcha/Show           -> ảnh captcha (gắn ASP.NET_SessionId) -> ddddocr -> 4 số
    3. POST /SearchInvoicebycode/Index
           __RequestVerificationToken, tab=content1, strFkey=<mã>, captch=<4 số>, submit=Tìm kiếm
    4. Moi checkCode trong HTML kết quả (nút Xem: ajxCall4Portal1('<checkCode>'))
    5. Moi checkCode trong HTML kết quả (nút Xem: ajxCall4Portal1('<checkCode>'))
    6. GET /SearchInvoicebycode/DownloadXml/?checkCode=<X> -> XML gốc (có chữ ký số)
    7. PDF: POST /SearchInvoicebycode/ajxPreview/ (checkCode) -> HTML bản thể hiện
           -> render ra PDF bằng headless Chrome (web gốc dùng html2pdf client-side;
           KHÔNG có endpoint tải PDF thẳng - /Download/ cũng trả XML).

Captcha không verify được trước khi submit -> chiến lược RETRY:
OCR -> submit -> nếu server báo sai captcha thì load captcha mới, thử lại (tối đa N lần).
Lọc trước: OCR phải ra ĐÚNG 4 chữ số, không thì load lại ngay (khỏi tốn 1 lần submit).

Fallback: nếu OCR fail hết số lần cho phép -> Selenium mở sẵn trang đã điền mã,
người dùng gõ captcha tay 1 lần, script tải nốt (bật/tắt qua USE_SELENIUM_FALLBACK).

Interface khớp PROVIDERS trong gmail_sync_v3:
    is_petrolimex_email(subject, from_email, body_text) -> bool
    download_petrolimex_invoice(body_text, save_dir) -> bool
"""

import os
import re
import time
import logging
from html import unescape
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://hoadon.petrolimex.com.vn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) "
        "Gecko/20100101 Firefox/151.0"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}

CAPTCHA_MAX_TRY = 6           # số lần thử captcha (mỗi lần 1 ảnh mới)
USE_SELENIUM_FALLBACK = True  # khi OCR fail hết -> mở Selenium cho gõ tay
PAGE_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60

# Petrolimex KHÔNG có PDF tải thẳng: file gốc là XML có chữ ký số (bản hợp pháp).
# "PDF" trên web là BẢN THỂ HIỆN render ở client từ HTML của ajxPreview.
# True  -> tải XML xong còn render thêm PDF (cần headless Chrome).
# False -> chỉ tải XML (đủ về mặt pháp lý cho kế toán, nhanh, không cần Chrome).
RENDER_PDF = True

# Dấu hiệu server báo SAI CAPTCHA (page render lại form kèm lỗi)
CAPTCHA_FAIL_HINTS = [
    "mã xác thực", "ma xac thuc", "không đúng", "khong dung",
    "sai mã", "sai ma", "captcha",
]
# Dấu hiệu KHÔNG TÌM THẤY hóa đơn (mã sai/hết hạn) -> dừng, không retry vô ích
NOT_FOUND_HINTS = [
    "không tìm thấy", "khong tim thay", "không có hóa đơn",
    "không tồn tại", "khong ton tai",
]


# ==========================================
# OCR CAPTCHA (ddddocr - không cần train)
# ==========================================
_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        import ddddocr  # pip install ddddocr
        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def solve_captcha(img_bytes):
    """OCR ảnh captcha. Trả về chuỗi 4 chữ số hoặc None nếu kết quả không hợp lệ."""
    try:
        raw = _get_ocr().classification(img_bytes)
    except Exception as e:
        logger.error("PETROLIMEX: lỗi OCR captcha: %s", e)
        return None

    # Captcha Petrolimex LUÔN 4 chữ số -> lọc lấy đúng 4 digit
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 4:
        return digits
    return None


# ==========================================
# TRÍCH THÔNG TIN TỪ EMAIL
# ==========================================
def _strip_html(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "",
               flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(t)
    return re.sub(r"\s+", " ", t)


def find_ma_tra_cuu(body_text):
    """
    Mã tra cứu Petrolimex: CHỮ HOA + SỐ, có thể kèm dấu '*' ở cuối
    (vd 'BIVW8BMAG*' - dấu * là ký tự của mã).
    Mã bọc trong tag HTML <b>/<span> -> strip HTML trước khi regex (ghi chú bug #2).
    """
    plain = _strip_html(body_text)

    # (?![A-Za-z0-9]) sau nhóm để không nuốt chữ liền sau khi thiếu khoảng trắng
    m = re.search(
        r"M[aã]\s*tra\s*c[uứ]+u?\s*[:\-]?\s*([A-Z0-9]{6,20}\*?)(?![A-Za-z0-9])",
        plain,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()
    return None


def extract_invoice_number(body_text):
    """Số hóa đơn để đặt tên file (fallback 'invoice')."""
    plain = _strip_html(body_text)
    m = re.search(
        r"S[oố]\s*h[oó]a\s*[dđ][oơ]n\s*[:\-]?\s*(\d{1,12})(?![A-Za-z0-9])",
        plain, re.IGNORECASE,
    )
    return m.group(1) if m else "invoice"


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_petrolimex_email(subject, from_email, body_text):
    blob = " ".join([
        (subject or "").lower(),
        (from_email or "").lower(),
        (body_text or "").lower(),
    ])

    if "hoadon.petrolimex.com.vn" in blob:
        return True

    if "petrolimex" in blob and "mã tra cứu" in _strip_html(body_text).lower():
        return True

    return False


# ==========================================
# EXTRACT checkCode TỪ HTML KẾT QUẢ (ĐA PATTERN)
# checkCode là chuỗi base64-like chứa A-Z a-z 0-9 + / = (vd
#   'DUBs8tlWdnv5mjt2+Vx31rVHJMB+Z/i6vNTLBfwgDfpoBCoZpgEWMMmb052vuTOI')
# Trong trang kết quả, mỗi hóa đơn có nút Xem:
#   onclick="ajxCall4Portal1('<checkCode>')"
# và (sau khi Xem) nút tải: downloadXml('<checkCode>') / download('<checkCode>').
# Bắt mọi pattern để chắc ăn dù response render kiểu nào.
# ==========================================
_CC = r"([A-Za-z0-9+/=_-]{20,})"

_CHECKCODE_PATTERNS = [
    r"ajxCall4Portal1\(\s*['\"]" + _CC,
    r"ajxCall4Portal1PDF\(\s*['\"]" + _CC,
    r"ajxCall4PortalPDF\(\s*['\"]" + _CC,
    r"downloadXml\(\s*['\"]" + _CC,
    r"\bdownload\(\s*['\"]" + _CC,
    r"/SearchInvoicebycode/DownloadXml/\?checkCode=" + _CC,
    r"/SearchInvoicebycode/Download/\?checkCode=" + _CC,
    r"checkCode=" + _CC,
]


def extract_check_codes(html):
    """Trả về list checkCode (giữ thứ tự, loại trùng) tìm thấy trong HTML kết quả."""
    if not html:
        return []

    page = unescape(html)
    found = []
    seen = set()

    for pat in _CHECKCODE_PATTERNS:
        for m in re.finditer(pat, page, re.IGNORECASE):
            cc = m.group(1)
            # loại nhiễu: bỏ các token rõ ràng không phải checkCode
            if cc.lower() in ("checkcode",):
                continue
            if cc not in seen:
                seen.add(cc)
                found.append(cc)
        if found:
            # ưu tiên pattern đứng trước (đáng tin hơn); có kết quả thì dừng
            break

    return found


# ==========================================
# LƯU FILE (nhận diện đuôi theo magic bytes - ghi chú bug #9)
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


def _save_file(content: bytes, save_dir: Path, default_stem: str,
               want_ext: str, cd_header: str = ""):
    """Lưu content; ưu tiên tên từ Content-Disposition, sửa đuôi theo magic bytes."""
    if not content:
        return None

    # Server trả trang HTML thay vì file -> không phải file hợp lệ
    head = content[:512].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return None

    name = f"{default_stem}{want_ext}"

    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd_header or "",
                  re.IGNORECASE)
    if m:
        name = re.sub(r'[\\/:*?"<>|]', "_", unescape(m.group(1)).strip())

    stem, ext = os.path.splitext(name)

    # Magic bytes thắng đuôi server trả về
    if content[:4] == b"%PDF":
        ext = ".pdf"
    elif content[:2] == b"PK":
        ext = ".zip"          # đề phòng nén
    elif content.lstrip()[:5] == b"<?xml":
        ext = ".xml"
    elif not ext:
        ext = want_ext

    path = _ensure_unique(save_dir / f"{stem}{ext}")
    path.write_bytes(content)
    print("PETROLIMEX - Đã tải:", path)
    return path


# ==========================================
# LẤY __RequestVerificationToken + form theo tab content1
# ==========================================
def _get_form_token(html):
    """
    Trang chủ có 2 form (content1 = tra theo mã, content2 = tra theo thông tin),
    mỗi form 1 __RequestVerificationToken. Lấy token của FORM content1.
    """
    if not html:
        return None

    page = unescape(html)

    # Khoanh vùng form chứa tab=content1 rồi lấy token trong đó
    # (form content1 luôn đứng trước content2 trong trang)
    idx_c1 = page.find('value="content1"')
    idx_c2 = page.find('value="content2"')

    region = page if idx_c1 == -1 else page[:(idx_c2 if idx_c2 > idx_c1 else len(page))]

    m = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        region, re.IGNORECASE,
    )
    if m:
        return m.group(1)

    # fallback: token đầu tiên trong trang
    m = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        page, re.IGNORECASE,
    )
    return m.group(1) if m else None


# ==========================================
# LẤY HTML BẢN THỂ HIỆN (cho việc render PDF)
# Nút PDF trên web gọi ajxCall4Portal1PDF -> POST /SearchInvoicebycode/ajxPreview/
# với checkCode -> server trả JSON {"str": "<html hóa đơn>"} -> client html2pdf.
# Ta lấy đúng data.str đó rồi tự render PDF.
# ==========================================
def _fetch_preview_html(session, check_code):
    try:
        r = session.post(
            BASE_URL + "/SearchInvoicebycode/ajxPreview/",
            data={"checkCode": check_code},
            timeout=PAGE_TIMEOUT,
            headers={
                "Referer": BASE_URL + "/SearchInvoicebycode/Index",
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        r.raise_for_status()
    except Exception as e:
        logger.error("PETROLIMEX: lỗi ajxPreview: %s", e)
        return None

    # Server trả JSON {"str": "..."} ; phòng khi trả thẳng HTML
    try:
        data = r.json()
        if isinstance(data, dict):
            html = data.get("str") or data.get("Str") or ""
        else:
            html = str(data)
    except ValueError:
        html = r.text

    html = (html or "").strip()
    return html or None


# ==========================================
# RENDER HTML -> PDF BẰNG HEADLESS CHROME (CDP Page.printToPDF)
# Tận dụng Selenium đã có sẵn (MISA/SoftDream dùng), không cần cài thêm binary.
# Chèn <base href=BASE_URL> để CSS/ảnh tương đối của hóa đơn load đúng.
# ==========================================
def _render_pdf_from_html(html, out_path: Path):
    try:
        import base64
        import tempfile
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("PETROLIMEX: chưa cài selenium -> không render được PDF")
        return None

    # Bọc HTML chuẩn + base href để tài nguyên tương đối trỏ về domain Petrolimex
    full_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<base href='{BASE_URL}/'>"
        "</head><body>" + html + "</body></html>"
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8")
    try:
        tmp.write(full_html)
        tmp.close()

        opt = Options()
        opt.add_argument("--headless=new")
        opt.add_argument("--disable-gpu")
        opt.add_argument("--no-sandbox")

        driver = webdriver.Chrome(options=opt)
        try:
            driver.get("file:///" + tmp.name.replace("\\", "/"))
            time.sleep(1.5)  # chờ CSS/ảnh tải xong

            result = driver.execute_cdp_cmd("Page.printToPDF", {
                "printBackground": True,
                "paperWidth": 8.27,    # A4
                "paperHeight": 11.69,
                "marginTop": 0.2, "marginBottom": 0.2,
                "marginLeft": 0.2, "marginRight": 0.2,
            })
            pdf_bytes = base64.b64decode(result["data"])
        finally:
            driver.quit()

        if pdf_bytes[:4] != b"%PDF":
            print("PETROLIMEX: render PDF lỗi (không phải %PDF)")
            return None

        out_path = _ensure_unique(out_path)
        out_path.write_bytes(pdf_bytes)
        print("PETROLIMEX - Đã render PDF:", out_path)
        return out_path

    except Exception as e:
        logger.error("PETROLIMEX: lỗi render PDF: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ==========================================
# TẢI 1 checkCode: XML (gốc, tải thẳng) + PDF (render từ bản thể hiện)
# ==========================================
def _download_by_checkcode(session, check_code, save_dir, stem):
    pdf_ok = xml_ok = False
    xml_path = None

    # ---- XML: file gốc có chữ ký số, tải thẳng ----
    try:
        url = f"{BASE_URL}/SearchInvoicebycode/DownloadXml/?checkCode={check_code}"
        r = session.get(url, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True,
                        headers={"Referer": f"{BASE_URL}/SearchInvoicebycode/Index"})
        if r.status_code == 200:
            xml_path = _save_file(r.content, save_dir, stem, ".xml",
                                  r.headers.get("Content-Disposition", ""))
            if xml_path:
                xml_ok = True
        else:
            print(f"PETROLIMEX XML: HTTP {r.status_code}")
    except Exception as e:
        logger.error("PETROLIMEX: lỗi tải XML: %s", e)

    # ---- PDF: render từ HTML bản thể hiện (ajxPreview) ----
    # Đặt PDF TRÙNG TÊN với XML (chỉ khác đuôi) -> thành 1 cặp dễ quản lý.
    # XML thường được đặt tên theo Content-Disposition (vd HDGTGT_K26TAN_01302173.xml),
    # nên lấy stem của file XML đã lưu; nếu không có XML thì fallback theo số hóa đơn.
    if RENDER_PDF:
        pdf_stem = xml_path.stem if xml_path else stem
        html = _fetch_preview_html(session, check_code)
        if html:
            if _render_pdf_from_html(html, save_dir / f"{pdf_stem}.pdf"):
                pdf_ok = True
        else:
            print("PETROLIMEX: không lấy được HTML bản thể hiện -> bỏ PDF")

    return pdf_ok, xml_ok


# ==========================================
# LUỒNG CHÍNH BẰNG REQUESTS (OCR captcha + retry)
# ==========================================
def _download_via_requests(ma_tra_cuu, save_dir, stem):
    session = requests.Session()
    session.headers.update(HEADERS)

    for attempt in range(1, CAPTCHA_MAX_TRY + 1):

        # 1. GET trang chủ -> session + token (fresh mỗi lần cho chắc)
        try:
            r0 = session.get(BASE_URL + "/", timeout=PAGE_TIMEOUT)
            r0.raise_for_status()
        except Exception as e:
            logger.error("PETROLIMEX: không mở được trang chủ: %s", e)
            return None  # None = lỗi mạng/hệ thống -> có thể rơi xuống Selenium

        token = _get_form_token(r0.text)
        if not token:
            logger.error("PETROLIMEX: không tìm thấy __RequestVerificationToken")
            return None

        # 2. GET ảnh captcha (gắn session) -> OCR
        try:
            rc = session.get(
                BASE_URL + "/Captcha/Show",
                timeout=PAGE_TIMEOUT,
                headers={"Referer": BASE_URL + "/"},
            )
            rc.raise_for_status()
        except Exception as e:
            logger.error("PETROLIMEX: không tải được captcha: %s", e)
            return None

        captcha = solve_captcha(rc.content)
        if not captcha:
            print(f"PETROLIMEX: OCR captcha không ra 4 số (lần {attempt}) -> thử lại")
            continue  # load captcha mới, chưa tốn lần submit

        print(f"PETROLIMEX: captcha OCR = {captcha} (lần {attempt})")

        # 3. POST tra cứu
        data = {
            "__RequestVerificationToken": token,
            "tab": "content1",
            "strFkey": ma_tra_cuu,
            "captch": captcha,            # CHÚ Ý: field tên 'captch' (thiếu 'a')
            "submit": "Tìm kiếm",
        }
        try:
            rp = session.post(
                BASE_URL + "/SearchInvoicebycode/Index",
                data=data,
                timeout=PAGE_TIMEOUT,
                headers={
                    "Referer": BASE_URL + "/",
                    "Origin": BASE_URL,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                allow_redirects=True,
            )
            rp.raise_for_status()
        except Exception as e:
            logger.error("PETROLIMEX: lỗi POST tra cứu: %s", e)
            return None

        html = rp.text
        low = _strip_html(html).lower()

        # 4. Có checkCode -> THÀNH CÔNG
        codes = extract_check_codes(html)
        if codes:
            print(f"PETROLIMEX: tìm thấy {len(codes)} checkCode")
            pdf_ok = xml_ok = False
            for cc in codes:
                p, x = _download_by_checkcode(session, cc, save_dir, stem)
                pdf_ok = pdf_ok or p
                xml_ok = xml_ok or x
            return pdf_ok or xml_ok

        # 5. Không có checkCode -> phân loại lỗi
        if any(h in low for h in NOT_FOUND_HINTS):
            print("PETROLIMEX: không tìm thấy hóa đơn (mã sai/hết hạn) -> dừng")
            return False

        if any(h in low for h in CAPTCHA_FAIL_HINTS):
            print(f"PETROLIMEX: sai captcha (lần {attempt}) -> thử lại")
            continue

        # Không rõ -> coi như sai captcha, thử lại vài lần rồi thôi
        print(f"PETROLIMEX: kết quả không có checkCode (lần {attempt}) -> thử lại")
        # debug: lưu html để soi nếu cần
        try:
            (Path(save_dir) / f"_debug_petrolimex_{attempt}.html").write_text(
                html, encoding="utf-8", errors="ignore")
        except Exception:
            pass

    print("PETROLIMEX: hết số lần thử captcha bằng OCR")
    return None  # None -> để gọi Selenium fallback


# ==========================================
# FALLBACK SELENIUM (gõ captcha tay 1 lần)
# Mở trang, điền sẵn mã tra cứu, để người dùng nhập captcha + bấm Tìm kiếm,
# script tự bắt checkCode rồi tải. Chỉ dùng khi OCR fail hết.
# ==========================================
def _download_via_selenium(ma_tra_cuu, save_dir, stem):
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("PETROLIMEX: chưa cài selenium, bỏ qua fallback")
        return False

    save_dir = os.path.abspath(str(save_dir))
    os.makedirs(save_dir, exist_ok=True)

    opt = Options()
    prefs = {
        "download.default_directory": save_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }
    opt.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=opt)

    def snapshot():
        try:
            return set(os.listdir(save_dir))
        except OSError:
            return set()

    def wait_new_file(before, timeout=DOWNLOAD_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            cur = snapshot()
            done = [f for f in cur - before
                    if not f.endswith((".crdownload", ".tmp"))]
            downloading = any(f.endswith(".crdownload") for f in cur)
            if done and not downloading:
                return True
            time.sleep(1)
        return False

    try:
        driver.get(BASE_URL + "/")

        # Điền sẵn mã tra cứu vào ô #strFkey
        try:
            box = WebDriverWait(driver, PAGE_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "strFkey"))
            )
            box.clear()
            box.send_keys(ma_tra_cuu)
        except Exception:
            print("PETROLIMEX: không thấy ô nhập mã - kiểm tra trang")

        print("=" * 60)
        print("PETROLIMEX [SELENIUM]: Mã đã điền sẵn:", ma_tra_cuu)
        print(">>> Vui lòng GÕ CAPTCHA trên cửa sổ Chrome rồi bấm 'Tìm kiếm'.")
        print(">>> Script đang chờ trang kết quả hiện nút 'Xem'/'Tải'...")
        print("=" * 60)

        # Chờ tới khi trang có dấu hiệu kết quả (nút Xem / hàm ajxCall4Portal1)
        def results_ready(d):
            src = d.page_source
            return ("ajxCall4Portal1(" in src and "'" in src) or \
                   bool(extract_check_codes(src))

        WebDriverWait(driver, 180).until(results_ready)

        codes = extract_check_codes(driver.page_source)
        if not codes:
            # thử bấm "Xem" để load preview rồi lấy checkCode
            try:
                el = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//*[contains(text(),'Xem')]"))
                )
                el.click()
                WebDriverWait(driver, 20).until(
                    lambda d: bool(extract_check_codes(d.page_source)))
                codes = extract_check_codes(driver.page_source)
            except Exception:
                pass

        if not codes:
            print("PETROLIMEX [SELENIUM]: không bắt được checkCode")
            return False

        # Có checkCode -> tải bằng requests dùng cookie của Chrome
        sess = requests.Session()
        sess.headers.update(HEADERS)
        for c in driver.get_cookies():
            sess.cookies.set(c["name"], c["value"])

        ok = False
        for cc in codes:
            p, x = _download_by_checkcode(sess, cc, Path(save_dir), stem)
            ok = ok or p or x

        # Nếu requests vẫn fail (cookie/anti-leech), thử click nút tải trong Chrome
        if not ok:
            before = snapshot()
            for xp in ["//*[contains(text(),'Tải hóa đơn xml')]",
                       "//*[contains(text(),'Tải hóa đơn')]",
                       "//button[contains(@name,'down')]"]:
                try:
                    WebDriverWait(driver, 8).until(
                        EC.element_to_be_clickable((By.XPATH, xp))).click()
                except Exception:
                    continue
            if wait_new_file(before):
                ok = True

        return ok

    except Exception as e:
        print("PETROLIMEX SELENIUM ERROR:", e)
        return False
    finally:
        driver.quit()


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_petrolimex_invoice(body_text, save_dir):
    ma_tra_cuu = find_ma_tra_cuu(body_text)
    if not ma_tra_cuu:
        print("PETROLIMEX: không tìm thấy mã tra cứu trong email")
        return False

    print("PETROLIMEX CODE:", ma_tra_cuu)

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    stem = extract_invoice_number(body_text)

    # 1. Thử requests + OCR
    res = _download_via_requests(ma_tra_cuu, save_dir, stem)
    if res is True:
        return True
    if res is False:
        # False = đã xác định không có hóa đơn / mã sai -> không cần Selenium
        return False

    # res is None -> OCR fail hết hoặc lỗi -> fallback Selenium gõ tay
    if USE_SELENIUM_FALLBACK:
        print("PETROLIMEX: chuyển sang Selenium (gõ captcha tay)...")
        return _download_via_selenium(ma_tra_cuu, save_dir, stem)

    return False


# ==========================================
# TEST OFFLINE
#   python petrolimex.py mau.eml        -> test extract mã + nhận diện email
#   python petrolimex.py --live MÃ DIR  -> chạy thật 1 mã tra cứu
# ==========================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) >= 4 and sys.argv[1] == "--live":
        ma, out = sys.argv[2], sys.argv[3]
        fake_body = f"Mã tra cứu: {ma}"
        print("KẾT QUẢ:", download_petrolimex_invoice(fake_body, out))

    elif len(sys.argv) > 1:
        import email
        from email import policy
        with open(sys.argv[1], "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body = "\n".join(
            p.get_content() for p in msg.walk()
            if p.get_content_type() in ("text/plain", "text/html")
        )
        print("is_petrolimex_email:",
              is_petrolimex_email(msg["Subject"], "x@gmail.com", body))
        print("mã tra cứu         :", find_ma_tra_cuu(body))
        print("số hóa đơn         :", extract_invoice_number(body))