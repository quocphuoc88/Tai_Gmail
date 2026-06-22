# -*- coding: utf-8 -*-
"""
providers/misa.py  (v2)
Tải hóa đơn MISA meinvoice.vn bằng Selenium theo mã tra cứu.

Cải tiến so với v1:
- find_ma_tra_cuu: 3 tầng (link sc= -> TransactionID= -> text đã strip HTML),
  xử lý được mã bọc trong <strong>, label "nhập mã số" / "mã tra cứu",
  cả bản có dấu lẫn không dấu.
- WebDriverWait thay cho time.sleep cứng -> nhanh hơn và ổn định hơn.
- wait_download: chờ FILE MỚI xuất hiện và hết .crdownload (bản cũ chỉ check
  .crdownload, nếu Chrome chưa kịp tạo file thì thoát sớm tưởng là xong).
- save_dir ép về đường dẫn tuyệt đối (Chrome prefs không nhận đường dẫn tương đối).
"""

import re
import time
import os
from html import unescape

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Chế độ hiển thị cửa sổ Chrome khi tải MISA:
#   "hidden"   : cửa sổ THẬT nhưng đẩy ra NGOÀI màn hình -> không thấy, chạy y như
#                cũ nên KHÔNG sợ MISA chặn. (MẶC ĐỊNH - khuyên dùng)
#   "headless" : ẩn HOÀN TOÀN (không hiện cả trên taskbar), nhanh hơn; nhưng MISA
#                CÓ THỂ chặn -> nếu tải lỗi/timeout thì đổi lại "hidden".
#   "visible"  : hiện cửa sổ như trước (để gỡ lỗi khi cần xem Chrome làm gì).
CHROME_MODE = "hidden"

PAGE_TIMEOUT = 30      # giây chờ trang/nút xuất hiện
DOWNLOAD_TIMEOUT = 60  # giây chờ tải file


# ==========================================
# TÌM MÃ TRA CỨU (3 TẦNG)
# ==========================================
def _strip_html(html):

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "",
                  flags=re.IGNORECASE | re.DOTALL)

    text = re.sub(r"<[^>]+>", " ", text)

    text = unescape(text)

    return re.sub(r"\s+", " ", text)


def find_ma_tra_cuu(text):

    text = text or ""

    # Mã MISA gồm CHỮ HOA + SỐ + dấu gạch dưới (vd: 25FDS3REP_KM)

    # Tầng 1: link tra cứu ?sc=MA (tin cậy nhất)
    m = re.search(
        r"meinvoice\.vn/tra-cuu/?\?[^\"'<>\s]*?\bsc=([A-Za-z0-9_]{6,30})",
        text,
        re.IGNORECASE
    )

    if m:
        return m.group(1).upper()

    # Tầng 2: TransactionID= trong link tracking
    m = re.search(
        r"\bTransactionID=([A-Za-z0-9_]{6,30})",
        text,
        re.IGNORECASE
    )

    if m:
        return m.group(1).upper()

    # Tầng 3: text thuần sau khi bỏ tag HTML
    # (xử lý được:  nhập mã số: <strong>46F8FEG9LX3Z</strong>)
    plain = _strip_html(text)

    # - Label dùng (?i:...) để không phân biệt hoa thường
    # - Mã dùng class CHỮ HOA (case-sensitive) + (?![a-z]) để không
    #   nuốt chữ liền sau khi thiếu khoảng trắng:
    #   "nhập mã số: 25FDS3REP_KMQuý khách" -> lấy đúng 25FDS3REP_KM
    m = re.search(
        r"(?i:nh[aậ]p\s*m[aã]\s*s[oố]"
        r"|m[aã]\s*tra\s*c[uứ]+u?(?:\s*l[aà])?"
        r"|m[aã]\s*s[oố])"
        r"\s*[:\-]?\s*([A-Z0-9_]{6,30})(?![a-z])",
        plain
    )

    return m.group(1).upper() if m else None


# ==========================================
# CHỜ DOWNLOAD XONG (theo dõi FILE MỚI)
# ==========================================
def _snapshot(save_dir):

    try:
        return set(os.listdir(save_dir))
    except OSError:
        return set()


def wait_download(save_dir, files_before, timeout=DOWNLOAD_TIMEOUT):
    """
    Trả về True khi có ít nhất 1 file MỚI hoàn chỉnh
    (không còn đuôi .crdownload / .tmp) xuất hiện trong save_dir.
    """

    start = time.time()

    while time.time() - start < timeout:

        current = _snapshot(save_dir)

        new_files = current - files_before

        done = [
            f for f in new_files
            if not f.endswith((".crdownload", ".tmp"))
        ]

        downloading = any(
            f.endswith(".crdownload") for f in current
        )

        if done and not downloading:
            return True

        time.sleep(1)

    return False


# ==========================================
# CLICK NÚT THEO TEXT (có chờ)
# ==========================================
def _click_text(driver, text, timeout=PAGE_TIMEOUT):

    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(
            (By.XPATH, f"//*[contains(text(),'{text}')]")
        )
    )

    el.click()

    return el


# ==========================================
# CLICK AN TOÀN (thường -> JS fallback nếu bị che / chưa interactable)
# ==========================================
def _safe_click(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)


# ==========================================
# MỞ MENU "Tải hóa đơn"
# FIX: XPath cũ contains(text(),'Tải hóa đơn') TRÙNG với 2 dòng
# "Tải hóa đơn dạng PDF/XML" -> lần mở menu thứ 2 click nhầm item.
# Dùng khớp text CHÍNH XÁC (normalize-space) cho nút trigger.
# ==========================================
_OPEN_MENU_XPATHS = [
    "//*[normalize-space(text())='Tải hóa đơn']",
    "//*[contains(@class,'btn-download') or contains(@class,'download-invoice')]",
    "//a[contains(.,'Tải hóa đơn') and not(contains(.,'dạng'))]",
    "//button[contains(.,'Tải hóa đơn') and not(contains(.,'dạng'))]",
]


def _open_download_menu(driver, timeout=PAGE_TIMEOUT):
    last = None
    for xp in _OPEN_MENU_XPATHS:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            _safe_click(driver, el)
            return True
        except Exception as e:
            last = e
            continue
    print("MISA: không mở được menu 'Tải hóa đơn':", last)
    return False


# ==========================================
# CLICK 1 ITEM TẢI (PDF/XML) THEO CLASS CHÍNH XÁC
# Ưu tiên class ổn định (vd .txt-download-xml), fallback theo text.
# Item có thể đang ẩn -> JS click vẫn kích hoạt được handler tải.
# ==========================================
def _click_download_item(driver, css_list, text_label, timeout=10):
    selectors = [(By.CSS_SELECTOR, c) for c in css_list]
    selectors += [
        (By.XPATH,
         f"//*[contains(@class,'dm-item') and contains(normalize-space(.),'{text_label}')]"),
        (By.XPATH, f"//*[normalize-space(text())='{text_label}']"),
    ]
    for by, sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, sel))
            )
            _safe_click(driver, el)
            return True
        except Exception:
            continue
    print(f"MISA: không tìm thấy nút tải '{text_label}'")
    return False


# ==========================================
# TẠO CHROME CHO MỖI HÓA ĐƠN (mở riêng -> ổn định nhất)
# Lưu ý: từng thử dùng CHUNG 1 Chrome cho nhanh, nhưng tải vài hóa đơn xong
# bị timeout (Chrome lệ trạng thái / thư mục tải không bám) -> quay lại mở riêng.
# ==========================================
def _build_options(save_dir):
    opt = Options()
    opt.add_argument("--log-level=3")
    opt.add_experimental_option("excludeSwitches", ["enable-logging"])

    if CHROME_MODE == "headless":
        opt.add_argument("--headless=new")
        opt.add_argument("--window-size=1280,900")
        opt.add_argument("--disable-gpu")
    elif CHROME_MODE == "hidden":
        opt.add_argument("--window-position=-32000,-32000")
        opt.add_argument("--window-size=1280,900")
    # "visible": để nguyên.

    # Thư mục tải đặt THẲNG trong prefs -> chắc chắn đúng cho hóa đơn này.
    opt.add_experimental_option("prefs", {
        "download.default_directory": save_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    })
    return opt


def close_driver():
    """Engine gọi khi kết thúc phiên. Mỗi hóa đơn dùng Chrome riêng và tự đóng
    nên đây là no-op (giữ sẵn hook nếu sau này quay lại dùng Chrome chung)."""
    pass


# ==========================================
# HÀM CHÍNH TẢI HÓA ĐƠN MISA
# ==========================================
def download_misa_invoice(email_text, save_dir):

    ma_tra_cuu = find_ma_tra_cuu(email_text)

    if not ma_tra_cuu:

        print("MISA: Không tìm thấy mã tra cứu")
        return False

    print("MISA CODE:", ma_tra_cuu)

    save_dir = os.path.abspath(save_dir)

    os.makedirs(save_dir, exist_ok=True)

    # Mở Chrome RIÊNG cho hóa đơn này (đóng ở finally).
    # KHÔNG minimize: cửa sổ bị thu nhỏ sẽ bị Chrome "throttle" -> JS tải đứng,
    # gây timeout sau vài hóa đơn. Chế độ hidden đã đẩy cửa sổ ra NGOÀI màn hình
    # (vẫn coi là "visible" nên không bị throttle).
    driver = webdriver.Chrome(options=_build_options(save_dir))

    saved_any = False

    try:

        url = f"https://www.meinvoice.vn/tra-cuu/?sc={ma_tra_cuu}"

        driver.get(url)

        # ==========================================
        # PDF
        # ==========================================
        try:

            files_before = _snapshot(save_dir)

            _open_download_menu(driver)

            _click_download_item(
                driver,
                [".txt-download-pdf", ".dm-item.pdf"],
                "Tải hóa đơn dạng PDF",
            )

            if wait_download(save_dir, files_before):

                print("MISA PDF OK")
                saved_any = True

            else:
                print("MISA PDF: timeout chờ tải")

        except Exception as e:
            print("MISA PDF ERROR:", e)

        # ==========================================
        # XML
        # ==========================================
        try:

            files_before = _snapshot(save_dir)

            _open_download_menu(driver)

            _click_download_item(
                driver,
                [".txt-download-xml", ".dm-item.xml"],
                "Tải hóa đơn dạng XML",
            )

            if wait_download(save_dir, files_before):

                print("MISA XML OK")
                saved_any = True

            else:
                print("MISA XML: timeout chờ tải")

        except Exception as e:
            print("MISA XML ERROR:", e)

        return saved_any

    except Exception as e:
        print("MISA ERROR:", e)
        return saved_any

    finally:
        try:
            driver.quit()
        except Exception:
            pass