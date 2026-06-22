# -*- coding: utf-8 -*-
"""
providers/smartsign.py
Nhà cung cấp SmartSign / Chữ Ký Số Vi Na (tracuuhd(c).smartsign.com.vn) — vd COMECO.

Đặc điểm:
- Email không có file đính kèm, chỉ có MÃ TRA CỨU + link xem hóa đơn.
- Trang xem cần "2 BƯỚC COOKIE": vào lần 1 server đặt cookie (ASP.NET_SessionId),
  lần 2 (đã có cookie) mới ra hóa đơn. KHÔNG cần captcha cho luồng có mã (code-link).
- Tải bằng cách bấm nút "Tải file PDF/XML" (postback ASP.NET) -> Chrome tải file.
- Dùng Selenium (Chrome thật). Mỗi hóa đơn mở 1 Chrome riêng (giống MISA).

Interface khớp PROVIDERS trong engine:
    is_smartsign_email(subject, from_email, body_text) -> bool
    download_smartsign_invoice(body_text, save_dir, name_prefix="") -> bool
"""

import os
import re
import time
from html import unescape

# Chế độ cửa sổ Chrome: "hidden" (ngoài màn hình), "headless", "visible".
CHROME_MODE = "hidden"
DOWNLOAD_TIMEOUT = 60
PAGE_WAIT = 4

VIEWER_URL = "https://tracuuhdc.smartsign.com.vn/hddt/?code={code}&xdb=1"

BTN_IDS = {
    "PDF": "ContentPlaceHolder1_LinkButtonDownloadPDF",
    "XML": "ContentPlaceHolder1_LinkButtonDownloadXML",
}


# ==========================================
# NHẬN DIỆN EMAIL
# ==========================================
def is_smartsign_email(subject, from_email, body_text):
    f = (from_email or "").lower()
    if f.endswith("@smartsign.com.vn") or f.endswith("@smartvas.com.vn"):
        return True
    b = (body_text or "").lower()
    return ("smartsign.com.vn" in b) or ("tracuuhd" in b and "smartsign" in b)


def _strip_html(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text))


def extract_smartsign_code(body_text):
    # Ưu tiên mã trong link ?code=...
    m = re.search(r"[?&]code=([A-Za-z0-9]{8,30})", body_text or "")
    if m:
        return m.group(1)
    text = _strip_html(body_text or "")
    m = re.search(r"M[ãa]\s*tra\s*c[ứu]+u?\s*[:\-]?\s*([A-Za-z0-9]{8,30})", text, re.IGNORECASE)
    return m.group(1) if m else None


# ==========================================
# SELENIUM
# ==========================================
def _build_options(save_dir):
    from selenium.webdriver.chrome.options import Options
    opt = Options()
    opt.add_argument("--log-level=3")
    opt.add_experimental_option("excludeSwitches", ["enable-logging"])
    if CHROME_MODE == "headless":
        opt.add_argument("--headless=new")
        opt.add_argument("--window-size=1280,950")
        opt.add_argument("--disable-gpu")
    elif CHROME_MODE == "hidden":
        opt.add_argument("--window-position=-32000,-32000")
        opt.add_argument("--window-size=1280,950")
    opt.add_experimental_option("prefs", {
        "download.default_directory": save_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
        "safebrowsing.disable_download_protection": True,
    })
    return opt


def _snapshot(save_dir):
    try:
        return set(os.listdir(save_dir))
    except OSError:
        return set()


def _wait_download(save_dir, before, timeout=DOWNLOAD_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        cur = _snapshot(save_dir)
        done = [f for f in cur - before if not f.endswith((".crdownload", ".tmp"))]
        if done and not any(f.endswith(".crdownload") for f in cur):
            return True
        time.sleep(1)
    return False


# ==========================================
# HÀM CHÍNH
# ==========================================
def download_smartsign_invoice(body_text, save_dir, name_prefix=""):
    code = extract_smartsign_code(body_text)
    if not code:
        print("SMARTSIGN: không tìm thấy mã tra cứu")
        return False

    print("SMARTSIGN CODE:", code)
    save_dir = os.path.abspath(str(save_dir))
    os.makedirs(save_dir, exist_ok=True)
    url = VIEWER_URL.format(code=code)

    from selenium import webdriver
    from selenium.webdriver.common.by import By

    drv = webdriver.Chrome(options=_build_options(save_dir))
    # Cho phép tải kể cả file Chrome cho là "lạ" (.xml) -> tránh kẹt Unconfirmed
    try:
        drv.execute_cdp_cmd("Browser.setDownloadBehavior",
                            {"behavior": "allow", "downloadPath": save_dir, "eventsEnabled": True})
    except Exception:
        pass

    saved_any = False
    try:
        drv.get(url)          # lần 1: server đặt cookie
        time.sleep(2)
        drv.get(url)          # lần 2: ra hóa đơn
        time.sleep(PAGE_WAIT)

        if "Login.aspx" in drv.current_url:
            print("SMARTSIGN: bị chặn (Login/captcha), không tải được mã này")
            return False

        for label in ("PDF", "XML"):
            try:
                drv.get(url)          # nạp lại -> viewstate mới (cookie đã ấm)
                time.sleep(PAGE_WAIT)
                before = _snapshot(save_dir)
                el = drv.find_element(By.ID, BTN_IDS[label])
                drv.execute_script("arguments[0].click();", el)
                if _wait_download(save_dir, before):
                    print(f"SMARTSIGN {label} OK")
                    saved_any = True
                else:
                    print(f"SMARTSIGN {label}: timeout chờ tải")
            except Exception as e:
                print(f"SMARTSIGN {label} ERROR:", e)

        return saved_any
    except Exception as e:
        print("SMARTSIGN ERROR:", e)
        return saved_any
    finally:
        try:
            drv.quit()
        except Exception:
            pass
