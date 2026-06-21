# -*- coding: utf-8 -*-
"""
providers/win.py
Nhà mạng WIN Invoice (wininvoice.vn / tracuu.wininvoice.vn).

Đặc điểm email (mẫu HĐĐT 00000275 - 06/2026):
- Thường là mail FORWARD -> From là gmail cá nhân, KHÔNG phải
  hddt.no-reply@wininvoice.com -> nhận diện theo BODY ("wininvoice").
- KHÔNG có file đính kèm, KHÔNG có link tải trực tiếp.
- Mọi link bị bọc tracking AWS: awstrack.me/L0/<url-encoded-target>/1/...
  -> PHẢI giải mã (unquote 2 lần) trước khi parse.
- Link tra cứu giải mã ra dạng:
    https://tracuu.wininvoice.vn/?mst=<MST bán>&cmpn=<MST bán>
        &code=<MÃ TRA CỨU>&cs_mst=<MST mua>&rec_email=<email>
- Link "Xem nhanh hóa đơn" có thêm /bill/view_inv?token=<TOKEN> (token
  url-encode 2 lần trong awstrack).
- Body text có: "Mã tra cứu: Z1260600986913074", "Mã công ty: 0312089194",
  "Hóa đơn số: 00000275".

Ưu tiên bắt mã từ THAM SỐ URL (code=, mst=) trước, text chỉ là fallback
(nguyên tắc #3 trong GHI_CHU).

LUỒNG TẢI:
1. requests: GET trang view_inv (token) hoặc trang tra cứu (code+mst),
   scan link/endpoint tải PDF/XML trong HTML trả về. Nếu trang render
   thuần server-side thì xong, không cần Selenium.
2. Fallback Selenium (kiểu C): mở trang chủ, điền Mã tra cứu + Mã công ty,
   bấm "Xem hóa đơn", rồi bấm các nút tải theo XPath heuristic.
   (Trang nghi render bằng JS -> requests có thể không thấy gì.)

⚠️ Luồng tải viết theo phỏng đoán cấu trúc trang (chưa có capture DevTools).
   Nếu fail: gửi Copy-as-cURL của nút tải trên tracuu.wininvoice.vn
   (xem mục 5 GHI_CHU) để chuyển hẳn về requests.

Interface khớp PROVIDERS trong gmail_sync_v3:
    is_win_email(subject, from_email, body_text) -> bool
    download_win_invoice(body_text, save_dir) -> bool
"""

import os
import re
import time
import logging
from html import unescape
from pathlib import Path
from urllib.parse import unquote, quote, urlsplit, parse_qs

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://tracuu.wininvoice.vn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}

USE_SELENIUM_FALLBACK = True
PAGE_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60


# ==========================================
# HELPERS
# ==========================================
def _strip_html(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "",
               flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(t)
    return re.sub(r"\s+", " ", t)


def _decode_awstrack(url):
    """
    Giải link tracking AWS SES:
        http(s)://xxx.awstrack.me/L0/<url-encoded-target>/1/<msgid>/<sig>
    Target bị encode 1-2 lần (token bên trong encode 2 lần) -> unquote 2 lần.
    Link thường trả về nguyên vẹn.
    """
    m = re.search(r"awstrack\.me/L0/(.+?)/\d+/", url or "", re.IGNORECASE)
    if not m:
        return url
    return unquote(unquote(m.group(1)))


def _all_links(body_html):
    """Mọi href trong body (đã unescape + giải awstrack)."""
    hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']',
                       body_html or "", re.IGNORECASE)
    out = []
    for h in hrefs:
        h = unescape(h).strip()
        if h.lower().startswith("http"):
            out.append(_decode_awstrack(h))
    # body forward dạng text/plain cũng chứa link trong <...>
    for h in re.findall(r"<(https?://[^>\s]+)>", body_html or ""):
        out.append(_decode_awstrack(unescape(h)))
    return out


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_win_email(subject, from_email, body_text):
    f = (from_email or "").lower()

    # From gốc (email không forward)
    if f.endswith("@wininvoice.com") or f.endswith("@wininvoice.vn"):
        return True

    # Mail forward -> nhận diện theo body
    b = (body_text or "").lower()
    return ("tracuu.wininvoice.vn" in b
            or "wininvoice.com" in b
            or "wininvoice.vn" in b)


# ==========================================
# TRÍCH THÔNG TIN TỪ BODY
# ==========================================
def extract_win_info(body_html):
    """
    Trả về dict:
        code     : mã tra cứu (None nếu không có)
        mst      : mã công ty / MST bên bán (None nếu không có)
        view_url : link /bill/view_inv?token=... đã giải mã (None nếu không có)
        lookup_url: link tra cứu đầy đủ ?mst=..&code=.. (None nếu không có)
        so_hd    : số hóa đơn (fallback 'invoice')
    """
    body_html = body_html or ""
    info = {"code": None, "mst": None, "view_url": None,
            "lookup_url": None, "so_hd": "invoice"}

    # ---- Tầng 1: tham số trong URL (tin cậy nhất) ----
    for link in _all_links(body_html):
        ll = link.lower()
        if "wininvoice" not in ll:
            continue

        # token view_inv (có thể bị nối lệch vào sau rec_email do template)
        m = re.search(r"/bill/view_inv\?token=([^&\s\"'<>]+)", link,
                      re.IGNORECASE)
        if m and not info["view_url"]:
            # token gốc bị encode 2 lần trong awstrack -> sau khi giải mã
            # chứa '/' và '==' -> phải encode lại 1 lần khi ghép URL
            token = quote(m.group(1), safe="")
            info["view_url"] = f"{BASE_URL}/bill/view_inv?token={token}"

        # code= / mst= / cmpn=
        try:
            qs = parse_qs(urlsplit(link).query)
        except ValueError:
            qs = {}
        if not info["code"] and qs.get("code"):
            info["code"] = qs["code"][0].strip()
        if not info["mst"]:
            v = qs.get("mst") or qs.get("cmpn")
            if v:
                info["mst"] = v[0].strip()

        if not info["lookup_url"] and "code=" in ll and "tracuu" in ll:
            # cắt bỏ phần /bill/view_inv bị nối lệch (nếu có)
            info["lookup_url"] = link.split("/bill/view_inv")[0]

    # ---- Tầng 2: text thuần (fallback khi template đổi) ----
    plain = _strip_html(body_html)

    if not info["code"]:
        m = re.search(
            r"M[aã]\s*tra\s*c[uứ]+u?\s*[:\-]?\s*([A-Z0-9]{8,30})(?![A-Za-z0-9])",
            plain, re.IGNORECASE)
        if m:
            info["code"] = m.group(1).upper()

    if not info["mst"]:
        m = re.search(
            r"M[aã]\s*c[oô]ng\s*ty\s*[:\-]?\s*(\d{10,14})(?![A-Za-z0-9])",
            plain, re.IGNORECASE)
        if m:
            info["mst"] = m.group(1)

    # Số hóa đơn: "Hóa đơn số: 00000275" hoặc "HĐĐT: 00000275" trong subject/body
    m = re.search(
        r"H[oó]a\s*[dđ][oơ]n\s*s[oố]\s*[:\-]?\s*(\d{1,12})(?![A-Za-z0-9])",
        plain, re.IGNORECASE)
    if not m:
        m = re.search(r"H[ĐD]{1,2}[ĐD]?T\s*[:\-]?\s*(\d{1,12})(?![A-Za-z0-9])",
                      plain, re.IGNORECASE)
    if m:
        info["so_hd"] = m.group(1).lstrip("0") or m.group(1)

    return info


# ==========================================
# LƯU FILE (magic bytes thắng đuôi - nguyên tắc #10)
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


def _save_file(content: bytes, save_dir: Path, default_name: str,
               cd_header: str = ""):
    if not content:
        return None

    head = content[:512].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return None  # server trả trang web, không phải file

    name = default_name
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
                  cd_header or "", re.IGNORECASE)
    if m:
        name = re.sub(r'[\\/:*?"<>|]', "_", unescape(m.group(1)).strip())

    stem, ext = os.path.splitext(name)
    if content[:4] == b"%PDF":
        ext = ".pdf"
    elif content[:2] == b"PK":
        ext = ".zip"
    elif content.lstrip()[:5] == b"<?xml":
        ext = ".xml"

    path = _ensure_unique(save_dir / f"{stem}{ext}")
    path.write_bytes(content)
    print("WIN - Đã tải:", path)
    return path


def _try_get(session, url, save_dir, default_name, referer=None, timeout=30):
    try:
        headers = {"Referer": referer} if referer else {}
        r = session.get(url, headers=headers, timeout=timeout,
                        allow_redirects=True)
        if r.status_code != 200:
            return None
        return _save_file(r.content, save_dir, default_name,
                          r.headers.get("Content-Disposition", ""))
    except Exception as e:
        logger.debug("WIN GET fail %s: %s", url, e)
        return None


# ==========================================
# REQUESTS: mở trang view/tra cứu, scan link tải
# ==========================================
_DL_PDF_HINTS = ["pdf"]
_DL_XML_HINTS = ["xml"]
_DL_HINTS = ["download", "tai", "export", "getfile", "/bill/"]


def _scan_download_links(page_html, page_url):
    """Tìm link tải PDF/XML trong HTML trang xem hóa đơn."""
    pdf_url = xml_url = None
    base = re.match(r"(https?://[^/]+)", page_url).group(1)

    hrefs = re.findall(r'(?:href|src|data-url)\s*=\s*["\']([^"\']+)["\']',
                       page_html or "", re.IGNORECASE)
    # cả URL trong JS: '/bill/download_pdf?...'
    hrefs += re.findall(r"""['"](/[^'"\s]*(?:pdf|xml|download)[^'"\s]*)['"]""",
                        page_html or "", re.IGNORECASE)

    for h in hrefs:
        h = unescape(h).strip()
        if h.startswith("//"):
            h = "https:" + h
        elif h.startswith("/"):
            h = base + h
        if not h.lower().startswith("http"):
            continue

        hl = h.lower()
        if not any(x in hl for x in _DL_HINTS + _DL_PDF_HINTS + _DL_XML_HINTS):
            continue
        if hl.endswith((".css", ".js", ".png", ".jpg", ".gif", ".svg")):
            continue

        if pdf_url is None and any(x in hl for x in _DL_PDF_HINTS):
            pdf_url = h
        elif xml_url is None and any(x in hl for x in _DL_XML_HINTS):
            xml_url = h

    return pdf_url, xml_url


# Khi có link PDF mà không thấy link XML: thử thay các biến thể 'pdf' -> 'xml'
# trong chính URL PDF (kiểu SoftDream DownloadInvPdf -> DownloadInvXml).
_PDF2XML_SUBS = [
    ("pdf", "xml"),
    ("Pdf", "Xml"),
    ("PDF", "XML"),
    ("download_pdf", "download_xml"),
    ("downloadpdf", "downloadxml"),
    ("export_pdf", "export_xml"),
]


def _guess_xml_from_pdf_url(pdf_url):
    """Sinh các URL XML khả dĩ từ URL PDF (loại trùng, giữ thứ tự)."""
    out, seen = [], set()
    for a, b in _PDF2XML_SUBS:
        if a in pdf_url:
            cand = pdf_url.replace(a, b)
            if cand != pdf_url and cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


# ==========================================
# SĂN XML KIỂU WIN (theo debug HTML 06/2026):
# Trang view_inv KHÔNG có nút XML. Iframe trỏ file tĩnh:
#   temp/<date>/<n>/<mst>/<kyhieu>_<sohd>_<matracuu>/C26TAA_00000275signed.html
# Nút PDF = /pdf?f=<url file html đó> (server render HTML->PDF).
# -> XML khả năng nằm CÙNG thư mục temp, tên anh em (.xml).
# ==========================================
def _abs_url(src, base):
    src = unescape(src or "").strip()
    if src.startswith("http"):
        return src
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return base + src
    return base + "/" + src


def _xml_candidates_from_view_file(page_html, page_url):
    """Đoán URL file XML trong thư mục temp từ src của iframe."""
    base = re.match(r"(https?://[^/]+)", page_url).group(1)

    view_files = []

    # iframe src
    m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', page_html or "",
                  re.IGNORECASE)
    if m:
        view_files.append(_abs_url(m.group(1), base))

    # tham số f= của nút PDF (/pdf?f=<url-encoded html>)
    m = re.search(r'[?&]f=([^"\'&\s]+)', page_html or "", re.IGNORECASE)
    if m:
        view_files.append(unquote(unescape(m.group(1))))

    cands, seen = [], set()
    for vf in view_files:
        if not vf.lower().endswith((".html", ".htm")):
            continue
        stem = re.sub(r"\.html?$", "", vf, flags=re.IGNORECASE)
        for c in (stem + ".xml",
                  re.sub(r"signed$", "", stem, flags=re.IGNORECASE) + ".xml",
                  re.sub(r"signed$", "", stem, flags=re.IGNORECASE).rstrip("_") + ".xml",
                  stem + ".zip"):
            if c not in seen:
                seen.add(c)
                cands.append(c)
    return cands


def _xml_from_bill_list(session, save_dir, default_name, referer):
    """
    Token view_inv đã tạo session cookie -> thử vào trang danh sách /bill/
    (nút 'Quay lại danh sách'), scan link tải XML trong đó.
    """
    try:
        r = session.get(BASE_URL + "/bill/", timeout=PAGE_TIMEOUT,
                        headers={"Referer": referer}, allow_redirects=True)
        if r.status_code != 200:
            return None
    except Exception as e:
        logger.debug("WIN: không vào được /bill/: %s", e)
        return None

    base = re.match(r"(https?://[^/]+)", r.url).group(1)
    hrefs = re.findall(r'(?:href|data-url)\s*=\s*["\']([^"\']+)["\']',
                       r.text or "", re.IGNORECASE)
    hrefs += re.findall(r"""['"](/[^'"\s]*xml[^'"\s]*)['"]""",
                        r.text or "", re.IGNORECASE)

    for h in hrefs:
        h = _abs_url(h, base)
        hl = h.lower()
        if "xml" not in hl:
            continue
        if hl.endswith((".css", ".js", ".png", ".jpg", ".gif", ".svg")):
            continue
        p = _try_get(session, h, save_dir, default_name, referer=r.url)
        if p:
            return p
    return None


def _download_via_requests(info, save_dir):
    """
    Trả về (pdf_ok, xml_ok) hoặc None nếu trang không truy cập được /
    không thấy link tải nào (-> Selenium lo cả 2).
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    page_url = info["view_url"] or info["lookup_url"]
    if not page_url and info["code"] and info["mst"]:
        page_url = f"{BASE_URL}/?mst={info['mst']}&cmpn={info['mst']}&code={info['code']}"

    if not page_url:
        return None

    try:
        r = session.get(page_url, timeout=PAGE_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        logger.error("WIN: không mở được trang tra cứu: %s", e)
        return None

    page_html = r.text

    pdf_url, xml_url = _scan_download_links(page_html, r.url)

    if not pdf_url and not xml_url:
        logger.warning("WIN: không thấy link tải trong HTML "
                       "(trang có thể render bằng JS)")
        return None  # -> Selenium

    so_hd = info["so_hd"]
    pdf_ok = xml_ok = False

    if pdf_url:
        if _try_get(session, pdf_url, save_dir, f"{so_hd}.pdf",
                    referer=page_url):
            pdf_ok = True

    if xml_url:
        if _try_get(session, xml_url, save_dir, f"{so_hd}.xml",
                    referer=page_url):
            xml_ok = True

    # ---- DỰ PHÒNG XML 1: endpoint anh em từ URL PDF ----
    if not xml_ok and pdf_url:
        for cand in _guess_xml_from_pdf_url(pdf_url):
            if _try_get(session, cand, save_dir, f"{so_hd}.xml",
                        referer=page_url):
                xml_ok = True
                print("WIN XML: tải được qua endpoint đoán:", cand)
                break

    # ---- DỰ PHÒNG XML 2: file anh em trong thư mục temp (từ iframe) ----
    # Đặt tên XML theo stem của file view (vd C26TAA_00000275signed.xml)
    # -> thành CẶP với PDF cùng tên (nguyên tắc #15)
    if not xml_ok:
        for cand in _xml_candidates_from_view_file(page_html, r.url):
            name = os.path.basename(urlsplit(cand).path) or f"{so_hd}.xml"
            if _try_get(session, cand, save_dir, name, referer=page_url):
                xml_ok = True
                break

    # ---- DỰ PHÒNG XML 3: trang danh sách /bill/ (session từ view_inv) ----
    if not xml_ok:
        if _xml_from_bill_list(session, save_dir, f"{so_hd}.xml", page_url):
            xml_ok = True
            print("WIN XML: tải được từ trang danh sách /bill/")

    # ---- Vẫn thiếu XML -> dump HTML để soi nút XML thật ----
    if not xml_ok:
        try:
            dbg = Path(save_dir) / "_debug_win_page.html"
            dbg.write_text(page_html, encoding="utf-8", errors="ignore")
            print("WIN: đã lưu HTML trang để debug:", dbg)
        except Exception:
            pass

    return (pdf_ok, xml_ok) if (pdf_ok or xml_ok) else None


# ==========================================
# FALLBACK SELENIUM (kiểu C)
# Mở trang chủ, điền Mã tra cứu + Mã công ty, bấm "Xem hóa đơn",
# rồi bấm nút tải PDF/XML. wait_download theo nguyên tắc #9.
# ==========================================
def _selenium_download(info, save_dir, need_pdf=True, need_xml=True):
    """Trả về (pdf_ok, xml_ok). Chỉ tải những phần được yêu cầu."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("WIN: chưa cài selenium, bỏ qua fallback")
        return False, False

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

    def wait_download(before, timeout=DOWNLOAD_TIMEOUT):
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

    def click_and_wait(xpaths, label):
        before = snapshot()
        for xp in xpaths:
            try:
                el = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, xp)))
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                break
            except Exception:
                continue
        else:
            print(f"WIN: không tìm thấy nút tải {label}")
            return False

        if wait_download(before):
            print(f"WIN {label} OK (selenium)")
            return True
        print(f"WIN {label}: timeout chờ tải (selenium)")
        return False

    PDF_XPATHS = [
        "//*[contains(text(),'Tải PDF')]",
        "//*[contains(text(),'PDF')]",
        "//*[contains(@href,'pdf') or contains(@onclick,'pdf')]",
        "//*[contains(@href,'Pdf') or contains(@onclick,'Pdf')]",
    ]
    XML_XPATHS = [
        "//*[contains(text(),'Tải XML')]",
        "//*[contains(text(),'XML')]",
        "//*[contains(@href,'xml') or contains(@onclick,'xml')]",
        "//*[contains(@href,'Xml') or contains(@onclick,'Xml')]",
    ]
    # Nút tải gộp (1 nút tải hết / tải zip)
    ALL_XPATHS = [
        "//*[contains(text(),'Tải hóa đơn')]",
        "//*[contains(text(),'Tải xuống')]",
        "//*[contains(text(),'Tải file')]",
        "//*[contains(@href,'download') or contains(@onclick,'download')]",
    ]

    try:
        # ---- Mở trang: ưu tiên link view_inv / lookup có sẵn tham số ----
        target = info["view_url"] or info["lookup_url"] or (BASE_URL + "/")
        driver.get(target)

        # ---- Nếu vẫn ở form tra cứu -> điền mã + bấm Xem hóa đơn ----
        def fill_if_form():
            try:
                inputs = driver.find_elements(By.XPATH,
                    "//input[@type='text' or not(@type)]")
                visible = [i for i in inputs if i.is_displayed()]
                if len(visible) >= 2 and info["code"] and info["mst"]:
                    visible[0].clear(); visible[0].send_keys(info["code"])
                    visible[1].clear(); visible[1].send_keys(info["mst"])
                    for xp in ["//*[contains(text(),'Xem hóa đơn')]",
                               "//button[contains(text(),'Xem')]",
                               "//*[contains(text(),'Tra cứu')]"]:
                        try:
                            WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, xp))
                            ).click()
                            return True
                        except Exception:
                            continue
            except Exception:
                pass
            return False

        page = driver.page_source
        if "Xem hóa đơn" in page and "Mã tra cứu" in page:
            if fill_if_form():
                time.sleep(3)  # chờ trang kết quả render

        pdf_ok = click_and_wait(PDF_XPATHS, "PDF") if need_pdf else False
        xml_ok = click_and_wait(XML_XPATHS, "XML") if need_xml else False

        # Không có nút riêng -> thử nút tải gộp
        if not pdf_ok and not xml_ok:
            if click_and_wait(ALL_XPATHS, "TẢI GỘP"):
                return True, True

        return pdf_ok, xml_ok

    except Exception as e:
        print("WIN SELENIUM ERROR:", e)
        return False, False
    finally:
        driver.quit()


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_win_invoice(body_text, save_dir):
    info = extract_win_info(body_text)

    if not info["code"] and not info["view_url"]:
        print("WIN: không tìm thấy mã tra cứu / link trong email")
        return False

    print("WIN CODE:", info["code"], "| MST:", info["mst"],
          "| SỐ HĐ:", info["so_hd"])

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # 1. Thử requests
    pdf_ok = xml_ok = False
    res = _download_via_requests(info, save_dir)
    if res:
        pdf_ok, xml_ok = res

    # 2. Selenium vớt những phần còn thiếu
    if (not pdf_ok or not xml_ok) and USE_SELENIUM_FALLBACK:
        if not pdf_ok and not xml_ok:
            print("WIN: requests không thấy link tải -> chuyển sang Selenium...")
        else:
            thieu = "XML" if pdf_ok else "PDF"
            print(f"WIN: requests thiếu {thieu} -> Selenium tải nốt...")

        sel_pdf, sel_xml = _selenium_download(
            info, save_dir,
            need_pdf=not pdf_ok,
            need_xml=not xml_ok,
        )
        pdf_ok = pdf_ok or sel_pdf
        xml_ok = xml_ok or sel_xml

    if not pdf_ok:
        print("WIN PDF: không tải được")
    if not xml_ok:
        print("WIN XML: không tải được")

    return pdf_ok or xml_ok


# ==========================================
# TEST OFFLINE
#   python win.py mau.eml        -> test nhận diện + extractor
#   python win.py --live mau.eml DIR -> chạy tải thật từ .eml
# ==========================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    def _body_from_eml(path):
        import email
        from email import policy
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body = "\n".join(
            p.get_content() for p in msg.walk()
            if p.get_content_type() in ("text/plain", "text/html"))
        return msg, body

    if len(sys.argv) >= 4 and sys.argv[1] == "--live":
        msg, body = _body_from_eml(sys.argv[2])
        print("KẾT QUẢ:", download_win_invoice(body, sys.argv[3]))

    elif len(sys.argv) > 1:
        msg, body = _body_from_eml(sys.argv[1])
        print("is_win_email :", is_win_email(msg["Subject"], "x@gmail.com", body))
        info = extract_win_info(body)
        for k, v in info.items():
            print(f"{k:11}:", v)